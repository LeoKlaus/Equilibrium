import asyncio
import json

import pytest

from Hub.EventBus import Event, EventBus
from rf_manager.rf_manager import RfInput, _Signal


def _payload_for(command: int) -> bytes:
    return bytes([0, (command >> 16) & 0xFF, (command >> 8) & 0xFF, command & 0xFF, 0])


class FakeRadio:
    def __init__(self, payloads: list[bytes]):
        self._payloads = list(payloads)
        self.powered_down = False

    def available(self) -> bool:
        return bool(self._payloads)

    def getDynamicPayloadSize(self) -> int:
        return len(self._payloads[0])

    def read(self, _size: int) -> bytes:
        return self._payloads.pop(0)

    def powerDown(self) -> None:
        self.powered_down = True


@pytest.fixture
def keymap_dir(tmp_path):
    (tmp_path / "remote_keymap.json").write_text(json.dumps({"Play": {"rf_command": "ABCDEF"}}))
    return str(tmp_path)


def test_load_known_commands_missing_file_returns_empty_dict(tmp_path):
    rf_input = RfInput(addresses=[b"a", b"b"], config_dir=str(tmp_path))
    assert rf_input._known_commands == {}


def test_load_known_commands_parses_hex_rf_command(keymap_dir):
    rf_input = RfInput(addresses=[b"a", b"b"], config_dir=keymap_dir)
    assert rf_input._known_commands == {0xABCDEF: "Play"}


def test_decode_recognized_command_returns_pressed_and_tracks_last_key(keymap_dir):
    rf_input = RfInput(addresses=[b"a", b"b"], config_dir=keymap_dir)

    signal = rf_input._decode(_payload_for(0xABCDEF))

    assert signal == _Signal("pressed", "Play")
    assert rf_input._last_key == "Play"


def test_decode_repeat_without_prior_press_returns_none(keymap_dir):
    rf_input = RfInput(addresses=[b"a", b"b"], config_dir=keymap_dir)
    assert rf_input._decode(_payload_for(0x400028)) is None


def test_decode_repeat_after_press_returns_repeated_for_last_key(keymap_dir):
    rf_input = RfInput(addresses=[b"a", b"b"], config_dir=keymap_dir)
    rf_input._decode(_payload_for(0xABCDEF))

    signal = rf_input._decode(_payload_for(0x400028))

    assert signal == _Signal("repeated", "Play")


def test_decode_all_released_returns_released_for_last_key(keymap_dir):
    rf_input = RfInput(addresses=[b"a", b"b"], config_dir=keymap_dir)
    rf_input._decode(_payload_for(0xABCDEF))

    signal = rf_input._decode(_payload_for(0x4F0004))

    assert signal == _Signal("released", "Play")


@pytest.mark.parametrize("command", [0x40044C, 0x4F0300, 0x4F0700, 0xC10000, 0xC30000])
def test_decode_ignored_signals_return_none(keymap_dir, command):
    rf_input = RfInput(addresses=[b"a", b"b"], config_dir=keymap_dir)
    assert rf_input._decode(_payload_for(command)) is None


def test_decode_short_payload_returns_none(keymap_dir):
    rf_input = RfInput(addresses=[b"a", b"b"], config_dir=keymap_dir)
    assert rf_input._decode(bytes([0, 1, 2])) is None


def test_decode_unrecognized_command_returns_none(keymap_dir):
    rf_input = RfInput(addresses=[b"a", b"b"], config_dir=keymap_dir)
    assert rf_input._decode(_payload_for(0x999999)) is None


def test_init_radio_skips_startup_with_fewer_than_two_addresses(keymap_dir):
    rf_input = RfInput(addresses=[b"only-one"], config_dir=keymap_dir)
    assert rf_input._init_radio() is None


async def test_start_returns_immediately_when_radio_unavailable(keymap_dir):
    rf_input = RfInput(addresses=[b"only-one"], config_dir=keymap_dir)
    bus = EventBus()

    await asyncio.wait_for(rf_input.start(bus), timeout=1)


def test_stop_powers_down_radio_and_stops_the_loop(keymap_dir):
    rf_input = RfInput(addresses=[b"a", b"b"], config_dir=keymap_dir)
    radio = FakeRadio([])
    rf_input._rf = radio

    rf_input.stop()

    assert rf_input._running is False
    assert radio.powered_down is True


def test_blocking_receive_returns_none_once_stopped(keymap_dir):
    rf_input = RfInput(addresses=[b"a", b"b"], config_dir=keymap_dir)
    rf_input._running = False

    assert rf_input._blocking_receive() is None


async def test_start_publishes_pressed_repeated_and_released_events(keymap_dir):
    rf_input = RfInput(addresses=[b"a", b"b"], config_dir=keymap_dir)
    rf_input._init_radio = lambda: FakeRadio([
        _payload_for(0xABCDEF),
        _payload_for(0x400028),
        _payload_for(0x4F0004),
    ])

    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("key_pressed", handler)
    bus.subscribe("key_repeated", handler)
    bus.subscribe("key_released", handler)

    task = asyncio.create_task(rf_input.start(bus))
    run_task = asyncio.create_task(bus.run())

    async def wait_for_all():
        while len(received) < 3:
            await asyncio.sleep(0.01)

    try:
        await asyncio.wait_for(wait_for_all(), timeout=2)
    finally:
        rf_input.stop()
        run_task.cancel()
        await asyncio.wait_for(task, timeout=1)

    assert [(e.type, e.payload["button"]) for e in received] == [
        ("key_pressed", "Play"),
        ("key_repeated", "Play"),
        ("key_released", "Play"),
    ]
