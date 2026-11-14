from collections.abc import Awaitable, Callable
from typing import Any

from sqlmodel import SQLModel
from starlette.websockets import WebSocket

from api import logger

AsyncJsonCallback = Callable[[Any], Awaitable[None]]

class WebsocketConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast_json(self, message: SQLModel):
        payload = message.model_dump()
        for connection in list(self.active_connections):
            try:
                await connection.send_json(payload)
            except Exception as error:
                self.disconnect(connection)
                logger.debug(f"Dropped a websocket connection that couldn't be reached: {type(error).__name__}")
