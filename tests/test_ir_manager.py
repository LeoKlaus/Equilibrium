import asyncio
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from api.models.command import Command
from api.models.command_group_type import CommandGroupType
from api.models.command_type import CommandType
from api.models.device import Device
from api.models.device_type import DeviceType
from api.models.remote_button import RemoteButton
from api.models.websocket_responses import WebsocketIrResponse
from hub.event_bus import Directive
from ir_manager.ir_manager import IrManager


class FakeLircTransmitter:
    """Stands in for LircTransmitter - avoids needing a real /dev/lircX
    device. `delay` simulates transmit()'s blocking write() syscall
    taking real time, for the offloading test."""

    def __init__(self, delay: float = 0.0):
        self.calls: list[list[int]] = []
        self._delay = delay

    def transmit(self, pulses):
        if self._delay:
            time.sleep(self._delay)
        self.calls.append(list(pulses))

    def close(self):
        pass


class FakeLircReceiver:
    """Stands in for LircReceiver - avoids needing a real /dev/lircX
    device. Feed it a sequence of pre-baked codes via `codes`; each
    receive_code() call (as run_in_executor would call it - synchronously,
    off the event loop) pops the next one."""

    def __init__(self, codes: list[list[int]] | None = None):
        self._codes = list(codes) if codes is not None else []

    def receive_code(self) -> list[int]:
        return self._codes.pop(0)

    def close(self):
        pass


def _ir_manager(tx=None, rx=None) -> IrManager:
    # Bypasses __init__ (which opens real /dev/lircX devices and
    # registers an atexit hook) so tests never need real hardware.
    manager = IrManager.__new__(IrManager)
    manager.tx = tx if tx is not None else FakeLircTransmitter()
    manager.rx = rx if rx is not None else FakeLircReceiver()
    manager.repeating = False
    manager.recording_task = None
    manager.sending_task = None
    manager.router = manager._build_router()
    return manager


def _command(**overrides) -> Command:
    defaults = {
        "name": "cmd",
        "button": RemoteButton.PLAY,
        "type": CommandType.IR,
        "command_group": CommandGroupType.TRANSPORT,
    }
    defaults.update(overrides)
    return Command(**defaults)


async def test_send_command_transmits_the_code_as_is():
    tx = FakeLircTransmitter()
    manager = _ir_manager(tx=tx)

    await manager.send_command([100, 200, 100, 200])

    assert tx.calls == [[100, 200, 100, 200]]


async def test_send_command_offloads_the_blocking_work():
    # ~200ms simulating transmit()'s blocking write() syscall - if that
    # ran on the event loop thread instead of an executor, ticker()'s
    # sleeps would get delayed too, pushing total elapsed time toward
    # the SUM of both durations instead of their MAX.
    tx = FakeLircTransmitter(delay=0.2)
    manager = _ir_manager(tx=tx)

    async def ticker() -> int:
        ticks = 0
        for _ in range(8):
            await asyncio.sleep(0.02)
            ticks += 1
        return ticks

    loop = asyncio.get_running_loop()
    start = loop.time()
    _, ticks = await asyncio.gather(manager.send_command([100, 200]), ticker())
    elapsed = loop.time() - start

    assert ticks == 8
    assert elapsed < 0.3


async def test_send_and_repeat_sends_at_least_once_then_can_be_cancelled():
    tx = FakeLircTransmitter()
    manager = _ir_manager(tx=tx)

    await manager.send_and_repeat([100, 200])
    for _ in range(20):
        if tx.calls:
            break
        await asyncio.sleep(0.01)

    assert tx.calls

    manager.stop_repeating()

    assert manager.sending_task is None


def test_cancel_sending_is_a_noop_when_nothing_running():
    manager = _ir_manager()
    manager.cancel_sending()
    assert manager.sending_task is None


async def test_execute_press_without_release_calls_send_and_repeat():
    manager = _ir_manager()
    calls = []

    async def fake_send_and_repeat(code):
        calls.append(("repeat", code))

    manager.send_and_repeat = fake_send_and_repeat
    command = _command(ir_action=[100, 200])

    await manager.execute(Directive(command_id=1, press_without_release=True), command)

    assert calls == [("repeat", [100, 200])]


async def test_execute_without_press_without_release_calls_send_command():
    manager = _ir_manager()
    calls = []

    async def fake_send_command(code):
        calls.append(("send", code))

    manager.send_command = fake_send_command
    command = _command(ir_action=[100, 200])

    await manager.execute(Directive(command_id=1, press_without_release=False), command)

    assert calls == [("send", [100, 200])]


