import logging
from typing import Any

from dbus_fast import Message, MessageType, Variant
from dbus_fast.aio import MessageBus

BLUEZ = "org.bluez"

_DBUS = "org.freedesktop.DBus"
_PROPERTIES = "org.freedesktop.DBus.Properties"
_OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
_ADAPTER = "org.bluez.Adapter1"
_ADVERTISING_MANAGER = "org.bluez.LEAdvertisingManager1"
_DEVICE = "org.bluez.Device1"

# BlueZ emits InterfacesAdded/Removed from the root path, which
# path_namespace='/org/bluez' wouldn't match - hence the separate rules.
_MATCH_RULES = (
    f"type='signal',sender='{BLUEZ}',interface='{_PROPERTIES}',member='PropertiesChanged',path_namespace='/org/bluez'",
    f"type='signal',sender='{BLUEZ}',interface='{_OBJECT_MANAGER}'",
    f"type='signal',sender='{_DBUS}',interface='{_DBUS}',member='NameOwnerChanged',arg0='{BLUEZ}'",
)

_ADAPTER_PROPERTIES = frozenset({"Powered", "PowerState", "Discoverable", "Pairable", "Discovering"})
_ADVERTISING_PROPERTIES = frozenset({"ActiveInstances"})
_DEVICE_PROPERTIES = frozenset({"Connected", "Paired", "Bonded", "Trusted", "Blocked", "ServicesResolved", "Alias"})

# State changes of a remote device worth an INFO line, and their wording
_DEVICE_STATE_CHANGES: dict[str, dict[bool, str]] = {
    "Connected": {True: "connected", False: "disconnected"},
    "Paired": {True: "paired", False: "unpaired"},
    "Bonded": {True: "bonded", False: "no longer bonded"},
}


def _unwrap(value: Any) -> Any:
    return value.value if isinstance(value, Variant) else value


def _unwrap_properties(properties: dict[str, Any]) -> dict[str, Any]:
    return {name: _unwrap(value) for name, value in properties.items()}


def _address_from_path(path: str) -> str:
    """'/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF' -> 'AA:BB:CC:DD:EE:FF'"""
    node = path.rsplit("/", 1)[-1]
    return node.removeprefix("dev_").replace("_", ":")


