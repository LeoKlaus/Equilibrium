import asyncio

from Hub.EventBus import Directive, Event, EventBus
from Hub.InputRouter import InputRouter
from Hub.KeymapResolver import SendDirective, StartScene, StopScene


class FakeKeymapResolver:
    def __init__(self, mapping=None):
        self._mapping = mapping or {}

    def resolve(self, button):
        return self._mapping.get(button)


class FakeSceneManager:
    def __init__(self):
        self.started = []
        self.stopped = 0

    async def start_scene(self, scene_id):
        self.started.append(scene_id)

    async def stop_current_scene(self):
        self.stopped += 1


class FakeCommandDispatcher:
    def __init__(self):
        self.dispatched = []

    async def dispatch(self, directive, from_start=False, from_stop=False):
        self.dispatched.append(directive)


class FakeBleKeyboard:
    def __init__(self):
        self.calls = []

    def release_keys(self):
        self.calls.append("release_keys")

    def release_media_keys(self):
        self.calls.append("release_media_keys")


class FakeIrManager:
    def __init__(self):
        self.stopped = 0

    def stop_repeating(self):
        self.stopped += 1


async def test_key_pressed_stop_scene():
    scene_manager = FakeSceneManager()
    router = InputRouter(FakeKeymapResolver({"Off": StopScene()}), scene_manager, FakeCommandDispatcher())

    await router._on_key_pressed(Event("key_pressed", {"button": "Off"}))

    assert scene_manager.stopped == 1
    assert scene_manager.started == []


async def test_key_pressed_start_scene():
    scene_manager = FakeSceneManager()
    router = InputRouter(FakeKeymapResolver({"Scene1": StartScene(10)}), scene_manager, FakeCommandDispatcher())

    await router._on_key_pressed(Event("key_pressed", {"button": "Scene1"}))

    assert scene_manager.started == [10]
    assert scene_manager.stopped == 0


async def test_key_pressed_send_directive():
    directive = Directive(command_id=1, press_without_release=True)
    command_dispatcher = FakeCommandDispatcher()
    router = InputRouter(
        FakeKeymapResolver({"Play": SendDirective(directive)}),
        FakeSceneManager(),
        command_dispatcher,
    )

    await router._on_key_pressed(Event("key_pressed", {"button": "Play"}))

    assert command_dispatcher.dispatched == [directive]


async def test_repeated_press_of_the_same_button_forces_a_release_first():
    directive = Directive(command_id=1, press_without_release=True)
    command_dispatcher = FakeCommandDispatcher()
    ble_keyboard = FakeBleKeyboard()
    router = InputRouter(
        FakeKeymapResolver({"Exit": SendDirective(directive)}),
        FakeSceneManager(),
        command_dispatcher,
        ble_keyboard=ble_keyboard,
    )

    await router._on_key_pressed(Event("key_pressed", {"button": "Exit"}))
    assert ble_keyboard.calls == []
    assert command_dispatcher.dispatched == [directive]

    # Same button pressed again with no key_released in between - matches
    # what the physical remote actually sends on a rapid double-tap.
    await router._on_key_pressed(Event("key_pressed", {"button": "Exit"}))

    assert ble_keyboard.calls == ["release_keys", "release_media_keys"]
    assert command_dispatcher.dispatched == [directive, directive]


async def test_press_of_a_different_button_does_not_force_a_release():
    exit_directive = Directive(command_id=1, press_without_release=True)
    up_directive = Directive(command_id=2, press_without_release=True)
    command_dispatcher = FakeCommandDispatcher()
    ble_keyboard = FakeBleKeyboard()
    router = InputRouter(
        FakeKeymapResolver({
            "Exit": SendDirective(exit_directive),
            "Up": SendDirective(up_directive),
        }),
        FakeSceneManager(),
        command_dispatcher,
        ble_keyboard=ble_keyboard,
    )

    await router._on_key_pressed(Event("key_pressed", {"button": "Exit"}))
    await router._on_key_pressed(Event("key_pressed", {"button": "Up"}))

    assert ble_keyboard.calls == []
    assert command_dispatcher.dispatched == [exit_directive, up_directive]


async def test_key_released_clears_held_button_so_next_press_does_not_force_a_release():
    directive = Directive(command_id=1, press_without_release=True)
    command_dispatcher = FakeCommandDispatcher()
    ble_keyboard = FakeBleKeyboard()
    router = InputRouter(
        FakeKeymapResolver({"Exit": SendDirective(directive)}),
        FakeSceneManager(),
        command_dispatcher,
        ble_keyboard=ble_keyboard,
    )

    await router._on_key_pressed(Event("key_pressed", {"button": "Exit"}))
    await router._on_key_released(Event("key_released", {}))
    ble_keyboard.calls.clear()

    await router._on_key_pressed(Event("key_pressed", {"button": "Exit"}))

    assert ble_keyboard.calls == []


async def test_key_pressed_unmapped_button_does_nothing():
    scene_manager = FakeSceneManager()
    command_dispatcher = FakeCommandDispatcher()
    router = InputRouter(FakeKeymapResolver({}), scene_manager, command_dispatcher)

    await router._on_key_pressed(Event("key_pressed", {"button": "Unmapped"}))

    assert scene_manager.started == []
    assert scene_manager.stopped == 0
    assert command_dispatcher.dispatched == []


async def test_key_pressed_missing_button_payload_does_nothing():
    scene_manager = FakeSceneManager()
    router = InputRouter(FakeKeymapResolver({}), scene_manager, FakeCommandDispatcher())

    await router._on_key_pressed(Event("key_pressed", {}))

    assert scene_manager.stopped == 0


async def test_key_released_releases_ble_and_stops_ir_repeat():
    ble_keyboard = FakeBleKeyboard()
    ir_manager = FakeIrManager()
    router = InputRouter(
        FakeKeymapResolver({}),
        FakeSceneManager(),
        FakeCommandDispatcher(),
        ble_keyboard=ble_keyboard,
        ir_manager=ir_manager,
    )

    await router._on_key_released(Event("key_released", {}))

    assert ir_manager.stopped == 1
    assert ble_keyboard.calls == ["release_keys", "release_media_keys"]


async def test_key_released_without_modules_does_not_raise():
    router = InputRouter(FakeKeymapResolver({}), FakeSceneManager(), FakeCommandDispatcher())

    await router._on_key_released(Event("key_released", {}))


async def test_subscribe_wires_handlers_to_the_bus():
    scene_manager = FakeSceneManager()
    router = InputRouter(FakeKeymapResolver({"Off": StopScene()}), scene_manager, FakeCommandDispatcher())
    bus = EventBus()
    router.subscribe(bus)

    bus._dispatch(Event("key_pressed", {"button": "Off"}))
    await asyncio.sleep(0)

    assert scene_manager.stopped == 1
