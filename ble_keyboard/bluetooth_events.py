import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict

from api.models.websocket_responses import (
    BleAdapter,
    BleDevice,
    BluetoothAdapterMessage,
    BluetoothAvailabilityMessage,
    BluetoothDeviceMessage,
    BluetoothMessage,
    BluetoothSnapshotMessage,
)
from ble_keyboard.bluetooth_state import (
    AdapterChanged,
    AdapterState,
    AvailabilityChanged,
    BluetoothSnapshot,
    BluetoothState,
    DeviceChanged,
    DeviceState,
    StateChange,
    normalize_address,
)

MAX_QUEUED_CHANGES = 100


def _adapter(adapter: AdapterState | None) -> BleAdapter | None:
    return None if adapter is None else BleAdapter(**asdict(adapter))


def _device(device: DeviceState) -> BleDevice:
    return BleDevice(name=device.name or "", address=device.address, connected=device.connected, paired=device.paired)


def device_for_address(device: DeviceState | None, address: str) -> BleDevice:
    """A device for clients that follow one specific address: unknown to
    BlueZ is reported as disconnected."""
    if device is None:
        return BleDevice(address=normalize_address(address))
    return _device(device)


def snapshot_message(snapshot: BluetoothSnapshot) -> BluetoothSnapshotMessage:
    return BluetoothSnapshotMessage(
        bluez_available=snapshot.bluez_available,
        adapter=_adapter(snapshot.adapter),
        devices=[_device(device) for device in snapshot.devices.values()],
    )


def change_message(change: StateChange) -> BluetoothMessage:
    match change:
        case AvailabilityChanged(available=available):
            return BluetoothAvailabilityMessage(available=available)
        case AdapterChanged(adapter=adapter):
            return BluetoothAdapterMessage(adapter=_adapter(adapter))
        case DeviceChanged(address=address, device=device):
            return BluetoothDeviceMessage(address=address, device=None if device is None else _device(device))


class Subscription:
    """A subscriber's queue of changes. `None` in it means the subscriber fell
    too far behind"""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[StateChange | None] = asyncio.Queue(maxsize=MAX_QUEUED_CHANGES)


class BluetoothEventBroadcaster:
    """Hands the changes of a BluetoothState to async consumers (websockets).

    The state notifies its listeners synchronously from inside the D-Bus
    reader, so this only puts changes on queues; sending is up to the consumer.
    """

    def __init__(self, state: BluetoothState) -> None:
        self._subscriptions: set[Subscription] = set()
        state.add_listener(self._on_change)

    @contextmanager
    def subscribe(self) -> Iterator[Subscription]:
        subscription = Subscription()
        self._subscriptions.add(subscription)
        try:
            yield subscription
        finally:
            self._subscriptions.discard(subscription)

    def _on_change(self, change: StateChange) -> None:
        for subscription in list(self._subscriptions):
            try:
                subscription.queue.put_nowait(change)
            except asyncio.QueueFull:
                self._subscriptions.discard(subscription)
                while not subscription.queue.empty():
                    subscription.queue.get_nowait()
                subscription.queue.put_nowait(None)
