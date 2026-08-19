import asyncio

from fastapi import APIRouter
from sqlmodel import Session
from starlette.websockets import WebSocket, WebSocketState, WebSocketDisconnect

from Api import logger
from Api.WebsocketConnectionManager.WebsocketConnectionManager import WebsocketConnectionManager
from Api.models.Command import Command, CommandBase
from Api.models.Device import Device
from Api.models.WebsocketResponses import WebsocketBleCommand, WebsocketBleSuccessResponse, BleDevice, \
    WebsocketBleDeviceResponse, WebsocketIrResponse
from BleKeyboard.BleKeyboard import BleKeyboard
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


# This is a bit finicky with some devices. On my ATV 4K, the pairing prompt only appears if it is manually triggered
# within a short time after connecting for the first time. I have built this into the `devices` property of the
# BleKeyboard class for now, which isn't super elegant but works.
# Pairing flow for the ATV 4K is thus:
# 1. Start advertisement
# 2. Select Equilibrium Virtual Keyboard in Apple TVs bluetooth settings
# 3. Send a devices query via websocket to trigger pairing (this should return connected: True, paired: False)
# 4. Confirm pairing on Apple TV
@router.websocket("/bt_pairing")
async def websocket_bt_pairing(websocket: WebSocket):

    ble_keyboard: BleKeyboard | None = websocket.state.ble_keyboard

    await websocket.accept()

    if ble_keyboard is None:
        await websocket.close(code=_UNAVAILABLE_CLOSE_CODE, reason="BLE is not available (dev mode or no adapter configured)")
        return

    while websocket.client_state == WebSocketState.CONNECTED:
        command = await websocket.receive_text()
        if command == WebsocketBleCommand.ADVERTISE:
            await ble_keyboard.advertise()
            await websocket.send_json(WebsocketBleSuccessResponse().model_dump())

        if command == WebsocketBleCommand.CONNECT:
            devices = await ble_keyboard.devices
            await  websocket.send_json(WebsocketBleDeviceResponse(devices=devices).model_dump())
            addr = await websocket.receive_text()
            await ble_keyboard.connect(addr)

        if command == WebsocketBleCommand.DISCONNECT:
            await ble_keyboard.disconnect()
            await websocket.send_json(WebsocketBleSuccessResponse().model_dump())

        if command == WebsocketBleCommand.DEVICES:
            devices = await ble_keyboard.devices
            await  websocket.send_json(WebsocketBleDeviceResponse(devices=devices).model_dump())


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
