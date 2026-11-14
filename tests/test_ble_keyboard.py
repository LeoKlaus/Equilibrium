import asyncio
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.models.command import Command
from api.models.command_group_type import CommandGroupType
from api.models.command_type import CommandType
from api.models.health import ComponentStatus
from api.models.remote_button import RemoteButton
from ble_keyboard.ble_keyboard import BleKeyboard
from ble_keyboard.bluetooth_events import MAX_QUEUED_CHANGES
from hub.event_bus import Directive


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
    keyboard.hid_service = FakeHidService()  # type: ignore[assignment]  # duck-typed test double
    return keyboard


def _command(**overrides) -> Command:
    defaults: dict[str, Any] = {
        "name": "cmd",
        "button": RemoteButton.PLAY,
        "type": CommandType.BLUETOOTH,
        "command_group": CommandGroupType.TRANSPORT,
    }
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


def _client_for(keyboard: BleKeyboard) -> TestClient:
    assert keyboard.router is not None
    app = FastAPI()
    app.include_router(keyboard.router)
    return TestClient(app)


def test_router_has_the_expected_routes():
    keyboard = _keyboard()

    paths = {route.path for route in keyboard.router.routes}  # type: ignore[attr-defined]

    assert paths == {
        "/bluetooth/devices",
        "/bluetooth/start_advertisement",
        "/bluetooth/start_pairing",
        "/bluetooth/connect/{mac_address}",
        "/bluetooth/disconnect",
        "/ws/bt_pairing",
        "/ws/bluetooth",
    }


def test_router_devices_endpoint_returns_ble_devices(monkeypatch):
    keyboard = _keyboard()

    async def fake_devices(self):
        return [{"path": "/dev1", "address": "AA:BB", "alias": "TV", "paired": True, "connected": True}]

    monkeypatch.setattr(BleKeyboard, "devices", property(fake_devices))

    with _client_for(keyboard) as client:
        response = client.get("/bluetooth/devices")

    assert response.status_code == 200
    assert response.json()[0]["address"] == "AA:BB"


def test_router_start_advertisement_calls_advertise():
    keyboard = _keyboard()
    calls = []

    async def fake_advertise():
        calls.append("advertise")

    keyboard.advertise = fake_advertise

    with _client_for(keyboard) as client:
        response = client.post("/bluetooth/start_advertisement")

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert calls == ["advertise"]


def test_router_start_pairing_calls_initiate_pairing():
    keyboard = _keyboard()
    calls = []

    async def fake_initiate_pairing():
        calls.append("initiate_pairing")

    keyboard.initiate_pairing = fake_initiate_pairing

    with _client_for(keyboard) as client:
        response = client.post("/bluetooth/start_pairing")

    assert response.status_code == 200
    assert calls == ["initiate_pairing"]


def test_router_connect_passes_the_mac_address():
    keyboard = _keyboard()
    calls = []

    async def fake_connect(address):
        calls.append(address)

    keyboard.connect = fake_connect

    with _client_for(keyboard) as client:
        response = client.post("/bluetooth/connect/AA:BB:CC:DD:EE:FF")

    assert response.status_code == 200
    assert calls == ["AA:BB:CC:DD:EE:FF"]


def test_router_disconnect_calls_disconnect():
    keyboard = _keyboard()
    calls = []

    async def fake_disconnect():
        calls.append("disconnect")

    keyboard.disconnect = fake_disconnect

    with _client_for(keyboard) as client:
        response = client.post("/bluetooth/disconnect")

    assert response.status_code == 200
    assert calls == ["disconnect"]


def test_ws_bt_pairing_advertise():
    keyboard = _keyboard()
    calls = []

    async def fake_advertise():
        calls.append("advertise")

    keyboard.advertise = fake_advertise

    with _client_for(keyboard) as client, client.websocket_connect("/ws/bt_pairing") as websocket:
        websocket.send_text("advertise")
        response = websocket.receive_json()

    assert response == {"success": True}
    assert calls == ["advertise"]


