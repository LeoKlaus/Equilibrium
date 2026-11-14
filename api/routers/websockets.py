from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketDisconnected

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

    try:
        status_store.set_callback(manager.broadcast_json)

        await websocket.send_json(status_store.status.model_dump())

        while True:
            await websocket.receive_text()
            await websocket.send_text("This endpoint should only be used to receive status updates!")
    except (WebSocketDisconnect, WebSocketDisconnected):
        logger.debug("Client disconnected from status websocket")
    finally:
        manager.disconnect(websocket)


@router.websocket("/keyboard")
async def websocket_keyboard(websocket: WebSocket):
    # TODO: Implement forwarding key presses
    pass


@router.websocket("/logs")
async def websocket_logs(websocket: WebSocket, log_broadcaster: LogBroadcasterWsDep):
    await log_broadcaster.manager.connect(websocket)

    try:
        for line in list(log_broadcaster.backlog):
            await websocket.send_json(line.model_dump())

        while True:
            await websocket.receive_text()
            await websocket.send_text("This endpoint should only be used to receive log updates!")
    except (WebSocketDisconnect, WebSocketDisconnected):
        logger.debug("Client disconnected from logs websocket")
    finally:
        log_broadcaster.manager.disconnect(websocket)
