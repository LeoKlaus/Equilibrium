from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_status_store_ws
from api.routers import websockets
from hub.status_store import StatusStore


def _client_for(status_store: StatusStore) -> TestClient:
    app = FastAPI()
    app.include_router(websockets.router)
    app.dependency_overrides[get_status_store_ws] = lambda: status_store
    return TestClient(app)


async def test_status_sends_current_status_on_connect():
    status_store = StatusStore()
    await status_store.set_device_state(1, new_power_state=True)
    client = _client_for(status_store)

    with client.websocket_connect("/ws/status") as websocket:
        message = websocket.receive_json()

    assert message["devices"]["states"]["1"]["powered"] is True


async def test_status_rejects_inbound_text():
    client = _client_for(StatusStore())

    with client.websocket_connect("/ws/status") as websocket:
        websocket.receive_json()  # the status sent on connect

        websocket.send_text("hello")

        reply = websocket.receive_text()

    assert reply == "This endpoint should only be used to receive status updates!"


async def test_status_broadcasts_updates_to_an_open_connection():
    status_store = StatusStore()
    client = _client_for(status_store)

    with client.websocket_connect("/ws/status") as websocket:
        websocket.receive_json()  # the status sent on connect

        await status_store.set_device_state(1, new_power_state=True)

        broadcast = websocket.receive_json()

    assert broadcast["devices"]["states"]["1"]["powered"] is True


def test_status_removes_the_connection_once_it_disconnects():
    status_store = StatusStore()
    client = _client_for(status_store)

    before = len(websockets.manager.active_connections)
    with client.websocket_connect("/ws/status") as ws:
        ws.receive_json()
        during = len(websockets.manager.active_connections)
    after = len(websockets.manager.active_connections)

    assert during == before + 1
    assert after == before