def test_ws_bt_pairing_devices(monkeypatch):
    keyboard = _keyboard()

    async def fake_devices(self):
        return [{"path": "/dev1", "address": "AA:BB", "alias": "TV", "paired": True, "connected": True}]

    monkeypatch.setattr(BleKeyboard, "devices", property(fake_devices))

    with _client_for(keyboard) as client, client.websocket_connect("/ws/bt_pairing") as websocket:
        websocket.send_text("devices")
        response = websocket.receive_json()

    assert response["devices"][0]["address"] == "AA:BB"


def test_ws_bt_pairing_connect_sends_devices_then_connects_to_the_chosen_address(monkeypatch):
    keyboard = _keyboard()

    async def fake_devices(self):
        return [{"path": "/dev1", "address": "AA:BB", "alias": "TV", "paired": False, "connected": True}]

    monkeypatch.setattr(BleKeyboard, "devices", property(fake_devices))
    calls = []

    async def fake_connect(address):
        calls.append(address)

    keyboard.connect = fake_connect

    with _client_for(keyboard) as client, client.websocket_connect("/ws/bt_pairing") as websocket:
        websocket.send_text("connect")
        devices_response = websocket.receive_json()
        websocket.send_text("AA:BB")

    assert devices_response["devices"][0]["address"] == "AA:BB"
    assert calls == ["AA:BB"]


def test_ws_bt_pairing_disconnect():
    keyboard = _keyboard()
    calls = []

    async def fake_disconnect():
        calls.append("disconnect")

    keyboard.disconnect = fake_disconnect

    with _client_for(keyboard) as client, client.websocket_connect("/ws/bt_pairing") as websocket:
        websocket.send_text("disconnect")
        response = websocket.receive_json()

    assert response == {"success": True}
    assert calls == ["disconnect"]


# --- health() ----------------------------------------------------------------

ADAPTER_PATH = "/org/bluez/hci0"
DEVICE_PATH = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"


def _load_bluez(keyboard: BleKeyboard) -> None:
    keyboard.state.load(
        {
            ADAPTER_PATH: {"org.bluez.Adapter1": {"Powered": True}},
            DEVICE_PATH: {"org.bluez.Device1": {"Alias": "Apple TV", "Connected": False, "Paired": True}},
        }
    )


def test_bluetooth_device_describes_a_known_device_by_any_spelling_of_its_address():
    keyboard = _keyboard()
    _load_bluez(keyboard)

    device = keyboard.bluetooth_device("aa-bb-cc-dd-ee-ff")

    assert device.model_dump() == {"name": "Apple TV", "address": "AA:BB:CC:DD:EE:FF", "connected": False, "paired": True}


def test_bluetooth_device_reports_an_unknown_device_as_disconnected():
    device = _keyboard().bluetooth_device("11:22:33:44:55:66")

    assert device.model_dump() == {"name": "", "address": "11:22:33:44:55:66", "connected": False, "paired": False}


def test_ws_bluetooth_sends_the_snapshot_on_connect():
    keyboard = _keyboard()
    _load_bluez(keyboard)

    with _client_for(keyboard) as client, client.websocket_connect("/ws/bluetooth") as websocket:
        message = websocket.receive_json()

    assert message["type"] == "snapshot"
    assert message["bluez_available"] is True
    assert message["adapter"]["powered"] is True
    assert message["devices"] == [{"name": "Apple TV", "address": "AA:BB:CC:DD:EE:FF", "connected": False, "paired": True}]


def test_ws_bluetooth_snapshot_without_bluez():
    with _client_for(_keyboard()) as client, client.websocket_connect("/ws/bluetooth") as websocket:
        message = websocket.receive_json()

    assert message == {"type": "snapshot", "bluez_available": False, "adapter": None, "devices": []}


