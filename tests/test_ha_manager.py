import asyncio
import time

from Api.models.Command import Command
from Api.models.CommandGroupType import CommandGroupType
from Api.models.CommandType import CommandType
from Api.models.IntegrationAction import IntegrationAction
from Api.models.RemoteButton import RemoteButton
from ha_manager.ha_manager import HaManager
from hub.event_bus import Directive


class FakeDomain:
    def __init__(self):
        self.toggle_calls = []
        self.turn_on_calls = []

    def toggle(self, entity_id):
        self.toggle_calls.append(entity_id)

    def turn_on(self, entity_id, **kwargs):
        self.turn_on_calls.append((entity_id, kwargs))


class FakeClient:
    def __init__(self):
        self.domain = FakeDomain()
        self.get_domain_calls = 0

    def get_domain(self, name):
        self.get_domain_calls += 1
        return self.domain


def _ha_manager() -> HaManager:
    manager = HaManager("http://fake/api", "faketoken")
    manager.client = FakeClient()
    return manager


def _command(**overrides) -> Command:
    defaults = {
        "name": "cmd",
        "button": RemoteButton.SELECT,
        "type": CommandType.INTEGRATION,
        "command_group": CommandGroupType.OTHER,
    }
    defaults.update(overrides)
    return Command(**defaults)


def test_toggle_light_toggles_and_remembers_the_entity():
    manager = _ha_manager()

    manager.toggle_light("light.living_room")

    assert manager.client.domain.toggle_calls == ["light.living_room"]
    assert manager.last_light_id == "light.living_room"


def test_toggle_light_reuses_the_domain_lookup():
    manager = _ha_manager()

    manager.toggle_light("light.a")
    manager.toggle_light("light.b")

    assert manager.client.get_domain_calls == 1


def test_increase_brightness_without_prior_toggle_is_a_noop():
    manager = _ha_manager()

    manager.increase_brightness()

    assert manager.client.domain.turn_on_calls == []


def test_increase_brightness_steps_up_the_last_toggled_light():
    manager = _ha_manager()
    manager.toggle_light("light.living_room")

    manager.increase_brightness()

    assert manager.client.domain.turn_on_calls == [("light.living_room", {"brightness_step_pct": 10})]


def test_decrease_brightness_steps_down_the_last_toggled_light():
    manager = _ha_manager()
    manager.toggle_light("light.living_room")

    manager.decrease_brightness()

    assert manager.client.domain.turn_on_calls == [("light.living_room", {"brightness_step_pct": -10})]


async def test_execute_toggle_light_dispatches_to_toggle_light():
    manager = _ha_manager()
    command = _command(integration_action=IntegrationAction.TOGGLE_LIGHT, integration_entity="light.living_room")

    await manager.execute(Directive(command_id=1), command)

    assert manager.client.domain.toggle_calls == ["light.living_room"]


async def test_execute_brightness_up_dispatches_to_increase_brightness():
    manager = _ha_manager()
    manager.toggle_light("light.living_room")
    command = _command(integration_action=IntegrationAction.BRIGHTNESS_UP)

    await manager.execute(Directive(command_id=1), command)

    assert manager.client.domain.turn_on_calls == [("light.living_room", {"brightness_step_pct": 10})]


async def test_execute_without_integration_action_does_nothing():
    manager = _ha_manager()
    command = _command(integration_action=None)

    await manager.execute(Directive(command_id=1), command)

    assert manager.client.domain.toggle_calls == []
    assert manager.client.domain.turn_on_calls == []


async def test_execute_offloads_the_blocking_client_call():
    # Proves the run_in_executor wrapping actually keeps the loop free,
    # the same way test_ir_manager's equivalent test does.
    manager = _ha_manager()

    def slow_toggle(entity_id):
        time.sleep(0.2)

    manager.client.domain.toggle = slow_toggle
    command = _command(integration_action=IntegrationAction.TOGGLE_LIGHT, integration_entity="light.living_room")

    async def ticker() -> int:
        ticks = 0
        for _ in range(8):
            await asyncio.sleep(0.02)
            ticks += 1
        return ticks

    loop = asyncio.get_running_loop()
    start = loop.time()
    _, ticks = await asyncio.gather(manager.execute(Directive(command_id=1), command), ticker())
    elapsed = loop.time() - start

    assert ticks == 8
    assert elapsed < 0.3
