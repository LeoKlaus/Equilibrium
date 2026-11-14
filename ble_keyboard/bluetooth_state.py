import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

ADAPTER_INTERFACE = "org.bluez.Adapter1"
ADVERTISING_MANAGER_INTERFACE = "org.bluez.LEAdvertisingManager1"
DEVICE_INTERFACE = "org.bluez.Device1"


def normalize_address(address: str) -> str:
    """'aa-bb-cc-dd-ee-ff' -> 'AA:BB:CC:DD:EE:FF'. Addresses are typed in by
    users (e.g. a scene's bluetooth_address), BlueZ always reports upper case."""
    return address.strip().upper().replace("-", ":")


def address_from_path(path: str) -> str:
    """'/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF' -> 'AA:BB:CC:DD:EE:FF'"""
    node = path.rsplit("/", 1)[-1]
    return normalize_address(node.removeprefix("dev_").replace("_", ":"))


@dataclass(frozen=True)
class AdapterState:
    powered: bool = False
    discoverable: bool = False
    pairable: bool = False
    advertising: bool = False


@dataclass(frozen=True)
class DeviceState:
    address: str
    name: str | None = None
    connected: bool = False
    paired: bool = False


@dataclass(frozen=True)
class BluetoothSnapshot:
    """An immutable copy of everything known, e.g. to send a new websocket
    client its initial state."""

    bluez_available: bool
    adapter: AdapterState | None
    devices: Mapping[str, DeviceState]


@dataclass(frozen=True)
class AvailabilityChanged:
    """bluetoothd appeared or went away."""

    available: bool


@dataclass(frozen=True)
class AdapterChanged:
    adapter: AdapterState | None  # None: the adapter is gone


@dataclass(frozen=True)
class DeviceChanged:
    address: str
    device: DeviceState | None  # None: BlueZ forgot the device


StateChange = AvailabilityChanged | AdapterChanged | DeviceChanged
StateListener = Callable[[StateChange], None]