def test_ws_bluetooth_sends_changes_after_the_snapshot():
    keyboard = _keyboard()
    _load_bluez(keyboard)

    with _client_for(keyboard) as client, client.websocket_connect("/ws/bluetooth") as websocket:
        websocket.receive_json()  # snapshot

        client.portal.call(  # type: ignore[union-attr]
            lambda: keyboard.state.properties_changed(DEVICE_PATH, "org.bluez.Device1", {"Connected": True})
        )
        device_message = websocket.receive_json()
        client.portal.call(keyboard.state.bluez_lost)  # type: ignore[union-attr]
        messages = [websocket.receive_json() for _ in range(3)]

    assert device_message == {
        "type": "device",
        "address": "AA:BB:CC:DD:EE:FF",
        "device": {"name": "Apple TV", "address": "AA:BB:CC:DD:EE:FF", "connected": True, "paired": True},
    }
    assert [message["type"] for message in messages] == ["device", "adapter", "availability"]
    assert messages[-1]["available"] is False


def test_ws_bluetooth_rejects_inbound_text():
    with _client_for(_keyboard()) as client, client.websocket_connect("/ws/bluetooth") as websocket:
        websocket.receive_json()

        websocket.send_text("hello")

        assert websocket.receive_text() == "This endpoint should only be used to receive Bluetooth updates!"


def test_ws_bluetooth_unsubscribes_when_the_client_disconnects():
    keyboard = _keyboard()

    with _client_for(keyboard) as client:
        with client.websocket_connect("/ws/bluetooth") as websocket:
            websocket.receive_json()
            assert len(keyboard.events._subscriptions) == 1

        client.portal.call(asyncio.sleep, 0.05)  # type: ignore[union-attr]

        assert len(keyboard.events._subscriptions) == 0


def test_ws_bluetooth_closes_a_client_that_fell_behind():
    keyboard = _keyboard()
    _load_bluez(keyboard)

    with _client_for(keyboard) as client, client.websocket_connect("/ws/bluetooth") as websocket:
        websocket.receive_json()

        def flood() -> None:
            for index in range(MAX_QUEUED_CHANGES + 1):
                keyboard.state.properties_changed(ADAPTER_PATH, "org.bluez.Adapter1", {"Powered": bool(index % 2)})

        client.portal.call(flood)  # type: ignore[union-attr]

        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                websocket.receive_json()

    assert closed.value.code == 1013


class FakeBus:
    def __init__(self, connected: bool = True):
        self.connected = connected


class FakeAdapter:
    def __init__(self, powered: bool = True):
        self._powered = powered

    async def get_powered(self) -> bool:
        return self._powered


def _fake_adapter_class(powered: bool = True, error: Exception | None = None):
    class FakeAdapterClass:
        @staticmethod
        async def get_first(bus):
            if error is not None:
                raise error
            return FakeAdapter(powered)

    return FakeAdapterClass


async def test_health_down_without_a_bus():
    health = await BleKeyboard().health()

    assert health.name == "bluetooth"
    assert health.status == ComponentStatus.DOWN
    assert health.detail == "Not connected to the system D-Bus"


async def test_health_down_when_the_bus_connection_was_lost():
    keyboard = BleKeyboard()
    keyboard.bus = FakeBus(connected=False)

    assert (await keyboard.health()).status == ComponentStatus.DOWN


async def test_health_down_when_there_is_no_adapter(monkeypatch):
    monkeypatch.setattr(
        "ble_keyboard.ble_keyboard.Adapter", _fake_adapter_class(error=ValueError("No adapters found"))
    )
    keyboard = BleKeyboard()
    keyboard.bus = FakeBus()

    health = await keyboard.health()

    assert health.status == ComponentStatus.DOWN
    assert health.detail == "No usable Bluetooth adapter: ValueError: No adapters found"


async def test_health_degraded_when_the_adapter_is_powered_off(monkeypatch):
    monkeypatch.setattr("ble_keyboard.ble_keyboard.Adapter", _fake_adapter_class(powered=False))
    keyboard = BleKeyboard()
    keyboard.bus = FakeBus()

    health = await keyboard.health()

    assert health.status == ComponentStatus.DEGRADED
    assert health.detail == "Bluetooth adapter is powered off"


