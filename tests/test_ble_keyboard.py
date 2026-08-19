from Api.models.Command import Command
from Api.models.CommandGroupType import CommandGroupType
from Api.models.CommandType import CommandType
from Api.models.RemoteButton import RemoteButton
from BleKeyboard.BleKeyboard import BleKeyboard
from Hub.EventBus import Directive


class FakeHidService:
    def __init__(self):
        self.pressed_keys_calls = []
        self.pressed_media_keys_calls = []

    def update_pressed_keys(self, key):
        self.pressed_keys_calls.append(key)

    def update_pressed_media_keys(self, key):
        self.pressed_media_keys_calls.append(key)


def _keyboard() -> BleKeyboard:
    keyboard = BleKeyboard()
    keyboard.hid_service = FakeHidService()
    return keyboard


def _command(**overrides) -> Command:
    defaults = dict(
        name="cmd",
        button=RemoteButton.PLAY,
        type=CommandType.BLUETOOTH,
        command_group=CommandGroupType.TRANSPORT,
    )
    defaults.update(overrides)
    return Command(**defaults)


def test_press_key_tracks_pressed_key_and_updates_hid_service():
    keyboard = _keyboard()

    keyboard.press_key("KEY_ESC")

    assert keyboard.pressed_keys != []
    assert len(keyboard.hid_service.pressed_keys_calls) == 1


def test_release_keys_clears_state_and_sends_zeroed_report():
    keyboard = _keyboard()
    keyboard.press_key("KEY_ESC")

    keyboard.release_keys()

    assert keyboard.pressed_keys == []
    assert keyboard.hid_service.pressed_keys_calls[-1] == [0, 0, 0, 0, 0, 0, 0, 0]


def test_release_keys_is_a_noop_when_nothing_pressed():
    keyboard = _keyboard()

    keyboard.release_keys()

    assert keyboard.hid_service.pressed_keys_calls == []


async def test_send_key_presses_then_releases():
    keyboard = _keyboard()

    await keyboard.send_key("KEY_ESC", delay=0)

    assert keyboard.pressed_keys == []
    assert len(keyboard.hid_service.pressed_keys_calls) == 2
    assert keyboard.hid_service.pressed_keys_calls[-1] == [0, 0, 0, 0, 0, 0, 0, 0]


def test_press_media_key_tracks_and_updates_hid_service():
    keyboard = _keyboard()

    keyboard.press_media_key("KEY_PLAY")

    assert keyboard.pressed_media_keys != []
    assert len(keyboard.hid_service.pressed_media_keys_calls) == 1


def test_release_media_keys_clears_state():
    keyboard = _keyboard()
    keyboard.press_media_key("KEY_PLAY")

    keyboard.release_media_keys()

    assert keyboard.pressed_media_keys == []
    assert keyboard.hid_service.pressed_media_keys_calls[-1] == [0, 0]


async def test_send_media_key_presses_then_releases():
    keyboard = _keyboard()

    await keyboard.send_media_key("KEY_PLAY", delay=0)

    assert keyboard.pressed_media_keys == []
    assert len(keyboard.hid_service.pressed_media_keys_calls) == 2


async def test_execute_press_without_release_holds_the_key():
    keyboard = _keyboard()
    command = _command(bt_action="KEY_ESC")

    await keyboard.execute(Directive(command_id=1, press_without_release=True), command)

    assert keyboard.pressed_keys != []
    assert len(keyboard.hid_service.pressed_keys_calls) == 1


async def test_execute_without_press_without_release_taps_the_key():
    keyboard = _keyboard()
    command = _command(bt_action="KEY_ESC")

    await keyboard.execute(Directive(command_id=1, press_without_release=False), command)

    assert keyboard.pressed_keys == []
    assert len(keyboard.hid_service.pressed_keys_calls) == 2


async def test_execute_media_action_press_without_release_holds_the_key():
    keyboard = _keyboard()
    command = _command(bt_media_action="KEY_PLAY")

    await keyboard.execute(Directive(command_id=1, press_without_release=True), command)

    assert keyboard.pressed_media_keys != []
    assert len(keyboard.hid_service.pressed_media_keys_calls) == 1


async def test_execute_without_bluetooth_action_logs_and_does_nothing():
    keyboard = _keyboard()
    command = _command()

    await keyboard.execute(Directive(command_id=1), command)

    assert keyboard.hid_service.pressed_keys_calls == []
    assert keyboard.hid_service.pressed_media_keys_calls == []
