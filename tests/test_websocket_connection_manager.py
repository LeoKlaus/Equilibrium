import logging

import pytest
from sqlmodel import SQLModel

from api.websocket_connection_manager.websocket_connection_manager import WebsocketConnectionManager


class Message(SQLModel):
    text: str


class FakeConnection:
    def __init__(self, error: Exception | None = None):
        self.received: list[dict] = []
        self.attempts = 0
        self._error = error

    async def send_json(self, payload):
        self.attempts += 1
        if self._error is not None:
            raise self._error
        self.received.append(payload)


def _manager_with(*connections: FakeConnection) -> WebsocketConnectionManager:
    manager = WebsocketConnectionManager()
    manager.active_connections.extend(connections)  # type: ignore[arg-type]  # duck-typed test double
    return manager


async def test_broadcast_sends_to_every_connection():
    first, second = FakeConnection(), FakeConnection()

    await _manager_with(first, second).broadcast_json(Message(text="hi"))

    assert first.received == second.received == [{"text": "hi"}]


async def test_a_connection_that_fails_is_dropped_and_the_others_still_receive():
    dead = FakeConnection(error=RuntimeError('Cannot call "send" once a close message has been sent.'))
    alive = FakeConnection()
    manager = _manager_with(dead, alive)

    await manager.broadcast_json(Message(text="hi"))  # must not raise

    assert alive.received == [{"text": "hi"}]
    assert manager.active_connections == [alive]


async def test_a_dropped_connection_is_not_tried_again():
    dead = FakeConnection(error=RuntimeError("gone"))
    manager = _manager_with(dead)

    await manager.broadcast_json(Message(text="one"))
    await manager.broadcast_json(Message(text="two"))

    assert dead.attempts == 1


async def test_connections_failing_in_a_row_are_all_dropped():
    manager = _manager_with(FakeConnection(error=RuntimeError("a")), FakeConnection(error=RuntimeError("b")))

    await manager.broadcast_json(Message(text="hi"))

    assert manager.active_connections == []


def test_disconnecting_an_unknown_connection_does_nothing():
    manager = _manager_with()

    manager.disconnect(FakeConnection())  # type: ignore[arg-type]  # duck-typed test double


def test_disconnecting_twice_does_nothing():
    connection = FakeConnection()
    manager = _manager_with(connection)

    manager.disconnect(connection)  # type: ignore[arg-type]  # duck-typed test double
    manager.disconnect(connection)  # type: ignore[arg-type]  # duck-typed test double

    assert manager.active_connections == []


async def test_a_failing_connection_is_only_noted_at_debug(caplog):
    manager = _manager_with(FakeConnection(error=RuntimeError("gone")))

    with caplog.at_level(logging.DEBUG, logger="api"):
        await manager.broadcast_json(Message(text="hi"))

    assert [record.levelno for record in caplog.records if "Dropped" in record.getMessage()] == [logging.DEBUG]


@pytest.mark.parametrize("error", [RuntimeError("closed"), ConnectionResetError(), OSError("broken pipe")])
async def test_any_failure_to_send_drops_the_connection(error):
    manager = _manager_with(FakeConnection(error=error))

    await manager.broadcast_json(Message(text="hi"))

    assert manager.active_connections == []