async def test_health_ok_with_a_powered_adapter(monkeypatch):
    monkeypatch.setattr("ble_keyboard.ble_keyboard.Adapter", _fake_adapter_class(powered=True))
    keyboard = BleKeyboard()
    keyboard.bus = FakeBus()

    assert (await keyboard.health()).status == ComponentStatus.OK


def _monitored_keyboard(adapter_powered: bool | None = True) -> BleKeyboard:
    keyboard = BleKeyboard()
    keyboard.bus = FakeBus()  # type: ignore[assignment]  # duck-typed test double
    keyboard.monitor = FakeMonitor(keyboard.bus)  # type: ignore[assignment]  # duck-typed test double
    managed_objects: dict = {}
    if adapter_powered is not None:
        managed_objects[ADAPTER_PATH] = {"org.bluez.Adapter1": {"Powered": adapter_powered}}
    keyboard.state.load(managed_objects)
    return keyboard


@pytest.fixture
def no_bluez_queries(monkeypatch):
    class FailingAdapter:
        @staticmethod
        async def get_first(bus):
            raise AssertionError("health should come from the cached state")

    monkeypatch.setattr("ble_keyboard.ble_keyboard.Adapter", FailingAdapter)


async def test_health_ok_from_the_state_with_a_powered_adapter(no_bluez_queries):
    health = await _monitored_keyboard(adapter_powered=True).health()

    assert health.status == ComponentStatus.OK


async def test_health_degraded_from_the_state_when_the_adapter_is_powered_off(no_bluez_queries):
    health = await _monitored_keyboard(adapter_powered=False).health()

    assert health.status == ComponentStatus.DEGRADED
    assert health.detail == "Bluetooth adapter is powered off"


async def test_health_down_from_the_state_when_there_is_no_adapter(no_bluez_queries):
    health = await _monitored_keyboard(adapter_powered=None).health()

    assert health.status == ComponentStatus.DOWN
    assert health.detail == "No Bluetooth adapter"


async def test_health_down_from_the_state_when_bluetoothd_is_gone(no_bluez_queries):
    keyboard = _monitored_keyboard()
    keyboard.state.bluez_lost()

    health = await keyboard.health()

    assert health.status == ComponentStatus.DOWN
    assert health.detail == "bluetoothd isn't available"


async def test_health_follows_the_state_as_it_changes(no_bluez_queries):
    keyboard = _monitored_keyboard(adapter_powered=True)

    keyboard.state.properties_changed(ADAPTER_PATH, "org.bluez.Adapter1", {"Powered": False})
    assert (await keyboard.health()).status == ComponentStatus.DEGRADED

    keyboard.state.properties_changed(ADAPTER_PATH, "org.bluez.Adapter1", {"Powered": True})
    assert (await keyboard.health()).status == ComponentStatus.OK


async def test_health_down_when_the_bus_connection_was_lost_even_though_the_state_looks_fine(no_bluez_queries):
    keyboard = _monitored_keyboard()
    keyboard.bus = FakeBus(connected=False)

    assert (await keyboard.health()).status == ComponentStatus.DOWN


async def test_health_never_touches_devices_because_listing_them_triggers_pairing(monkeypatch):
    monkeypatch.setattr("ble_keyboard.ble_keyboard.Adapter", _fake_adapter_class())
    monkeypatch.setattr(
        BleKeyboard, "devices", property(lambda self: pytest.fail("health() must not touch .devices"))
    )
    keyboard = BleKeyboard()
    keyboard.bus = FakeBus()

    await keyboard.health()


