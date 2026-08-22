import asyncio
import atexit
import logging
from asyncio import Task
from collections.abc import Awaitable, Callable
from typing import ClassVar

from fastapi import APIRouter
from sqlmodel import Session
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from api.models.command import Command, CommandBase
from api.models.device import Device
from api.models.websocket_responses import WebsocketIrResponse
from db_manager.db_manager import engine
from hub.event_bus import Directive
from hub.interfaces import ActionExecutor
from ir_manager.lirc_device import LircReceiver, LircTransmitter

AsyncCallback = Callable[[str], Awaitable[None]]

# A captured code shorter than this many edges is treated as noise/a
# repeat rather than a real press - matches the old pigpio-based
# recorder's threshold.
_MIN_CODE_LENGTH = 8


class IrManager(ActionExecutor):

    name = "ir"
    capabilities: ClassVar[list[str]] = ["command_recording"]

    logger = logging.getLogger(__package__)
    recording_task: Task|None = None
    sending_task: Task|None = None

    def __init__(self):
        self.logger.info("Connecting...")
        self.tx = LircTransmitter()
        self.rx = LircReceiver()
        self.logger.info("Done")

        self.repeating = False

        self.router = self._build_router()

        atexit.register(self.cleanup)

    def cleanup(self):
        self.logger.info("Disconnecting from GPIO...")
        self.tx.close()
        self.rx.close()

    def _build_router(self) -> APIRouter:
        router = APIRouter(
            prefix="/ws",
            tags=["websockets"],
            responses={404: {"description": "Not found"}},
        )

        @router.websocket("/commands")
        async def websocket_commands(websocket: WebSocket):
            await websocket.accept()

            try:
                while websocket.client_state == WebSocketState.CONNECTED:
                    data = await websocket.receive_json()
                    self.logger.debug(f"received: {data}")
                    closed = await self._record_ir_command(data, websocket)
                    if closed:
                        break
            except WebSocketDisconnect:
                self.logger.debug("Client disconnected from commands websocket")

        return router

    async def _record_ir_command(self, data: dict, websocket: WebSocket) -> bool:
        """Returns True if this call closed the websocket (a cancelled
        recording), telling the caller to stop looping instead of calling
        receive_json() again on an already-closed connection."""
        self.cancel_recording()

        with Session(engine) as session:
            new_command = CommandBase.model_validate(data)
            if new_command:
                db_command = Command.model_validate(data)

                if new_command.device_id:
                    db_device = session.get(Device, new_command.device_id)
                    db_command.device_id = new_command.device_id
                    db_command.device = db_device

                db_command.type = new_command.type

                try:
                    code = await self.record_command(new_command.name, websocket)

                    if code:
                        db_command.ir_action = code

                        session.add(db_command)
                        session.commit()
                        session.refresh(db_command)
                        await websocket.send_json(WebsocketIrResponse.DONE)

                except asyncio.CancelledError:
                    if websocket.application_state == WebSocketState.CONNECTED:
                        try:
                            await websocket.send_json(WebsocketIrResponse.CANCELLED)
                            await websocket.close()
                        except (WebSocketDisconnect, RuntimeError):
                            pass
                    return True

        return False

    async def execute(self, directive: Directive, command: Command) -> None:
        if not command.ir_action:
            self.logger.error(f"Command {command.name} doesn't include an IR action")
            return

        if directive.press_without_release:
            await self.send_and_repeat(command.ir_action)
        else:
            await self.send_command(command.ir_action)

    async def send_and_repeat(self, code: list[int]):
        self.cancel_sending()
        self.sending_task = asyncio.create_task(self._send_and_repeat(code))

    def cancel_sending(self):
        if self.sending_task is not None and not self.sending_task.cancelled():
            self.sending_task.cancel()
            self.sending_task = None

    async def _send_and_repeat(self, code: list[int]):
        while True:
            try:
                await self.send_command(code)
            except Exception as e:
                self.cancel_sending()
                self.logger.exception(e)
            await asyncio.sleep(0.25)

    def stop_repeating(self):
        self.cancel_sending()


    async def send_command(self, code: list[int]):
        # transmit() is a blocking write() syscall - offload it, or a
        # send stalls whatever else is pending on the event loop.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.tx.transmit, code)
        self.logger.debug("Sent IR command")


    async def record_command(self, name: str, websocket: WebSocket | None = None) -> list[int] | None:
        #self.cancel_recording()
        self.recording_task = asyncio.create_task(self._record_command(name, websocket))
        return await self.recording_task

    async def _record_command(self, name: str, websocket: WebSocket | None = None) -> list[int] | None:

        async def send_message(msg: str):
            self.logger.debug(msg)
            if websocket is not None and websocket.client_state == WebSocketState.CONNECTED:
                try:
                    await websocket.send_json(msg)
                except  WebSocketDisconnect:
                    self.cancel_recording()

        def normalise(c):
            entries = len(c)
            p = [0] * entries  # Set all entries not processed.
            for i in range(entries):
                if not p[i]:  # Not processed?
                    v = c[i]
                    tot = v
                    similar = 1.0
                    for j in range(i + 2, entries, 2):  # Find unprocessed similar.
                        if not p[j] and c[j] * 0.8 < v < c[j] * 1.2:  # Unprocessed and similar.
                            tot = tot + c[j]
                            similar += 1.0
                    newv = tot / similar
                    c[i] = newv
                    for j in range(i + 2, entries, 2):  # Normalise similar.
                        if not p[j] and c[j] * 0.8 < v < c[j] * 1.2:  # Unprocessed and similar.
                            c[j] = newv
                            p[j] = 1

        def compare(p1, p2):
            if len(p1) != len(p2):
                return False
            for i in range(len(p1)):
                if p2[i] == 0:
                    return False
                v = p1[i] / p2[i]
                if (v < 0.8) or (v > 1.2):
                    return False
            for i in range(len(p1)):
                p1[i] = round((p1[i] + p2[i]) / 2.0)
            return True

        async def receive_valid_code() -> list[int]:
            """Blocks until a code long enough to be a real press (not
            noise/a repeat) is captured, notifying the client and
            retrying on anything shorter."""
            loop = asyncio.get_running_loop()
            while True:
                code = await loop.run_in_executor(None, self.rx.receive_code)
                if len(code) > _MIN_CODE_LENGTH:
                    normalise(code)
                    return code
                await send_message(WebsocketIrResponse.SHORT_CODE)

        await send_message(WebsocketIrResponse.PRESS_KEY)
        press_1 = await receive_valid_code()

        match = False
        tries = 0

        while not match:
            if tries > 4:
                await send_message(WebsocketIrResponse.TOO_MANY_RETRIES)
                return None

            await send_message(WebsocketIrResponse.REPEAT_KEY)
            press_2 = await receive_valid_code()

            the_same = compare(press_1, press_2)

            if the_same:
                match = True

            tries += 1

        return press_1

    def cancel_recording(self):
        if self.recording_task is not None and not self.recording_task.cancelled():
            self.recording_task.cancel()
            self.logger.info("Cancelled IR recording task")
            self.recording_task = None
