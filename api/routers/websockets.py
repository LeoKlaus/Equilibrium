from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect

from api import logger
from api.dependencies import LogBroadcasterWsDep, StatusStoreWsDep
from api.websocket_connection_manager.websocket_connection_manager import WebsocketConnectionManager

router = APIRouter(
    prefix="/ws",
    tags=["websockets"],
    responses={404: {"description": "Not found"}}
)

manager = WebsocketConnectionManager()


@router.websocket("/status")
async def websocket_status(websocket: WebSocket, status_store: StatusStoreWsDep):

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


@router.websocket("/logs")
async def websocket_logs(websocket: WebSocket, log_broadcaster: LogBroadcasterWsDep):
    await log_broadcaster.manager.connect(websocket)

    for line in log_broadcaster.backlog:
        await websocket.send_json(line.model_dump())

    try:
        while True:
            await websocket.receive_text()
            await websocket.send_text("This endpoint should only be used to receive log updates!")
    except WebSocketDisconnect:
        log_broadcaster.manager.disconnect(websocket)
        logger.debug("Client disconnected from logs websocket")