class BluezMonitor:
    """Listens to BlueZ's D-Bus signals and logs them."""

    logger = logging.getLogger(__package__)

    def __init__(self, bus: MessageBus) -> None:
        self._bus = bus
        self._started = False
        self._aliases: dict[str, str] = {}

    async def start(self) -> None:
        self._bus.add_message_handler(self._on_message)
        self._started = True
        try:
            for rule in _MATCH_RULES:
                await self._call_dbus("AddMatch", "s", [rule])
            await self._load_known_devices()
        except Exception:
            await self.stop()
            raise
        self.logger.debug("Bluetooth monitor started")

    async def stop(self) -> None:
        self._bus.remove_message_handler(self._on_message)
        if self._started:
            self._started = False
            for rule in _MATCH_RULES:
                try:
                    await self._call_dbus("RemoveMatch", "s", [rule])
                except Exception:
                    self.logger.debug("Couldn't remove D-Bus match rule", exc_info=True)

    async def _call_dbus(self, member: str, signature: str, body: list[Any]) -> None:
        reply = await self._bus.call(
            Message(
                destination=_DBUS,
                path="/org/freedesktop/DBus",
                interface=_DBUS,
                member=member,
                signature=signature,
                body=body,
            )
        )
        if reply is not None and reply.message_type == MessageType.ERROR:
            raise RuntimeError(f"{member} failed: {reply.error_name}: {reply.body}")

    async def _load_known_devices(self) -> None:
        """Remembers the names of devices BlueZ already knows (and logs the
        adapter state) so later events can say which device they're about."""
        reply = await self._bus.call(
            Message(
                destination=BLUEZ,
                path="/",
                interface=_OBJECT_MANAGER,
                member="GetManagedObjects",
            )
        )
        if reply is None or reply.message_type == MessageType.ERROR:
            self.logger.warning("Bluetooth monitor: BlueZ isn't available right now")
            return

        for path, interfaces in reply.body[0].items():
            device = interfaces.get(_DEVICE)
            if device is not None:
                self._remember_device(path, _unwrap_properties(device))
            adapter = interfaces.get(_ADAPTER)
            if adapter is not None:
                properties = _unwrap_properties(adapter)
                self.logger.debug(
                    f"Bluetooth adapter {path}: powered={properties.get('Powered')}, "
                    f"discoverable={properties.get('Discoverable')}"
                )

        self.logger.debug(f"Bluetooth monitor: {len(self._aliases)} known device(s)")

    def _remember_device(self, path: str, properties: dict[str, Any]) -> None:
        alias = properties.get("Alias") or properties.get("Name")
        if alias:
            self._aliases[path] = alias

    def _device_label(self, path: str) -> str:
        address = _address_from_path(path)
        alias = self._aliases.get(path)
        return f"{address} ({alias})" if alias else address

    def _on_message(self, message: Message) -> None:
        if message.message_type != MessageType.SIGNAL:
            return

        try:
            if message.member == "PropertiesChanged" and message.path and message.path.startswith("/org/bluez"):
                interface, changed, _invalidated = message.body
                self._on_properties_changed(message.path, interface, _unwrap_properties(changed))
            elif message.member == "InterfacesAdded":
                path, interfaces = message.body
                self._on_interfaces_added(path, interfaces)
            elif message.member == "InterfacesRemoved":
                path, interfaces = message.body
                self._on_interfaces_removed(path, interfaces)
            elif message.member == "NameOwnerChanged":
                name, old_owner, new_owner = message.body
                if name == BLUEZ:
                    self._on_bluez_owner_changed(old_owner, new_owner)
        except Exception:
            self.logger.exception("Couldn't process a BlueZ signal")

    def _on_properties_changed(self, path: str, interface: str, changed: dict[str, Any]) -> None:
        if interface == _DEVICE:
            self._on_device_properties_changed(path, changed)
        elif interface == _ADAPTER:
            for name in sorted(_ADAPTER_PROPERTIES & changed.keys()):
                level = logging.INFO if name == "Powered" else logging.DEBUG
                self.logger.log(level, f"Bluetooth adapter {name} = {changed[name]}")
        elif interface == _ADVERTISING_MANAGER:
            for name in sorted(_ADVERTISING_PROPERTIES & changed.keys()):
                self.logger.debug(f"Bluetooth advertising: {name} = {changed[name]}")

    def _on_device_properties_changed(self, path: str, changed: dict[str, Any]) -> None:
        if "Alias" in changed:
            self._aliases[path] = changed["Alias"]

        label = self._device_label(path)
        for name in sorted(_DEVICE_PROPERTIES & changed.keys()):
            value = changed[name]
            wording = _DEVICE_STATE_CHANGES.get(name)
            if wording is not None and value in wording:
                self.logger.info(f"Bluetooth device {label} {wording[value]}")
            else:
                self.logger.debug(f"Bluetooth device {label}: {name} = {value}")

    def _on_interfaces_added(self, path: str, interfaces: dict[str, Any]) -> None:
        device = interfaces.get(_DEVICE)
        if device is None:
            return
        self._remember_device(path, _unwrap_properties(device))
        self.logger.debug(f"Bluetooth device {self._device_label(path)} added")

    def _on_interfaces_removed(self, path: str, interfaces: list[str]) -> None:
        if _DEVICE not in interfaces:
            return
        self.logger.debug(f"Bluetooth device {self._device_label(path)} removed")
        self._aliases.pop(path, None)

    def _on_bluez_owner_changed(self, old_owner: str, new_owner: str) -> None:
        if not new_owner:
            self._aliases.clear()
            self.logger.warning(
                "bluetoothd went away - Bluetooth is unavailable until it comes back "
                "(registered services and the pairing agent are lost with it)"
            )
        else:
            self.logger.info("bluetoothd is available again")
