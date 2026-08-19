import pytest
from sqlmodel import Session

from Api.models.Command import Command
from Api.models.CommandGroupType import CommandGroupType
from Api.models.CommandType import CommandType
from Api.models.Macro import Macro
from Api.models.RemoteButton import RemoteButton
from Api.models.Scene import Scene
from Api.models.SceneStatus import SceneStatus
from Hub.SceneManager import NoActiveSceneError, SceneManager, SceneNotFoundError
from Hub.StatusStore import StatusStore


class FakeKeymapResolver:
    def __init__(self):
        self.loaded = []

    def load_key_map(self, keymap_name: str = "default") -> None:
        self.loaded.append(keymap_name)


class FakeCommandDispatcher:
    def __init__(self):
        self.executed_macros = []
        self.state_update_calls = []
        self.dispatched = []

    async def execute_macro(self, macro, from_start=False, from_stop=False):
        self.executed_macros.append((macro, from_start, from_stop))

    async def update_states_for_commands(self, commands):
        self.state_update_calls.append(commands)

    async def dispatch(self, directive, from_start=False, from_stop=False):
        self.dispatched.append((directive, from_start, from_stop))


class FakeBleKeyboard:
    def __init__(self):
        self.calls = []

    async def connect(self, address):
        self.calls.append(("connect", address))

    async def disconnect(self, address=None):
        self.calls.append(("disconnect", address))

    async def register_services(self):
        self.calls.append(("register_services",))

    async def unregister_services(self):
        self.calls.append(("unregister_services",))


@pytest.fixture
def deps(db_engine, monkeypatch):
    monkeypatch.setattr("Hub.SceneManager.engine", db_engine)
    return StatusStore(), FakeKeymapResolver(), FakeCommandDispatcher(), FakeBleKeyboard()


def _create_command(db_engine, **overrides) -> int:
    defaults = dict(
        name="cmd",
        button=RemoteButton.POWER_OFF,
        type=CommandType.IR,
        command_group=CommandGroupType.POWER,
        ir_action="ff",
    )
    defaults.update(overrides)
    with Session(db_engine) as session:
        command = Command(**defaults)
        session.add(command)
        session.commit()
        session.refresh(command)
        return command.id


def _create_scene(
    db_engine,
    name: str = "Movie Night",
    keymap: str | None = None,
    bluetooth_address: str | None = None,
    start_macro_commands: list[Command] | None = None,
    stop_macro_command_ids: list[int] | None = None,
) -> int:
    with Session(db_engine) as session:
        start_macro_id = None
        if start_macro_commands is not None:
            start_macro = Macro(command_ids=[], delays=[])
            start_macro.commands = start_macro_commands
            session.add(start_macro)
            session.commit()
            session.refresh(start_macro)
            start_macro_id = start_macro.id

        stop_macro_id = None
        if stop_macro_command_ids is not None:
            stop_macro = Macro(command_ids=stop_macro_command_ids, delays=[0] * len(stop_macro_command_ids))
            session.add(stop_macro)
            session.commit()
            session.refresh(stop_macro)
            stop_macro_id = stop_macro.id

        scene = Scene(
            name=name,
            keymap=keymap,
            bluetooth_address=bluetooth_address,
            start_macro_id=start_macro_id,
            stop_macro_id=stop_macro_id,
        )
        session.add(scene)
        session.commit()
        session.refresh(scene)
        return scene.id


async def test_start_scene_raises_when_scene_missing(deps):
    status_store, keymap_resolver, command_dispatcher, ble_keyboard = deps
    manager = SceneManager(status_store, keymap_resolver, command_dispatcher, ble_keyboard)

    with pytest.raises(SceneNotFoundError):
        await manager.start_scene(999)


async def test_start_scene_activates_runs_macro_loads_keymap_and_connects_ble(db_engine, deps):
    status_store, keymap_resolver, command_dispatcher, ble_keyboard = deps
    scene_id = _create_scene(db_engine, keymap="movie", bluetooth_address="AA:BB:CC:DD:EE:FF", start_macro_commands=[])
    manager = SceneManager(status_store, keymap_resolver, command_dispatcher, ble_keyboard)

    await manager.start_scene(scene_id)

    assert status_store.status.current_scene.name == "Movie Night"
    assert status_store.status.scene_status == SceneStatus.ACTIVE
    assert len(command_dispatcher.executed_macros) == 1
    _, from_start, from_stop = command_dispatcher.executed_macros[0]
    assert (from_start, from_stop) == (True, False)
    assert keymap_resolver.loaded == ["movie"]
    assert ("connect", "AA:BB:CC:DD:EE:FF") in ble_keyboard.calls
    assert ("register_services",) in ble_keyboard.calls


