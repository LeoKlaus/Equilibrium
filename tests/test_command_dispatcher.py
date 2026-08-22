import asyncio

import pytest
from sqlmodel import Session

from api.models.command import Command
from api.models.command_group_type import CommandGroupType
from api.models.command_type import CommandType
from api.models.macro import Macro
from api.models.network_request_type import NetworkRequestType
from api.models.remote_button import RemoteButton
from hub.command_dispatcher import CommandDispatcher
from hub.event_bus import Directive
from hub.interfaces import ActionExecutor
from hub.keymap_resolver import KeymapResolver
from hub.status_store import StatusStore


class FakeExecutor(ActionExecutor):
    name = "fake"

    def __init__(self):
        self.calls = []

    async def execute(self, directive, command):
        self.calls.append((directive, command))


class SlowExecutor(ActionExecutor):
    """Blocks on `release` until the test lets it finish - used to prove
    execute_macro() doesn't wait for it."""

    name = "network"

    def __init__(self):
        self.calls = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, directive, command):
        self.started.set()
        await self.release.wait()
        self.calls.append((directive, command))


class FailingExecutor(ActionExecutor):
    name = "network"

    async def execute(self, directive, command):
        raise RuntimeError("device unreachable")


@pytest.fixture
def keymap_resolver(db_engine, monkeypatch):
    monkeypatch.setattr("hub.keymap_resolver.engine", db_engine)
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
        assert command.id is not None
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


async def test_execute_macro_does_not_wait_for_a_zero_delay_network_command(db_engine, keymap_resolver):
    network_id = _add_command(db_engine, name="TurnOnLight", type=CommandType.NETWORK, host="http://light", method=NetworkRequestType.GET)
    ir_id = _add_command(db_engine, name="VolumeUp")
    slow_executor = SlowExecutor()
    ir_executor = FakeExecutor()
    dispatcher = CommandDispatcher(
        StatusStore(), keymap_resolver, {"network": slow_executor, "ir": ir_executor}
    )

    macro = Macro(command_ids=[network_id, ir_id], delays=[0])
    await asyncio.wait_for(dispatcher.execute_macro(macro), timeout=1)

    # The IR command fired even though the network command never released -
    # proves execute_macro() didn't block on it.
    assert slow_executor.started.is_set()
    assert slow_executor.calls == []
    assert len(ir_executor.calls) == 1

    slow_executor.release.set()
    await asyncio.gather(*dispatcher._background_tasks)
    assert len(slow_executor.calls) == 1


async def test_execute_macro_still_waits_for_a_non_zero_delay_network_command(db_engine, keymap_resolver):
    network_id = _add_command(db_engine, name="TurnOnLight", type=CommandType.NETWORK, host="http://light", method=NetworkRequestType.GET)
    ir_id = _add_command(db_engine, name="VolumeUp")
    slow_executor = SlowExecutor()
    ir_executor = FakeExecutor()
    dispatcher = CommandDispatcher(
        StatusStore(), keymap_resolver, {"network": slow_executor, "ir": ir_executor}
    )
    slow_executor.release.set()  # would hang otherwise, since this path awaits it directly

    macro = Macro(command_ids=[network_id, ir_id], delays=[500])
    await asyncio.wait_for(dispatcher.execute_macro(macro), timeout=1)

    assert len(slow_executor.calls) == 1
    assert len(ir_executor.calls) == 1


async def test_execute_macro_runs_the_last_command_in_the_background(db_engine, keymap_resolver):
    network_id = _add_command(db_engine, name="TurnOnLight", type=CommandType.NETWORK, host="http://light", method=NetworkRequestType.GET)
    slow_executor = SlowExecutor()
    dispatcher = CommandDispatcher(StatusStore(), keymap_resolver, {"network": slow_executor})

    macro = Macro(command_ids=[network_id], delays=[])
    await asyncio.wait_for(dispatcher.execute_macro(macro), timeout=1)

    # A single-command macro has no further await after the task is
    # created, so give the event loop a turn before checking it actually
    # started - create_task() only schedules it, it doesn't run inline.
    await asyncio.wait_for(slow_executor.started.wait(), timeout=1)
    assert slow_executor.calls == []

    slow_executor.release.set()
    await asyncio.gather(*dispatcher._background_tasks)


async def test_execute_macro_ir_command_with_zero_delay_still_runs_synchronously(db_engine, keymap_resolver):
    # IR isn't a background-eligible type, so delay=0 shouldn't change how
    # it's dispatched - this is the existing test_execute_macro_dispatches_
    # each_command_in_order behavior, asserted explicitly against the
    # background-eligibility change.
    first_id = _add_command(db_engine, name="First")
    second_id = _add_command(db_engine, name="Second")
    executor = FakeExecutor()
    dispatcher = CommandDispatcher(StatusStore(), keymap_resolver, {"ir": executor})

    macro = Macro(command_ids=[first_id, second_id], delays=[0])
    await dispatcher.execute_macro(macro)

    assert len(executor.calls) == 2
    assert dispatcher._background_tasks == set()


async def test_execute_macro_applies_optimistic_state_before_the_background_call_completes(db_engine, keymap_resolver):
    network_id = _add_command(
        db_engine, name="TurnOnLight", type=CommandType.NETWORK, host="http://light", method=NetworkRequestType.GET,
        button=RemoteButton.POWER_ON, device_id=1,
    )
    slow_executor = SlowExecutor()
    status_store = StatusStore()
    dispatcher = CommandDispatcher(status_store, keymap_resolver, {"network": slow_executor})

    macro = Macro(command_ids=[network_id], delays=[])
    await asyncio.wait_for(dispatcher.execute_macro(macro, from_start=True), timeout=1)

    # State is already updated even though the network call hasn't
    # finished (or even been released) yet.
    assert status_store.status.devices.state(for_device_id=1).powered is True
    assert slow_executor.calls == []

    slow_executor.release.set()
    await asyncio.gather(*dispatcher._background_tasks)


async def test_background_command_failure_is_logged_not_raised(db_engine, keymap_resolver):
    network_id = _add_command(db_engine, name="TurnOnLight", type=CommandType.NETWORK, host="http://light", method=NetworkRequestType.GET)
    dispatcher = CommandDispatcher(StatusStore(), keymap_resolver, {"network": FailingExecutor()})

    macro = Macro(command_ids=[network_id], delays=[])
    await asyncio.wait_for(dispatcher.execute_macro(macro), timeout=1)  # should not raise

    tasks = list(dispatcher._background_tasks)
    await asyncio.gather(*tasks, return_exceptions=True)
    assert all(task.done() for task in tasks)


async def test_shutdown_cancels_pending_background_tasks(db_engine, keymap_resolver):
    network_id = _add_command(db_engine, name="TurnOnLight", type=CommandType.NETWORK, host="http://light", method=NetworkRequestType.GET)
    slow_executor = SlowExecutor()
    dispatcher = CommandDispatcher(StatusStore(), keymap_resolver, {"network": slow_executor})

    macro = Macro(command_ids=[network_id], delays=[])
    await asyncio.wait_for(dispatcher.execute_macro(macro), timeout=1)
    assert len(dispatcher._background_tasks) == 1

    await asyncio.wait_for(dispatcher.shutdown(), timeout=1)

    assert dispatcher._background_tasks == set()
