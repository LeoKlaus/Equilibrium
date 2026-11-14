import asyncio
import logging

from api.models.scene import SceneWithRelationships
from api.models.scene_status import SceneStatus
from api.models.websocket_responses import BleDevice
from ble_keyboard.bluetooth_events import device_for_address
from ble_keyboard.bluetooth_state import BluetoothState
from hub.bluetooth_status_forwarder import BluetoothStatusForwarder
from hub.status_store import StatusStore

DEVICE = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
OTHER_DEVICE = "/org/bluez/hci0/dev_11_22_33_44_55_66"
ADDRESS = "AA:BB:CC:DD:EE:FF"


def _managed_objects(connected: bool = False) -> dict:
    return {
        DEVICE: {"org.bluez.Device1": {"Alias": "Apple TV", "Connected": connected, "Paired": True}},
        OTHER_DEVICE: {"org.bluez.Device1": {"Alias": "Speaker", "Connected": False, "Paired": True}},
    }


async def _setup(scene_address: str | None = ADDRESS):
    state = BluetoothState()
    state.load(_managed_objects())
    store = StatusStore(bluetooth_device_resolver=lambda address: device_for_address(state.device(address), address))
    forwarder = BluetoothStatusForwarder(state, store)
    if scene_address is not None:
        await store.set_scene(SceneWithRelationships(id=1, name="Movie", bluetooth_address=scene_address),
                              SceneStatus.ACTIVE)
    notifications: list[BleDevice | None] = []

    async def callback(status):
        notifications.append(status.bluetooth_device)

    store.set_callback(callback)
    return state, store, forwarder, notifications


async def _settle(forwarder: BluetoothStatusForwarder) -> None:
    await asyncio.gather(*forwarder._tasks)


async def test_a_change_of_the_scenes_device_updates_the_status_and_notifies():
    state, store, forwarder, notifications = await _setup()
    assert store.status.bluetooth_device == BleDevice(name="Apple TV", address=ADDRESS, paired=True)

    state.properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True})
    await _settle(forwarder)

    expected = BleDevice(name="Apple TV", address=ADDRESS, connected=True, paired=True)
    assert store.status.bluetooth_device == expected
    assert notifications == [expected]


async def test_the_scenes_address_matches_in_any_case_and_separator():
    state, _store, forwarder, notifications = await _setup(scene_address="aa-bb-cc-dd-ee-ff")

    state.properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True})
    await _settle(forwarder)

    assert len(notifications) == 1


async def test_changes_of_other_devices_are_not_forwarded():
    state, _store, forwarder, notifications = await _setup()

    state.properties_changed(OTHER_DEVICE, "org.bluez.Device1", {"Connected": True})

    assert not forwarder._tasks
    assert notifications == []


async def test_adapter_and_availability_changes_are_not_forwarded():
    state, _store, forwarder, notifications = await _setup()

    state.interfaces_added("/org/bluez/hci0", {"org.bluez.Adapter1": {"Powered": True}})

    assert not forwarder._tasks
    assert notifications == []


async def test_nothing_is_forwarded_without_a_scene_or_a_scene_address():
    for scene_address in (None, ""):
        state, _store, forwarder, notifications = await _setup(scene_address=scene_address)

        state.properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True})

        assert not forwarder._tasks
        assert notifications == []


async def test_a_device_bluez_forgot_is_reported_as_disconnected():
    state, store, forwarder, _notifications = await _setup()
    state.properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True})
    await _settle(forwarder)

    state.interfaces_removed(DEVICE, ["org.bluez.Device1"])
    await _settle(forwarder)

    assert store.status.bluetooth_device == BleDevice(address=ADDRESS)


async def test_losing_bluetoothd_reports_the_device_as_disconnected_and_it_comes_back():
    state, store, forwarder, _notifications = await _setup()
    state.properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True})
    await _settle(forwarder)

    state.bluez_lost()
    await _settle(forwarder)
    assert store.status.bluetooth_device == BleDevice(address=ADDRESS)

    state.load(_managed_objects(connected=True))
    await _settle(forwarder)
    assert store.status.bluetooth_device == BleDevice(name="Apple TV", address=ADDRESS, connected=True, paired=True)


async def test_a_failing_status_update_is_logged(caplog):
    state, store, forwarder, _notifications = await _setup()

    async def failing(status):
        raise RuntimeError("socket gone")

    store.set_callback(failing)

    with caplog.at_level(logging.ERROR):
        state.properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True})
        await _settle(forwarder)

    assert "Couldn't forward a Bluetooth device change to the status" in caplog.text