class FakeAgent:
    """Stands in for NoIoAgent, recording how it was registered."""

    instances: ClassVar[list["FakeAgent"]] = []
    fail_register = False

    def __init__(self):
        self.is_exported = False
        self.register_calls: list[dict[str, Any]] = []
        FakeAgent.instances.append(self)

    async def register(self, bus, **kwargs):
        self.register_calls.append(kwargs)
        self.is_exported = True
        if FakeAgent.fail_register:
            raise RuntimeError("bluez said no")

    def unexport(self):
        self.is_exported = False


class FakeAdvertisement:
    def __init__(self, *args, **kwargs):
        pass

    async def register(self, bus, adapter=None):
        pass


@pytest.fixture
def fake_bluez(monkeypatch):
    async def get_first(bus):
        return object()

    FakeAgent.instances = []
    FakeAgent.fail_register = False
    monkeypatch.setattr("ble_keyboard.ble_keyboard.NoIoAgent", FakeAgent)
    monkeypatch.setattr("ble_keyboard.ble_keyboard.Advertisement", FakeAdvertisement)
    monkeypatch.setattr("ble_keyboard.ble_keyboard.Adapter.get_first", get_first)


@pytest.mark.asyncio
async def test_advertise_registers_the_agent_with_an_explicit_path(fake_bluez):
    # bluez_peripheral 0.2.0a5 forwards path=None to BlueZ's RegisterAgent
    # unless a path is given, which BlueZ rejects (HTTP 500 on /start_advertisement).
    keyboard = BleKeyboard()

    await keyboard.advertise()

    assert FakeAgent.instances[0].register_calls == [{"path": BleKeyboard.AGENT_PATH}]


@pytest.mark.asyncio
async def test_advertise_registers_the_agent_only_once(fake_bluez):
    keyboard = BleKeyboard()

    await keyboard.advertise()
    await keyboard.advertise()

    assert len(FakeAgent.instances) == 1


@pytest.mark.asyncio
async def test_advertise_can_retry_after_the_agent_registration_failed(fake_bluez):
    keyboard = BleKeyboard()
    FakeAgent.fail_register = True

    with pytest.raises(RuntimeError):
        await keyboard.advertise()

    assert keyboard.agent is None
    assert not FakeAgent.instances[0].is_exported  # the export was undone so the path is free again

    FakeAgent.fail_register = False
    await keyboard.advertise()

    assert keyboard.agent is FakeAgent.instances[1]


class FakeMonitor:
    instances: ClassVar[list["FakeMonitor"]] = []
    fail_start = False

    def __init__(self, bus, state=None):
        self.bus = bus
        self.state = state
        self.started = False
        FakeMonitor.instances.append(self)

    async def start(self):
        if FakeMonitor.fail_start:
            raise RuntimeError("no D-Bus match for you")
        self.started = True


@pytest.fixture
def fake_create_deps(monkeypatch):
    bus = object()

    async def get_message_bus():
        return bus

    async def register_services(self):
        pass

    FakeMonitor.instances = []
    FakeMonitor.fail_start = False
    monkeypatch.setattr("ble_keyboard.ble_keyboard.get_message_bus", get_message_bus)
    monkeypatch.setattr("ble_keyboard.ble_keyboard.BluezMonitor", FakeMonitor)
    monkeypatch.setattr(BleKeyboard, "register_services", register_services)
    return bus


async def test_create_starts_the_bluetooth_monitor_on_the_keyboards_bus(fake_create_deps):
    keyboard = await BleKeyboard.create()

    assert keyboard.monitor is FakeMonitor.instances[0]
    assert keyboard.monitor.started  # type: ignore[attr-defined]
    assert FakeMonitor.instances[0].bus is fake_create_deps


async def test_create_gives_the_monitor_the_keyboards_state(fake_create_deps):
    keyboard = await BleKeyboard.create()

    assert FakeMonitor.instances[0].state is keyboard.state


async def test_create_still_succeeds_when_the_monitor_cannot_start(fake_create_deps, caplog):
    FakeMonitor.fail_start = True

    keyboard = await BleKeyboard.create()

    assert keyboard.monitor is None
    assert "Couldn't start the Bluetooth state monitor" in caplog.text
