from typing import Callable, Awaitable

from starlette.websockets import WebSocket

AsyncJsonCallback = Callable[[any], Awaitable[None]]

class WebsocketConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast_json(self, message):
        for connection in self.active_connections:
            await connection.send_json(message)