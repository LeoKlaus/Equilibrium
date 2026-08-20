import pytest
from sqlmodel import Session

from Api.models.Command import Command
from Api.models.CommandGroupType import CommandGroupType
from Api.models.CommandType import CommandType
from Api.models.Macro import Macro
from Api.models.RemoteButton import RemoteButton
from Hub.CommandDispatcher import CommandDispatcher
from Hub.EventBus import Directive
from Hub.interfaces import ActionExecutor
from Hub.KeymapResolver import KeymapResolver
from Hub.StatusStore import StatusStore


class FakeExecutor(ActionExecutor):
    name = "fake"

    def __init__(self):
        self.calls = []

    async def execute(self, directive, command):
        self.calls.append((directive, command))


@pytest.fixture
def keymap_resolver(db_engine, monkeypatch):
    monkeypatch.setattr("Hub.KeymapResolver.engine", db_engine)
    return KeymapResolver()


def _add_command(db_engine, **overrides) -> int:
    defaults = {
        "name": "Play",
        "button": RemoteButton.PLAY,
        "type": CommandType.IR,
        "command_group": CommandGroupType.TRANSPORT,
        "ir_action": "deadbeef",
    }
    defaults.update(overrides)
    with Session(db_engine) as session:
        command = Command(**defaults)
        session.add(command)
        session.commit()
        session.refresh(command)
        return command.id


async def test_dispatch_calls_the_registered_executor(db_engine, keymap_resolver):
    command_id = _add_command(db_engine)
    ir_executor = FakeExecutor()
    dispatcher = CommandDispatcher(StatusStore(), keymap_resolver, {"ir": ir_executor})

    directive = Directive(command_id=command_id, press_without_release=True)
    await dispatcher.dispatch(directive)

    assert len(ir_executor.calls) == 1
    called_directive, called_command = ir_executor.calls[0]
    assert called_directive is directive
    assert called_command.id == command_id


async def test_dispatch_unknown_command_id_does_not_call_any_executor(db_engine, keymap_resolver):
    executor = FakeExecutor()
    dispatcher = CommandDispatcher(StatusStore(), keymap_resolver, {"ir": executor})

    await dispatcher.dispatch(Directive(command_id=999))

    assert executor.calls == []


async def test_dispatch_missing_executor_does_not_update_status(db_engine, keymap_resolver):
    command_id = _add_command(db_engine, button=RemoteButton.POWER_ON, device_id=1)
    status_store = StatusStore()
    dispatcher = CommandDispatcher(status_store, keymap_resolver, {})

    await dispatcher.dispatch(Directive(command_id=command_id), from_start=True)

    assert status_store.status.devices.state(for_device_id=1).powered is False


async def test_plain_dispatch_does_not_update_status(db_engine, keymap_resolver):
    command_id = _add_command(db_engine, button=RemoteButton.POWER_ON, device_id=1)
    status_store = StatusStore()
    dispatcher = CommandDispatcher(status_store, keymap_resolver, {"ir": FakeExecutor()})

    await dispatcher.dispatch(Directive(command_id=command_id))

    assert status_store.status.devices.state(for_device_id=1).powered is False


async def test_from_start_skips_power_on_when_already_powered(db_engine, keymap_resolver):
    command_id = _add_command(db_engine, button=RemoteButton.POWER_ON, device_id=1)
    status_store = StatusStore()
    await status_store.set_device_state(1, new_power_state=True)
    executor = FakeExecutor()
    dispatcher = CommandDispatcher(status_store, keymap_resolver, {"ir": executor})

    await dispatcher.dispatch(Directive(command_id=command_id), from_start=True)

    assert executor.calls == []


async def test_from_start_skips_input_already_selected(db_engine, keymap_resolver):
    command_id = _add_command(db_engine, command_group=CommandGroupType.INPUT, device_id=1)
    status_store = StatusStore()
    await status_store.set_device_state(1, new_power_state=True, new_input=command_id)
    executor = FakeExecutor()
    dispatcher = CommandDispatcher(status_store, keymap_resolver, {"ir": executor})

    await dispatcher.dispatch(Directive(command_id=command_id), from_start=True)

    assert executor.calls == []


async def test_from_start_still_sends_when_device_not_yet_powered(db_engine, keymap_resolver):
    command_id = _add_command(db_engine, button=RemoteButton.POWER_ON, device_id=1)
    status_store = StatusStore()
    executor = FakeExecutor()
    dispatcher = CommandDispatcher(status_store, keymap_resolver, {"ir": executor})

    await dispatcher.dispatch(Directive(command_id=command_id), from_start=True)

    assert len(executor.calls) == 1
    assert status_store.status.devices.state(for_device_id=1).powered is True


async def test_from_stop_skips_power_off_when_already_off(db_engine, keymap_resolver):
    command_id = _add_command(db_engine, button=RemoteButton.POWER_OFF, device_id=1)
    status_store = StatusStore()
    executor = FakeExecutor()
    dispatcher = CommandDispatcher(status_store, keymap_resolver, {"ir": executor})

    await dispatcher.dispatch(Directive(command_id=command_id), from_stop=True)

    assert executor.calls == []


async def test_update_state_for_command_input_group_sets_power_and_input(db_engine, keymap_resolver):
    command_id = _add_command(db_engine, command_group=CommandGroupType.INPUT, device_id=1)
    status_store = StatusStore()
    dispatcher = CommandDispatcher(status_store, keymap_resolver, {})

    command = keymap_resolver.get_command(command_id)
    await dispatcher.update_state_for_command(command)

    state = status_store.status.devices.state(for_device_id=1)
    assert state.powered is True
    assert state.input == command_id


async def test_execute_macro_dispatches_each_command_in_order(db_engine, keymap_resolver):
    first_id = _add_command(db_engine, name="First")
    second_id = _add_command(db_engine, name="Second")
    executor = FakeExecutor()
    dispatcher = CommandDispatcher(StatusStore(), keymap_resolver, {"ir": executor})

    macro = Macro(command_ids=[first_id, second_id], delays=[0])
    await dispatcher.execute_macro(macro)

    assert [command.name for _, command in executor.calls] == ["First", "Second"]
