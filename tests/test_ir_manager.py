import asyncio

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


class FakePigpio:
    """Stands in for pigpio.pi() - avoids needing a real pigpiod daemon."""

    def __init__(self, busy_ticks: int = 0):
        self.calls: list[tuple] = []
        self._busy_ticks = busy_ticks
        self._next_wave_id = 0

    def set_mode(self, gpio, mode):
        self.calls.append(("set_mode", gpio, mode))

    def wave_add_new(self):
        self.calls.append(("wave_add_new",))

    def wave_add_generic(self, pulses):
        self.calls.append(("wave_add_generic", len(pulses)))

    def wave_create(self):
        self._next_wave_id += 1
        self.calls.append(("wave_create",))
        return self._next_wave_id

    def wave_chain(self, wave):
        self.calls.append(("wave_chain", list(wave)))

    def wave_tx_busy(self):
        if self._busy_ticks > 0:
            self._busy_ticks -= 1
            return True
        return False

    def wave_delete(self, wave_id):
        self.calls.append(("wave_delete", wave_id))


def _ir_manager(pi=None) -> IrManager:
    # Bypasses __init__ (which calls pigpio.pi() and registers an atexit
    # hook) so tests never need a real pigpiod daemon.
    manager = IrManager.__new__(IrManager)
    manager.pi = pi if pi is not None else FakePigpio()
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


async def test_send_command_builds_and_chains_a_wave_then_cleans_up():
    pi = FakePigpio(busy_ticks=2)
    manager = _ir_manager(pi)

    await manager.send_command([100, 200, 100, 200])

    call_names = [call[0] for call in pi.calls]
    assert call_names[0] == "set_mode"
    assert "wave_chain" in call_names
    assert call_names.count("wave_delete") == 2  # one mark wave, one space wave


async def test_send_command_offloads_the_blocking_work():
    # ~200ms of pigpio.wave_tx_busy() polling via time.sleep - if that ran
    # on the event loop thread instead of an executor, ticker()'s sleeps
    # would get delayed too, pushing total elapsed time toward the SUM of
    # both durations instead of their MAX.
    pi = FakePigpio(busy_ticks=4)
    manager = _ir_manager(pi)

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
    pi = FakePigpio()
    manager = _ir_manager(pi)

    await manager.send_and_repeat([100, 200])
    for _ in range(20):
        if any(call[0] == "wave_chain" for call in pi.calls):
            break
        await asyncio.sleep(0.01)

    assert any(call[0] == "wave_chain" for call in pi.calls)

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
