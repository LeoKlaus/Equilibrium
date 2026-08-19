from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect

from Api import logger
from Api.WebsocketConnectionManager.WebsocketConnectionManager import WebsocketConnectionManager
from Hub.StatusStore import StatusStore

router = APIRouter(
    prefix="/ws",
    tags=["websockets"],
    responses={404: {"description": "Not found"}}
)

manager = WebsocketConnectionManager()


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