async def test_execute_without_ir_action_does_not_send_anything():
    manager = _ir_manager()
    calls = []
    manager.send_command = lambda code: calls.append(code)
    manager.send_and_repeat = lambda code: calls.append(code)

    await manager.execute(Directive(command_id=1), _command(ir_action=[]))

    assert calls == []


_CODE_A = [9000, 4500, 560, 560, 560, 1690, 560, 560, 560, 1690, 560]
_CODE_B = [1000, 2000, 300, 300, 300, 400, 300, 300, 300, 400, 300]  # nothing like _CODE_A
_SHORT_CODE = [100, 200, 100]  # shorter than _MIN_CODE_LENGTH (8)


async def test_record_command_returns_the_code_when_two_presses_match():
    manager = _ir_manager(rx=FakeLircReceiver(codes=[_CODE_A, _CODE_A]))

    result = await manager.record_command("Power")

    assert result == _CODE_A


async def test_record_command_retries_on_a_short_code():
    rx = FakeLircReceiver(codes=[_SHORT_CODE, _CODE_A, _CODE_A])
    manager = _ir_manager(rx=rx)

    result = await manager.record_command("Power")

    assert result == _CODE_A
    assert rx._codes == []  # all three fed codes were consumed, none left over


async def test_record_command_retries_when_presses_dont_match_then_succeeds():
    rx = FakeLircReceiver(codes=[_CODE_A, _CODE_B, _CODE_A])
    manager = _ir_manager(rx=rx)

    result = await manager.record_command("Power")

    assert result is not None
    assert rx._codes == []


async def test_record_command_gives_up_after_too_many_mismatched_tries():
    # 1 initial press + 5 mismatched repeat attempts before giving up.
    rx = FakeLircReceiver(codes=[_CODE_A, _CODE_B, _CODE_B, _CODE_B, _CODE_B, _CODE_B])
    manager = _ir_manager(rx=rx)

    result = await manager.record_command("Power")

    assert result is None
    assert rx._codes == []


def test_router_has_the_expected_routes():
    manager = _ir_manager()

    paths = {route.path for route in manager.router.routes}

    assert paths == {"/ws/commands"}


def _client_for(manager: IrManager) -> TestClient:
    assert manager.router is not None
    app = FastAPI()
    app.include_router(manager.router)
    return TestClient(app)


def test_ws_commands_records_and_persists_a_command(db_engine, monkeypatch):
    monkeypatch.setattr("ir_manager.ir_manager.engine", db_engine)
    manager = _ir_manager()

    async def fake_record_command(name, websocket):
        return [100, 200]

    manager.record_command = fake_record_command

    payload = {"name": "Play", "button": "play", "type": "ir", "command_group": "transport"}

    with _client_for(manager) as client, client.websocket_connect("/ws/commands") as websocket:
        websocket.send_json(payload)
        response = websocket.receive_json()

    assert response == WebsocketIrResponse.DONE.value

    with Session(db_engine) as session:
        saved = session.exec(select(Command).where(Command.name == "Play")).one()
        assert saved.ir_action == [100, 200]


def test_ws_commands_links_the_device_when_device_id_is_given(db_engine, monkeypatch):
    monkeypatch.setattr("ir_manager.ir_manager.engine", db_engine)
    manager = _ir_manager()

    async def fake_record_command(name, websocket):
        return [1, 2]

    manager.record_command = fake_record_command

    with Session(db_engine) as session:
        device = Device(name="TV", type=DeviceType.DISPLAY)
        session.add(device)
        session.commit()
        session.refresh(device)
        device_id = device.id

    payload = {
        "name": "Power", "button": "power_on", "type": "ir",
        "command_group": "power", "device_id": device_id,
    }

    with _client_for(manager) as client, client.websocket_connect("/ws/commands") as websocket:
        websocket.send_json(payload)
        websocket.receive_json()

    with Session(db_engine) as session:
        saved = session.exec(select(Command).where(Command.name == "Power")).one()
        assert saved.device_id == device_id


def test_ws_commands_cancelled_recording_sends_cancelled_and_closes_cleanly(db_engine, monkeypatch):
    monkeypatch.setattr("ir_manager.ir_manager.engine", db_engine)
    manager = _ir_manager()

    async def fake_record_command(name, websocket):
        raise asyncio.CancelledError()

    manager.record_command = fake_record_command

    payload = {"name": "Play", "button": "play", "type": "ir", "command_group": "transport"}

    with _client_for(manager) as client, client.websocket_connect("/ws/commands") as websocket:
        websocket.send_json(payload)
        response = websocket.receive_json()

    assert response == WebsocketIrResponse.CANCELLED.value

    with Session(db_engine) as session:
        assert session.exec(select(Command).where(Command.name == "Play")).first() is None
