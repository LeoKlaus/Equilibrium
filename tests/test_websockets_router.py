import asyncio
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnected

from api.dependencies import get_log_broadcaster_ws, get_status_store_ws
from api.log_broadcaster import LogBroadcaster
from api.models.log_line import LogLine
from api.routers import websockets
from hub.status_store import StatusStore


def _client_for(status_store: StatusStore) -> TestClient:
    app = FastAPI()
    app.include_router(websockets.router)
    app.dependency_overrides[get_status_store_ws] = lambda: status_store
    return TestClient(app)


def _client_for_logs(broadcaster: LogBroadcaster) -> TestClient:
    app = FastAPI()
    app.include_router(websockets.router)
    app.dependency_overrides[get_log_broadcaster_ws] = lambda: broadcaster
    return TestClient(app)


def _make_record(message: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=message, args=(), exc_info=None,
    )


def _line(message: str) -> LogLine:
    return LogLine(timestamp="12:00:00", level="INFO", logger="test", message=message, formatted=message)


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


async def test_logs_sends_the_backlog_on_connect():
    broadcaster = LogBroadcaster(asyncio.get_running_loop())
    broadcaster.emit(_make_record("already logged"))
    await asyncio.sleep(0)
    client = _client_for_logs(broadcaster)

    with client.websocket_connect("/ws/logs") as websocket:
        message = websocket.receive_json()

    assert message["message"] == "already logged"


async def test_logs_rejects_inbound_text():
    client = _client_for_logs(LogBroadcaster(asyncio.get_running_loop()))

    with client.websocket_connect("/ws/logs") as websocket:
        websocket.send_text("hello")
        reply = websocket.receive_text()

    assert reply == "This endpoint should only be used to receive log updates!"


async def test_logs_broadcasts_new_lines_to_an_open_connection():
    # Goes through broadcaster.manager directly, the same fan-out
    # emit() itself ultimately schedules onto - emit()'s cross-thread
    # call_soon_threadsafe scheduling is covered in its own right by
    # test_log_broadcaster.py, without a real websocket transport
    # involved. Awaiting it straight through (like status's own
    # broadcast test does) is what makes this deterministic: the
    # blocking receive_json() below can't itself pump the event loop,
    # so the send has to be fully finished before it's called.
    broadcaster = LogBroadcaster(asyncio.get_running_loop())
    client = _client_for_logs(broadcaster)

    with client.websocket_connect("/ws/logs") as websocket:
        await broadcaster.manager.broadcast_json(_line("live line"))

        message = websocket.receive_json()

    assert message["message"] == "live line"


def test_logs_removes_the_connection_once_it_disconnects():
    broadcaster = LogBroadcaster(asyncio.new_event_loop())  # never run - this test needs no broadcast
    client = _client_for_logs(broadcaster)

    before = len(broadcaster.manager.active_connections)
    with client.websocket_connect("/ws/logs"):
        during = len(broadcaster.manager.active_connections)
    after = len(broadcaster.manager.active_connections)

    assert during == before + 1
    assert after == before


def _patch_send_json(monkeypatch, before_send):
    """Runs `before_send(call_number)` before every send_json of every websocket."""
    original = WebSocket.send_json
    calls = {"count": 0}

    async def send_json(self, data, mode="text"):
        calls["count"] += 1
        before_send(calls["count"])
        await original(self, data, mode)

    monkeypatch.setattr(WebSocket, "send_json", send_json)


async def test_logs_replays_the_whole_backlog_even_when_sending_logs_something(monkeypatch):
    # With DEBUG logging every send is itself logged, so the backlog grows while it is replayed
    broadcaster = LogBroadcaster(asyncio.get_running_loop())
    for index in range(5):
        broadcaster.backlog.append(_line(f"line {index}"))
    _patch_send_json(monkeypatch, lambda call: broadcaster.backlog.append(_line("logged by the send")))
    client = _client_for_logs(broadcaster)

    with client.websocket_connect("/ws/logs") as websocket:
        messages = [websocket.receive_json()["message"] for _ in range(5)]

    assert messages == [f"line {index}" for index in range(5)]


def _raise_disconnected(call):
    raise WebSocketDisconnected("Cannot call \"send\" once a close message has been sent.")


async def test_logs_removes_the_connection_when_replaying_fails(monkeypatch):
    broadcaster = LogBroadcaster(asyncio.get_running_loop())
    broadcaster.backlog.append(_line("a line"))
    _patch_send_json(monkeypatch, _raise_disconnected)
    client = _client_for_logs(broadcaster)

    with client.websocket_connect("/ws/logs"):
        pass

    assert broadcaster.manager.active_connections == []


async def test_status_removes_the_connection_when_the_first_send_fails(monkeypatch):
    before = len(websockets.manager.active_connections)
    _patch_send_json(monkeypatch, _raise_disconnected)
    client = _client_for(StatusStore())

    with client.websocket_connect("/ws/status"):
        pass

    assert len(websockets.manager.active_connections) == before
