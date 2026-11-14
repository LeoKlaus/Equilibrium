from api.models.websocket_responses import (
    BleAdapter,
    BleDevice,
    BluetoothAdapterMessage,
    BluetoothAvailabilityMessage,
    BluetoothDeviceMessage,
)
from ble_keyboard.bluetooth_events import (
    MAX_QUEUED_CHANGES,
    BluetoothEventBroadcaster,
    change_message,
    snapshot_message,
)
from ble_keyboard.bluetooth_state import (
    AdapterChanged,
    AdapterState,
    AvailabilityChanged,
    BluetoothState,
    DeviceChanged,
    DeviceState,
)

ADAPTER = "/org/bluez/hci0"
DEVICE = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
ADDRESS = "AA:BB:CC:DD:EE:FF"


def _loaded_state() -> BluetoothState:
    state = BluetoothState()
    state.load(
        {
            ADAPTER: {"org.bluez.Adapter1": {"Powered": True, "Discoverable": True, "Pairable": False}},
            DEVICE: {"org.bluez.Device1": {"Alias": "Apple TV", "Connected": True, "Paired": True}},
        }
    )
    return state


def test_snapshot_message_describes_the_adapter_and_devices():
    message = snapshot_message(_loaded_state().snapshot)

    assert message.model_dump() == {
        "type": "snapshot",
        "bluez_available": True,
        "adapter": {"powered": True, "discoverable": True, "pairable": False, "advertising": False},
        "devices": [{"name": "Apple TV", "address": ADDRESS, "connected": True, "paired": True}],
    }


def test_snapshot_message_without_bluez():
    message = snapshot_message(BluetoothState().snapshot)

    assert message.model_dump() == {"type": "snapshot", "bluez_available": False, "adapter": None, "devices": []}


def test_snapshot_message_uses_an_empty_name_for_unnamed_devices():
    state = BluetoothState()
    state.load({DEVICE: {"org.bluez.Device1": {"Connected": True}}})

    assert snapshot_message(state.snapshot).devices[0].name == ""


def test_change_messages():
    assert change_message(AvailabilityChanged(False)) == BluetoothAvailabilityMessage(available=False)
    assert change_message(AdapterChanged(AdapterState(powered=True))) == BluetoothAdapterMessage(
        adapter=BleAdapter(powered=True)
    )
    assert change_message(AdapterChanged(None)) == BluetoothAdapterMessage(adapter=None)
    assert change_message(DeviceChanged(ADDRESS, DeviceState(ADDRESS, "TV", True, False))) == BluetoothDeviceMessage(
        address=ADDRESS, device=BleDevice(name="TV", address=ADDRESS, connected=True, paired=False)
    )
    assert change_message(DeviceChanged(ADDRESS, None)) == BluetoothDeviceMessage(address=ADDRESS, device=None)


async def test_subscribers_receive_changes_in_order():
    state = _loaded_state()
    broadcaster = BluetoothEventBroadcaster(state)

    with broadcaster.subscribe() as subscription:
        state.properties_changed(DEVICE, "org.bluez.Device1", {"Connected": False})
        state.bluez_lost()

        changes = [subscription.queue.get_nowait() for _ in range(subscription.queue.qsize())]

    assert changes[0] == DeviceChanged(ADDRESS, DeviceState(ADDRESS, "Apple TV", False, True))
    assert changes[-1] == AvailabilityChanged(False)


async def test_every_subscriber_gets_every_change():
    state = _loaded_state()
    broadcaster = BluetoothEventBroadcaster(state)

    with broadcaster.subscribe() as first, broadcaster.subscribe() as second:
        state.properties_changed(ADAPTER, "org.bluez.Adapter1", {"Powered": False})

        assert first.queue.qsize() == second.queue.qsize() == 1


async def test_nothing_is_queued_after_unsubscribing():
    state = _loaded_state()
    broadcaster = BluetoothEventBroadcaster(state)

    with broadcaster.subscribe() as subscription:
        pass
    state.properties_changed(ADAPTER, "org.bluez.Adapter1", {"Powered": False})

    assert subscription.queue.empty()


async def test_changes_before_subscribing_are_not_delivered():
    state = _loaded_state()
    broadcaster = BluetoothEventBroadcaster(state)

    state.properties_changed(ADAPTER, "org.bluez.Adapter1", {"Powered": False})
    with broadcaster.subscribe() as subscription:
        assert subscription.queue.empty()


async def test_a_subscriber_that_falls_behind_is_told_to_start_over():
    state = _loaded_state()
    broadcaster = BluetoothEventBroadcaster(state)

    with broadcaster.subscribe() as slow, broadcaster.subscribe() as fast:
        for index in range(MAX_QUEUED_CHANGES + 1):
            state.properties_changed(ADAPTER, "org.bluez.Adapter1", {"Powered": bool(index % 2)})
            if index < MAX_QUEUED_CHANGES:
                fast.queue.get_nowait()

        assert slow.queue.qsize() == 1
        assert slow.queue.get_nowait() is None
        assert fast.queue.qsize() == 1  # still subscribed, got the latest change

        state.properties_changed(ADAPTER, "org.bluez.Adapter1", {"Powered": True})
        assert slow.queue.empty()  # no longer subscribed
