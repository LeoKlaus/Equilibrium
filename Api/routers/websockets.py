from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketState, WebSocketDisconnect

from Api import logger
from Api.WebsocketConnectionManager.WebsocketConnectionManager import WebsocketConnectionManager
from Api.models.WebsocketResponses import WebsocketBleCommand, WebsocketBleSuccessResponse, BleDevice, \
    WebsocketBleDeviceResponse
from RemoteController.RemoteController import RemoteController

router = APIRouter(
    prefix="/ws",
    tags=["websockets"],
    responses={404: {"description": "Not found"}}
)

manager = WebsocketConnectionManager()


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

    controller: RemoteController = websocket.state.controller

    await websocket.accept()

    while websocket.client_state == WebSocketState.CONNECTED:
        command = await websocket.receive_text()
        if command == WebsocketBleCommand.ADVERTISE:
            await controller.start_ble_advertisement()
            await websocket.send_json(WebsocketBleSuccessResponse().model_dump_json())

        if command == WebsocketBleCommand.CONNECT:
            devices = await controller.get_ble_devices()
            await  websocket.send_json(WebsocketBleDeviceResponse(devices=devices).model_dump_json())
            addr = await websocket.receive_text()
            await controller.ble_connect(addr)

        if command == WebsocketBleCommand.DISCONNECT:
            await controller.ble_disconnect()
            await websocket.send_json(WebsocketBleSuccessResponse().model_dump_json())

        if command == WebsocketBleCommand.DEVICES:
            devices = await controller.get_ble_devices()
            await  websocket.send_json(WebsocketBleDeviceResponse(devices=devices).model_dump_json())


@router.websocket("/commands")
async def websocket_commands(websocket: WebSocket):
    controller: RemoteController = websocket.state.controller

    await websocket.accept()

    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            data = await websocket.receive_json()
            logger.debug(f"received: {data}")
            await  controller.record_ir_command(data, websocket.send_json)

    except WebSocketDisconnect:
        logger.debug("Websocket disconnected.")

@router.websocket("/status")
async def websocket_status(websocket: WebSocket):

    controller: RemoteController = websocket.state.controller

    await manager.connect(websocket)

    controller.status_callback = manager.broadcast_json

    await websocket.send_json(controller.active_scene_status.model_dump_json())

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