import asyncio
import atexit
import logging
import time
from asyncio import Task
from collections.abc import Awaitable, Callable
from typing import ClassVar

import pigpio
from fastapi import APIRouter
from sqlmodel import Session
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from Api.models.Command import Command, CommandBase
from Api.models.Device import Device
from Api.models.WebsocketResponses import WebsocketIrResponse
from db_manager.db_manager import engine
from Hub.EventBus import Directive
from Hub.interfaces import ActionExecutor

AsyncCallback = Callable[[str], Awaitable[None]]

PRE = 20
POST = 20
RXGPIO = 17
GLIT = 100
PRE_US = PRE * 1000

TXGPIO = 18
FREQ = 38


class IrManager(ActionExecutor):

    name = "ir"
    capabilities: ClassVar[list[str]] = ["command_recording"]

    logger = logging.getLogger(__package__)
    recording_task: Task|None = None
    sending_task: Task|None = None

    def __init__(self):
        self.logger.info("Connecting...")
        self.pi = pigpio.pi()
        self.logger.info("Done")

        self.repeating = False

        self.router = self._build_router()

        atexit.register(self.cleanup)

    def cleanup(self):
        self.logger.info("Disconnecting from GPIO...")
        self.pi.stop()

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
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.send_json(WebsocketIrResponse.CANCELLED)
                        await websocket.close()
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
        # pigpio's socket API is blocking - every call in _blocking_send must
        # run off the event loop, or a send stalls whatever else is pending
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._blocking_send, code)
        self.logger.debug("Sent IR command")

    def _blocking_send(self, code: list[int]):
        def carrier(gpio, frequency, micros, dutycycle=0.5):
            """
            Generate cycles of carrier on gpio with frequency and dutycycle.
            """
            nonlocal wf
            wf = []
            cycle = 1000.0 / frequency
            cycles = round(micros / cycle)
            on = round(cycle * dutycycle)
            sofar = 0
            for c in range(cycles):
                target = round((c + 1) * cycle)
                sofar += on
                off = target - sofar
                sofar += off
                wf.append(pigpio.pulse(1 << gpio, 0, on))
                wf.append(pigpio.pulse(0, 1 << gpio, off))
            return wf

        self.pi.set_mode(TXGPIO, pigpio.OUTPUT)  # IR TX connected to this GPIO.

        self.pi.wave_add_new()

        # Check marks
        marks = {}
        for i in range(0, len(code), 2):
            if code[i] not in marks:
                marks[code[i]] = -1

        for i in marks:
            wf = carrier(TXGPIO, FREQ, i)
            self.pi.wave_add_generic(wf)
            wid = self.pi.wave_create()
            marks[i] = wid

        # Check spaces
        spaces = {}
        for i in range(1, len(code), 2):
            if code[i] not in spaces:
                spaces[code[i]] = -1

        for i in spaces:
            self.pi.wave_add_generic([pigpio.pulse(0, 0, i)])
            wid = self.pi.wave_create()
            spaces[i] = wid

        # Create wave
        wave = [0] * len(code)
        for i in range(0, len(code)):
            if i & 1:  # Space
                wave[i] = spaces[code[i]]
            else:  # Mark
                wave[i] = marks[code[i]]

        self.pi.wave_chain(wave)

        while self.pi.wave_tx_busy():
            time.sleep(0.05)

        for i in marks:
            self.pi.wave_delete(marks[i])
        for i in spaces:
            self.pi.wave_delete(spaces[i])


    async def record_command(self, name: str, websocket: WebSocket | None = None) -> list[int] | None:
        #self.cancel_recording()
        self.recording_task = asyncio.create_task(self._record_command(name, websocket))
        return await self.recording_task

    async def _record_command(self, name: str, websocket: WebSocket | None = None) -> list[int] | None:

        last_tick = None
        in_code = False
        code: list[int] = []
        code_done = False

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

        def end_of_code():
            nonlocal code, code_done
            if len(code) > 8:
                normalise(code)
                code_done = True
            else:
                code = []
                asyncio.run(send_message(WebsocketIrResponse.SHORT_CODE))
                # send_websocket_message("Short code, probably a repeat. Please try again.")

        def cbf(_, level, tick):
            nonlocal last_tick, in_code, code, code_done
            if last_tick is not None:
                if level != pigpio.TIMEOUT:
                    edge = pigpio.tickDiff(last_tick, tick)
                    if edge > PRE_US:  # Start or stop of a code.
                        if in_code:
                            in_code = False
                            self.pi.set_watchdog(RXGPIO, 0)  # Cancel watchdog.
                            end_of_code()
                        else:
                            if not code_done:
                                in_code = True
                                self.pi.set_watchdog(RXGPIO, POST)  # Start watchdog.
                    else:
                        if in_code:
                            code.append(edge)
                else:  # Timeout.
                    self.pi.set_watchdog(RXGPIO, 0)  # Cancel watchdog.
                    if in_code:
                        in_code = False
                        end_of_code()
            if level != pigpio.TIMEOUT:
                last_tick = tick

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

        self.pi.set_mode(RXGPIO, pigpio.INPUT) # IR RX connected to this GPIO.
        self.pi.set_glitch_filter(RXGPIO, GLIT) # Ignore glitches.

        _ = self.pi.callback(RXGPIO, pigpio.EITHER_EDGE, cbf)

        code = []
        code_done = False

        await send_message(WebsocketIrResponse.PRESS_KEY)

        while not code_done:
            await asyncio.sleep(0.1)

        press_1 = code[:]
        match = False
        tries = 0

        while not match:
            code = []
            code_done = False
            if tries > 4:
                await send_message(WebsocketIrResponse.TOO_MANY_RETRIES)
                return None

            await send_message(WebsocketIrResponse.REPEAT_KEY)

            while not code_done:
                await asyncio.sleep(0.1)

            press_2 = code[:]
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
