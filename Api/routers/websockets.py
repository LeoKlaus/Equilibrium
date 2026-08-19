import asyncio

from fastapi import APIRouter
from sqlmodel import Session
from starlette.websockets import WebSocket, WebSocketState, WebSocketDisconnect

from Api import logger
from Api.WebsocketConnectionManager.WebsocketConnectionManager import WebsocketConnectionManager
from Api.models.Command import Command, CommandBase
from Api.models.Device import Device
from Api.models.WebsocketResponses import WebsocketIrResponse
from DbManager.DbManager import engine
from Hub.StatusStore import StatusStore
from IrManager.IrManager import IrManager

router = APIRouter(
    prefix="/ws",
    tags=["websockets"],
    responses={404: {"description": "Not found"}}
)

manager = WebsocketConnectionManager()

_UNAVAILABLE_CLOSE_CODE = 1013  # RFC 6455 "Try Again Later"


async def _record_ir_command(ir_manager: IrManager, data: dict, websocket: WebSocket) -> None:
    ir_manager.cancel_recording()

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
                code = await ir_manager.record_command(new_command.name, websocket)

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


@router.websocket("/commands")
async def websocket_commands(websocket: WebSocket):
    ir_manager: IrManager | None = websocket.state.ir_manager

    await websocket.accept()

    if ir_manager is None:
        await websocket.close(code=_UNAVAILABLE_CLOSE_CODE, reason="IR is not available (dev mode or no hardware configured)")
        return

    # TODO: This can break when cancelling/disconnecting during the recording process, fix this
    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            data = await websocket.receive_json()
            logger.debug(f"received: {data}")
            await _record_ir_command(ir_manager, data, websocket)

    except WebSocketDisconnect:
        logger.debug("Client disconnected from commands websocket")

@router.websocket("/status")
async def websocket_status(websocket: WebSocket):

    status_store: StatusStore = websocket.state.status_store

    await manager.connect(websocket)

    status_store.set_callback(manager.broadcast_json)

    await websocket.send_json(status_store.status.model_dump())

    try:
        while True:
            await websocket.receive_text()
            await websocket.send_text("This endpoint should only be used to receive status updates!")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.debug("Client disconnected from status websocket")


@router.websocket("/keyboard")
async def websocket_keyboard(websocket: WebSocket):
    # TODO: Implement forwarding key presses
    pass
