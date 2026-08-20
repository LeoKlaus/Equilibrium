from fastapi import FastAPI
from fastapi.testclient import TestClient

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
    defaults = {
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
    app = FastAPI()
    app.include_router(keyboard.router)
    return TestClient(app)


def test_router_has_the_expected_routes():
    keyboard = _keyboard()

    paths = {route.path for route in keyboard.router.routes}

    assert paths == {
        "/bluetooth/devices",
        "/bluetooth/start_advertisement",
        "/bluetooth/start_pairing",
        "/bluetooth/connect/{mac_address}",
        "/bluetooth/disconnect",
        "/ws/bt_pairing",
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
