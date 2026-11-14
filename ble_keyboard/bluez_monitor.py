import asyncio
import logging
from typing import Any

from dbus_fast import Message, MessageType, Variant
from dbus_fast.aio import MessageBus

from ble_keyboard.bluetooth_state import (
    ADAPTER_INTERFACE,
    ADVERTISING_MANAGER_INTERFACE,
    DEVICE_INTERFACE,
    BluetoothState,
    address_from_path,
)

BLUEZ = "org.bluez"

_DBUS = "org.freedesktop.DBus"
_PROPERTIES = "org.freedesktop.DBus.Properties"
_OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"

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


def _unwrap_interfaces(interfaces: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {name: _unwrap_properties(properties) for name, properties in interfaces.items()}


class BluezMonitor:
    """Listens to BlueZ's D-Bus signals, logs them and keeps `state` up to date."""

    logger = logging.getLogger(__package__)

    def __init__(self, bus: MessageBus, state: BluetoothState | None = None) -> None:
        self._bus = bus
        self._started = False
        self._tasks: set[asyncio.Task[None]] = set()
        self.state = state if state is not None else BluetoothState()

    async def start(self) -> None:
        self._bus.add_message_handler(self._on_message)
        self._started = True
        try:
            for rule in _MATCH_RULES:
                await self._call_dbus("AddMatch", "s", [rule])
            await self._load_state()
        except Exception:
            await self.stop()
            raise
        self.logger.debug("Bluetooth monitor started")

    async def stop(self) -> None:
        self._bus.remove_message_handler(self._on_message)
        for task in list(self._tasks):
            task.cancel()
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

    async def _load_state(self) -> None:
        """Reads everything BlueZ currently has into the state, so the signals
        that follow only have to describe changes."""
        reply = await self._bus.call(
            Message(
                destination=BLUEZ,
                path="/",
                interface=_OBJECT_MANAGER,
                member="GetManagedObjects",
            )
        )
        if reply is None or reply.message_type == MessageType.ERROR:
            self.state.bluez_lost()
            self.logger.warning("Bluetooth monitor: BlueZ isn't available right now")
            return

        self.state.load({path: _unwrap_interfaces(interfaces) for path, interfaces in reply.body[0].items()})

        adapter = self.state.adapter
        if adapter is not None:
            self.logger.debug(f"Bluetooth adapter: powered={adapter.powered}, discoverable={adapter.discoverable}")
        self.logger.debug(f"Bluetooth monitor: {len(self.state.snapshot.devices)} known device(s)")

    def _device_label(self, path: str) -> str:
        device = self.state.device_at(path)
        address = address_from_path(path)
        return f"{address} ({device.name})" if device is not None and device.name else address

    def _on_message(self, message: Message) -> None:
        if message.message_type != MessageType.SIGNAL:
            return

        try:
            if message.member == "PropertiesChanged" and message.path and message.path.startswith("/org/bluez"):
                interface, changed, _invalidated = message.body
                self._on_properties_changed(message.path, interface, _unwrap_properties(changed))
            elif message.member == "InterfacesAdded":
                path, interfaces = message.body
                self._on_interfaces_added(path, _unwrap_interfaces(interfaces))
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
        self.state.properties_changed(path, interface, changed)

        if interface == DEVICE_INTERFACE:
            self._log_device_properties(path, changed)
        elif interface == ADAPTER_INTERFACE:
            for name in sorted(_ADAPTER_PROPERTIES & changed.keys()):
                level = logging.INFO if name == "Powered" else logging.DEBUG
                self.logger.log(level, f"Bluetooth adapter {name} = {changed[name]}")
        elif interface == ADVERTISING_MANAGER_INTERFACE:
            for name in sorted(_ADVERTISING_PROPERTIES & changed.keys()):
                self.logger.debug(f"Bluetooth advertising: {name} = {changed[name]}")

    def _log_device_properties(self, path: str, changed: dict[str, Any]) -> None:
        label = self._device_label(path)
        for name in sorted(_DEVICE_PROPERTIES & changed.keys()):
            value = changed[name]
            wording = _DEVICE_STATE_CHANGES.get(name)
            if wording is not None and value in wording:
                self.logger.info(f"Bluetooth device {label} {wording[value]}")
            else:
                self.logger.debug(f"Bluetooth device {label}: {name} = {value}")

    def _on_interfaces_added(self, path: str, interfaces: dict[str, dict[str, Any]]) -> None:
        self.state.interfaces_added(path, interfaces)
        if DEVICE_INTERFACE in interfaces:
            self.logger.debug(f"Bluetooth device {self._device_label(path)} added")

    def _on_interfaces_removed(self, path: str, interfaces: list[str]) -> None:
        if DEVICE_INTERFACE in interfaces:
            # Before the state drops it, so the label still has the name
            self.logger.debug(f"Bluetooth device {self._device_label(path)} removed")
        self.state.interfaces_removed(path, interfaces)

    def _on_bluez_owner_changed(self, old_owner: str, new_owner: str) -> None:
        if not new_owner:
            self.state.bluez_lost()
            self.logger.warning(
                "bluetoothd went away - Bluetooth is unavailable until it comes back "
                "(registered services and the pairing agent are lost with it)"
            )
        else:
            self.logger.info("bluetoothd is available again")
            task = asyncio.create_task(self._reload_state())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _reload_state(self) -> None:
        try:
            await self._load_state()
        except Exception:
            self.logger.warning("Couldn't reload the Bluetooth state after bluetoothd came back", exc_info=True)
