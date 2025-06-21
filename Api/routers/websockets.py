from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketState, WebSocketDisconnect

from RemoteController.RemoteController import RemoteController

router = APIRouter(
    prefix="/ws",
    tags=["websockets"],
    responses={404: {"description": "Not found"}}
)

@router.websocket("/bt_pairing")
async def websocket_bt_pairing(websocket: WebSocket):

    # TODO: Implement bluetooth pairing via websocket

    await websocket.accept()

    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            data = await websocket.receive_json()
            print(f"received: {data}")

    except WebSocketDisconnect:
        print("ws disconnected")


@router.websocket("/commands")
async def websocket_commands(websocket: WebSocket):

    # TODO: Implement recording/sending commands via websocket

    controller: RemoteController = websocket.state.controller

    await websocket.accept()

    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            data = await websocket.receive_json()
            print(f"received: {data}")
            await  controller.record_ir_command(data, websocket.send_text)

    except WebSocketDisconnect:
        print("ws disconnected")