async def test_start_scene_without_ble_keyboard_does_not_raise(db_engine, monkeypatch):
    monkeypatch.setattr("Hub.SceneManager.engine", db_engine)
    scene_id = _create_scene(db_engine, bluetooth_address="AA:BB:CC:DD:EE:FF")
    status_store = StatusStore()
    manager = SceneManager(status_store, FakeKeymapResolver(), FakeCommandDispatcher(), ble_keyboard=None)

    await manager.start_scene(scene_id)

    assert status_store.status.scene_status == SceneStatus.ACTIVE


async def test_start_scene_skips_power_down_for_devices_already_being_started(db_engine, deps):
    status_store, keymap_resolver, command_dispatcher, ble_keyboard = deps

    # New scene powers device 1 on - stopping the previous scene should
    # skip powering device 1 back off, but still power device 2 off.
    tv_power_on = Command(
        name="TV On", button=RemoteButton.POWER_ON, type=CommandType.IR,
        command_group=CommandGroupType.POWER, ir_action="ff", device_id=1,
    )
    new_scene_id = _create_scene(db_engine, name="Second Scene", start_macro_commands=[tv_power_on])

    tv_off_id = _create_command(db_engine, name="TV Off", button=RemoteButton.POWER_OFF, device_id=1)
    amp_off_id = _create_command(db_engine, name="Amp Off", button=RemoteButton.POWER_OFF, device_id=2)
    previous_scene_id = _create_scene(db_engine, name="First Scene", stop_macro_command_ids=[tv_off_id, amp_off_id])

    with Session(db_engine) as session:
        previous = session.get(Scene, previous_scene_id)
        await status_store.set_scene(previous, SceneStatus.ACTIVE)

    manager = SceneManager(status_store, keymap_resolver, command_dispatcher, ble_keyboard)
    await manager.start_scene(new_scene_id)

    stopped_ids = [directive.command_id for directive, _, from_stop in command_dispatcher.dispatched if from_stop]
    assert stopped_ids == [amp_off_id]
    assert status_store.status.current_scene.name == "Second Scene"


async def test_set_current_scene_does_not_run_start_macro(db_engine, deps):
    status_store, keymap_resolver, command_dispatcher, ble_keyboard = deps
    tv_on = Command(
        name="TV On", button=RemoteButton.POWER_ON, type=CommandType.IR,
        command_group=CommandGroupType.POWER, ir_action="ff", device_id=1,
    )
    scene_id = _create_scene(db_engine, keymap="movie", start_macro_commands=[tv_on])
    manager = SceneManager(status_store, keymap_resolver, command_dispatcher, ble_keyboard)

    await manager.set_current_scene(scene_id)

    assert command_dispatcher.executed_macros == []
    assert len(command_dispatcher.state_update_calls) == 1
    assert status_store.status.current_scene.name == "Movie Night"
    assert status_store.status.scene_status == SceneStatus.ACTIVE
    assert keymap_resolver.loaded == ["movie"]


async def test_stop_current_scene_raises_when_none_active(deps):
    status_store, keymap_resolver, command_dispatcher, ble_keyboard = deps
    manager = SceneManager(status_store, keymap_resolver, command_dispatcher, ble_keyboard)

    with pytest.raises(NoActiveSceneError):
        await manager.stop_current_scene()


async def test_stop_current_scene_only_dispatches_unskipped_power_commands(db_engine, deps):
    status_store, keymap_resolver, command_dispatcher, ble_keyboard = deps

    power_off_id = _create_command(db_engine, name="TV Off", button=RemoteButton.POWER_OFF, device_id=1)
    skipped_toggle_id = _create_command(db_engine, name="Amp Toggle", button=RemoteButton.POWER_TOGGLE, device_id=2)
    non_power_id = _create_command(
        db_engine, name="Volume", button=RemoteButton.VOLUME_UP,
        command_group=CommandGroupType.VOLUME, device_id=3,
    )
    scene_id = _create_scene(
        db_engine,
        bluetooth_address="AA:BB:CC:DD:EE:FF",
        stop_macro_command_ids=[power_off_id, skipped_toggle_id, non_power_id],
    )

    with Session(db_engine) as session:
        scene = session.get(Scene, scene_id)
        await status_store.set_scene(scene, SceneStatus.ACTIVE)

    manager = SceneManager(status_store, keymap_resolver, command_dispatcher, ble_keyboard)
    await manager.stop_current_scene(skip_power_down_for={2})

    dispatched_ids = [directive.command_id for directive, _, _ in command_dispatcher.dispatched]
    assert dispatched_ids == [power_off_id]
    assert ("disconnect", "AA:BB:CC:DD:EE:FF") in ble_keyboard.calls
    assert status_store.status.current_scene is None
    assert status_store.status.scene_status is None
    assert keymap_resolver.loaded == ["default"]