class BluetoothState:
    """What BlueZ currently says about the adapter and the devices it knows,
    kept up to date from its D-Bus signals (see BluezMonitor)."""

    logger = logging.getLogger(__package__)

    def __init__(self) -> None:
        self._available = False
        self._adapters: dict[str, AdapterState] = {}  # by object path
        self._devices: dict[str, DeviceState] = {}  # by object path
        self._listeners: list[StateListener] = []

    # --- reading ---

    @property
    def bluez_available(self) -> bool:
        return self._available

    @property
    def adapter(self) -> AdapterState | None:
        """The adapter in use. The rest of the module only ever uses the first
        one (Adapter.get_first), so that's the one tracked here too."""
        if not self._adapters:
            return None
        return self._adapters[min(self._adapters)]

    @property
    def snapshot(self) -> BluetoothSnapshot:
        devices = {device.address: device for device in self._devices.values()}
        return BluetoothSnapshot(self._available, self.adapter, MappingProxyType(devices))

    def device(self, address: str) -> DeviceState | None:
        """A device by address, in any case/separator, e.g. a scene's bluetooth_address."""
        wanted = normalize_address(address)
        for device in self._devices.values():
            if device.address == wanted:
                return device
        return None

    def device_at(self, path: str) -> DeviceState | None:
        return self._devices.get(path)

    # --- listening ---

    def add_listener(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: StateListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    # --- feeding ---

    def load(self, managed_objects: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> None:
        """Replaces everything with a full ObjectManager.GetManagedObjects
        result (property values already unwrapped). Notifies listeners only
        about what differs from what was known before."""
        before = self._begin()

        adapters: dict[str, AdapterState] = {}
        devices: dict[str, DeviceState] = {}
        for path, interfaces in managed_objects.items():
            adapter = self._adapter_from_interfaces(AdapterState(), interfaces)
            if adapter is not None:
                adapters[path] = adapter
            device = self._device_from_interfaces(path, interfaces, existing=None)
            if device is not None:
                devices[path] = device

        self._adapters = adapters
        self._devices = devices
        self._available = True
        self._finish(before)

    def bluez_lost(self) -> None:
        before = self._begin()
        self._adapters = {}
        self._devices = {}
        self._available = False
        self._finish(before)

    def interfaces_added(self, path: str, interfaces: Mapping[str, Mapping[str, Any]]) -> None:
        before = self._begin()

        adapter = self._adapter_from_interfaces(self._adapters.get(path, AdapterState()), interfaces)
        if adapter is not None:
            self._adapters[path] = adapter
        device = self._device_from_interfaces(path, interfaces, existing=self._devices.get(path))
        if device is not None:
            self._devices[path] = device

        self._finish(before)

    def interfaces_removed(self, path: str, interfaces: list[str]) -> None:
        before = self._begin()

        if ADAPTER_INTERFACE in interfaces:
            self._adapters.pop(path, None)
        if DEVICE_INTERFACE in interfaces:
            self._devices.pop(path, None)

        self._finish(before)

    def properties_changed(self, path: str, interface: str, changed: Mapping[str, Any]) -> None:
        """Only applied to objects already known"""
        before = self._begin()

        if interface in (ADAPTER_INTERFACE, ADVERTISING_MANAGER_INTERFACE):
            current = self._adapters.get(path)
            if current is not None:
                updated = self._adapter_from_interfaces(current, {interface: changed})
                if updated is not None:
                    self._adapters[path] = updated
        elif interface == DEVICE_INTERFACE:
            current_device = self._devices.get(path)
            if current_device is not None:
                self._devices[path] = self._updated_device(current_device, changed)

        self._finish(before)

    # --- building states from BlueZ's properties ---

    @staticmethod
    def _adapter_from_interfaces(
        current: AdapterState, interfaces: Mapping[str, Mapping[str, Any]]
    ) -> AdapterState | None:
        """`current` with whatever the given interfaces say; None if none of
        them are about an adapter."""
        adapter = interfaces.get(ADAPTER_INTERFACE)
        advertising = interfaces.get(ADVERTISING_MANAGER_INTERFACE)
        if adapter is None and advertising is None:
            return None

        updates: dict[str, bool] = {}
        for source, name in (("Powered", "powered"), ("Discoverable", "discoverable"), ("Pairable", "pairable")):
            if adapter is not None and source in adapter:
                updates[name] = bool(adapter[source])
        if advertising is not None and "ActiveInstances" in advertising:
            updates["advertising"] = advertising["ActiveInstances"] > 0
        return replace(current, **updates)

    @classmethod
    def _device_from_interfaces(
        cls, path: str, interfaces: Mapping[str, Mapping[str, Any]], existing: DeviceState | None
    ) -> DeviceState | None:
        properties = interfaces.get(DEVICE_INTERFACE)
        if properties is None:
            return None
        return cls._updated_device(existing or DeviceState(address=address_from_path(path)), properties)

    @staticmethod
    def _updated_device(device: DeviceState, properties: Mapping[str, Any]) -> DeviceState:
        updates: dict[str, Any] = {}
        if "Connected" in properties:
            updates["connected"] = bool(properties["Connected"])
        if "Paired" in properties:
            updates["paired"] = bool(properties["Paired"])
        name = properties.get("Alias") or properties.get("Name")
        if name:
            updates["name"] = name
        return replace(device, **updates)

    # --- change detection ---

    def _begin(self) -> "_Before":
        return _Before(
            available=self._available,
            adapter=self.adapter,
            devices=dict(self._devices),
        )

    def _finish(self, before: "_Before") -> None:
        changes: list[StateChange] = []

        for path, device in self._devices.items():
            if before.devices.get(path) != device:
                changes.append(DeviceChanged(device.address, device))
        for path, old_device in before.devices.items():
            if path not in self._devices:
                changes.append(DeviceChanged(old_device.address, None))

        if before.adapter != self.adapter:
            changes.append(AdapterChanged(self.adapter))

        if before.available != self._available:
            changes.append(AvailabilityChanged(self._available))

        for change in changes:
            for listener in list(self._listeners):
                try:
                    listener(change)
                except Exception:
                    self.logger.exception(f"A Bluetooth state listener raised for {change}")


@dataclass
class _Before:
    available: bool
    adapter: AdapterState | None
    devices: dict[str, DeviceState]
