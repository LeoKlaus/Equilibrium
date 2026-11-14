import asyncio
import logging
from typing import Any

import pytest
from dbus_fast import Message, Variant

from ble_keyboard.bluez_monitor import BluezMonitor

ADAPTER = "/org/bluez/hci0"
DEVICE = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"


class FakeBus:
    """Stands in for dbus_fast's MessageBus: records handlers and D-Bus calls."""

    def __init__(self, managed_objects: dict[str, Any] | None = None, fail_on: str | None = None):
        self.handlers: list[Any] = []
        self.calls: list[tuple[str | None, list[Any]]] = []
        self._managed_objects = managed_objects or {}
        self._fail_on = fail_on

    def add_message_handler(self, handler):
        self.handlers.append(handler)

    def remove_message_handler(self, handler):
        if handler in self.handlers:
            self.handlers.remove(handler)

    async def call(self, message: Message):
        message.serial = 1
        self.calls.append((message.member, message.body))
        if message.member == self._fail_on:
            return Message.new_error(message, "org.freedesktop.DBus.Error.Failed", "nope")
        if message.member == "GetManagedObjects":
            return Message.new_method_return(message, "a{oa{sa{sv}}}", [self._managed_objects])
        return Message.new_method_return(message)


def _properties_changed(path: str, interface: str, changed: dict[str, Any]) -> Message:
    return Message.new_signal(
        path,
        "org.freedesktop.DBus.Properties",
        "PropertiesChanged",
        "sa{sv}as",
        [interface, {name: _variant(value) for name, value in changed.items()}, []],
    )


def _variant(value: Any) -> Variant:
    if isinstance(value, bool):
        return Variant("b", value)
    if isinstance(value, int):
        return Variant("n", value)
    return Variant("s", value)


def _interfaces_added(path: str, interfaces: dict[str, dict[str, Any]]) -> Message:
    return Message.new_signal(
        "/",
        "org.freedesktop.DBus.ObjectManager",
        "InterfacesAdded",
        "oa{sa{sv}}",
        [path, {name: {k: _variant(v) for k, v in props.items()} for name, props in interfaces.items()}],
    )


def _interfaces_removed(path: str, interfaces: list[str]) -> Message:
    return Message.new_signal(
        "/", "org.freedesktop.DBus.ObjectManager", "InterfacesRemoved", "oas", [path, interfaces]
    )


def _name_owner_changed(name: str, old: str, new: str) -> Message:
    return Message.new_signal(
        "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameOwnerChanged", "sss", [name, old, new]
    )


def _monitor() -> BluezMonitor:
    return BluezMonitor(FakeBus())  # type: ignore[arg-type]  # duck-typed test double


@pytest.fixture(autouse=True)
def debug_logging(caplog):
    caplog.set_level(logging.DEBUG, logger="ble_keyboard")


async def _finish_tasks(monitor: BluezMonitor) -> None:
    await asyncio.gather(*monitor._tasks)


def _records(caplog) -> list[tuple[str, str]]:
    return [(record.levelname, record.getMessage()) for record in caplog.records]


# --- device events ---

def test_device_connect_and_disconnect_are_logged_at_info(caplog):
    monitor = _monitor()

    monitor._on_message(_properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True}))
    monitor._on_message(_properties_changed(DEVICE, "org.bluez.Device1", {"Connected": False}))

    assert _records(caplog) == [
        ("INFO", "Bluetooth device AA:BB:CC:DD:EE:FF connected"),
        ("INFO", "Bluetooth device AA:BB:CC:DD:EE:FF disconnected"),
    ]


def test_pairing_changes_are_logged_at_info(caplog):
    monitor = _monitor()

    monitor._on_message(_properties_changed(DEVICE, "org.bluez.Device1", {"Paired": True, "Bonded": True}))
    monitor._on_message(_properties_changed(DEVICE, "org.bluez.Device1", {"Paired": False}))

    assert _records(caplog) == [
        ("INFO", "Bluetooth device AA:BB:CC:DD:EE:FF bonded"),
        ("INFO", "Bluetooth device AA:BB:CC:DD:EE:FF paired"),
        ("INFO", "Bluetooth device AA:BB:CC:DD:EE:FF unpaired"),
    ]


def test_other_device_properties_are_logged_at_debug(caplog):
    monitor = _monitor()

    monitor._on_message(_properties_changed(DEVICE, "org.bluez.Device1", {"Trusted": True, "ServicesResolved": True}))

    assert _records(caplog) == [
        ("DEBUG", "Bluetooth device AA:BB:CC:DD:EE:FF: ServicesResolved = True"),
        ("DEBUG", "Bluetooth device AA:BB:CC:DD:EE:FF: Trusted = True"),
    ]


def test_noisy_device_properties_are_not_logged(caplog):
    monitor = _monitor()

    monitor._on_message(_properties_changed(DEVICE, "org.bluez.Device1", {"RSSI": -60, "TxPower": 4}))

    assert _records(caplog) == []


def test_the_device_name_comes_from_the_alias_it_was_added_with(caplog):
    monitor = _monitor()
    monitor._on_message(_interfaces_added(DEVICE, {"org.bluez.Device1": {"Alias": "Apple TV"}}))
    caplog.clear()

    monitor._on_message(_properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True}))

    assert _records(caplog) == [("INFO", "Bluetooth device AA:BB:CC:DD:EE:FF (Apple TV) connected")]


def test_an_alias_change_updates_the_name_used_afterwards(caplog):
    monitor = _monitor()
    monitor._on_message(_interfaces_added(DEVICE, {"org.bluez.Device1": {"Alias": "Apple TV"}}))
    monitor._on_message(_properties_changed(DEVICE, "org.bluez.Device1", {"Alias": "Living room"}))
    caplog.clear()

    monitor._on_message(_properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True}))

    assert _records(caplog) == [("INFO", "Bluetooth device AA:BB:CC:DD:EE:FF (Living room) connected")]


def test_device_added_and_removed_are_logged_at_debug_and_forget_the_name(caplog):
    monitor = _monitor()

    monitor._on_message(_interfaces_added(DEVICE, {"org.bluez.Device1": {"Alias": "Apple TV"}}))
    monitor._on_message(_interfaces_removed(DEVICE, ["org.bluez.Device1"]))
    monitor._on_message(_properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True}))

    assert _records(caplog) == [
        ("DEBUG", "Bluetooth device AA:BB:CC:DD:EE:FF (Apple TV) added"),
        ("DEBUG", "Bluetooth device AA:BB:CC:DD:EE:FF (Apple TV) removed"),
        ("INFO", "Bluetooth device AA:BB:CC:DD:EE:FF connected"),
    ]


def test_other_interfaces_added_or_removed_are_ignored(caplog):
    monitor = _monitor()

    monitor._on_message(_interfaces_added(DEVICE + "/service0001", {"org.bluez.GattService1": {"Primary": True}}))
    monitor._on_message(_interfaces_removed(DEVICE + "/service0001", ["org.bluez.GattService1"]))

    assert _records(caplog) == []


# --- adapter events ---

def test_adapter_power_is_logged_at_info_the_rest_at_debug(caplog):
    monitor = _monitor()

    monitor._on_message(
        _properties_changed(ADAPTER, "org.bluez.Adapter1", {"PowerState": "off", "Powered": False, "Class": 0})
    )
    monitor._on_message(_properties_changed(ADAPTER, "org.bluez.Adapter1", {"Discoverable": True}))

    assert _records(caplog) == [
        ("DEBUG", "Bluetooth adapter PowerState = off"),
        ("INFO", "Bluetooth adapter Powered = False"),
        ("DEBUG", "Bluetooth adapter Discoverable = True"),
    ]


def test_advertising_changes_are_logged_at_debug_without_the_free_slot_count(caplog):
    monitor = _monitor()

    monitor._on_message(
        _properties_changed(ADAPTER, "org.bluez.LEAdvertisingManager1", {"ActiveInstances": 1, "SupportedInstances": 4})
    )

    assert _records(caplog) == [("DEBUG", "Bluetooth advertising: ActiveInstances = 1")]


# --- bluetoothd coming and going ---

def test_bluetoothd_disappearing_is_a_warning_and_forgets_device_names(caplog):
    monitor = _monitor()
    monitor._on_message(_interfaces_added(DEVICE, {"org.bluez.Device1": {"Alias": "Apple TV"}}))
    caplog.clear()

    monitor._on_message(_name_owner_changed("org.bluez", ":1.42", ""))

    assert [level for level, _ in _records(caplog)] == ["WARNING"]
    assert "bluetoothd went away" in caplog.records[0].getMessage()
    assert monitor.state.snapshot.devices == {}


async def test_bluetoothd_coming_back_is_logged_at_info(caplog):
    monitor = _monitor()

    monitor._on_message(_name_owner_changed("org.bluez", "", ":1.57"))

    assert ("INFO", "bluetoothd is available again") in _records(caplog)
    await _finish_tasks(monitor)


def test_other_bus_names_changing_owner_are_ignored(caplog):
    monitor = _monitor()

    monitor._on_message(_name_owner_changed("org.example.Other", "", ":1.9"))

    assert _records(caplog) == []


# --- robustness ---

def test_properties_changed_outside_org_bluez_is_ignored(caplog):
    monitor = _monitor()

    # e.g. one of our own exported GATT services
    monitor._on_message(
        _properties_changed("/me/wehrfritz/bluez_peripheral/service_hid", "org.bluez.Device1", {"Connected": True})
    )

    assert _records(caplog) == []


def test_non_signal_messages_are_ignored(caplog):
    monitor = _monitor()
    call = Message(
        destination="org.example", path="/", interface="org.example.I", member="PropertiesChanged"
    )

    monitor._on_message(call)

    assert _records(caplog) == []


def test_a_malformed_signal_is_logged_and_does_not_raise(caplog):
    monitor = _monitor()
    broken = Message.new_signal(
        DEVICE, "org.freedesktop.DBus.Properties", "PropertiesChanged", "s", ["only one argument"]
    )

    monitor._on_message(broken)

    assert [level for level, _ in _records(caplog)] == ["ERROR"]


# --- lifecycle ---

async def test_start_subscribes_to_bluez_signals_and_stop_unsubscribes():
    bus = FakeBus()
    monitor = BluezMonitor(bus)  # type: ignore[arg-type]

    await monitor.start()

    assert bus.handlers == [monitor._on_message]
    added = [body[0] for member, body in bus.calls if member == "AddMatch"]
    assert len(added) == 3
    assert any("path_namespace='/org/bluez'" in rule and "PropertiesChanged" in rule for rule in added)
    assert any("ObjectManager" in rule for rule in added)
    assert any("NameOwnerChanged" in rule and "arg0='org.bluez'" in rule for rule in added)

    await monitor.stop()

    assert bus.handlers == []
    assert [body[0] for member, body in bus.calls if member == "RemoveMatch"] == added


async def test_start_remembers_the_names_of_devices_bluez_already_knows(caplog):
    bus = FakeBus(
        managed_objects={
            ADAPTER: {"org.bluez.Adapter1": {"Powered": Variant("b", True), "Discoverable": Variant("b", False)}},
            DEVICE: {"org.bluez.Device1": {"Alias": Variant("s", "Apple TV")}},
        }
    )
    monitor = BluezMonitor(bus)  # type: ignore[arg-type]

    await monitor.start()
    caplog.clear()
    monitor._on_message(_properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True}))

    assert _records(caplog) == [("INFO", "Bluetooth device AA:BB:CC:DD:EE:FF (Apple TV) connected")]


async def test_start_never_calls_into_a_device():
    bus = FakeBus()
    monitor = BluezMonitor(bus)  # type: ignore[arg-type]

    await monitor.start()

    # Listing devices over D-Bus is fine; touching one (Pair, Connect, ...) can trigger pairing
    assert {member for member, _ in bus.calls} <= {"AddMatch", "GetManagedObjects"}


async def test_start_failure_cleans_up_and_raises():
    bus = FakeBus(fail_on="AddMatch")
    monitor = BluezMonitor(bus)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="AddMatch failed"):
        await monitor.start()

    assert bus.handlers == []


async def test_start_without_bluez_running_only_warns(caplog):
    bus = FakeBus(fail_on="GetManagedObjects")
    monitor = BluezMonitor(bus)  # type: ignore[arg-type]

    await monitor.start()

    assert bus.handlers == [monitor._on_message]  # still listening for bluetoothd appearing
    assert ("WARNING", "Bluetooth monitor: BlueZ isn't available right now") in _records(caplog)


async def test_stop_tolerates_a_bus_that_is_already_gone():
    class DeadBus(FakeBus):
        async def call(self, message):
            if message.member == "RemoveMatch":
                raise ConnectionError("bus disconnected")
            return await super().call(message)

    monitor = BluezMonitor(DeadBus())  # type: ignore[arg-type]
    await monitor.start()

    await monitor.stop()  # must not raise


# --- keeping the state up to date ---

def test_signals_update_the_state():
    monitor = _monitor()
    monitor._on_message(_interfaces_added(ADAPTER, {"org.bluez.Adapter1": {"Powered": True}}))
    monitor._on_message(_interfaces_added(DEVICE, {"org.bluez.Device1": {"Alias": "Apple TV"}}))

    monitor._on_message(_properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True, "Paired": True}))
    monitor._on_message(_properties_changed(ADAPTER, "org.bluez.LEAdvertisingManager1", {"ActiveInstances": 1}))

    snapshot = monitor.state.snapshot
    assert snapshot.devices["AA:BB:CC:DD:EE:FF"].connected is True
    assert snapshot.devices["AA:BB:CC:DD:EE:FF"].paired is True
    assert snapshot.devices["AA:BB:CC:DD:EE:FF"].name == "Apple TV"
    assert snapshot.adapter is not None and snapshot.adapter.advertising is True


def test_a_removed_device_leaves_the_state():
    monitor = _monitor()
    monitor._on_message(_interfaces_added(DEVICE, {"org.bluez.Device1": {"Alias": "Apple TV"}}))

    monitor._on_message(_interfaces_removed(DEVICE, ["org.bluez.Device1"]))

    assert monitor.state.snapshot.devices == {}


def test_bluetoothd_disappearing_marks_bluez_unavailable_in_the_state():
    monitor = _monitor()
    monitor.state.load({ADAPTER: {"org.bluez.Adapter1": {"Powered": True}}})

    monitor._on_message(_name_owner_changed("org.bluez", ":1.42", ""))

    assert monitor.state.bluez_available is False
    assert monitor.state.adapter is None


async def test_start_loads_the_current_state():
    bus = FakeBus(
        managed_objects={
            ADAPTER: {"org.bluez.Adapter1": {"Powered": Variant("b", True), "Pairable": Variant("b", True)}},
            DEVICE: {
                "org.bluez.Device1": {
                    "Alias": Variant("s", "Apple TV"),
                    "Connected": Variant("b", True),
                    "Paired": Variant("b", True),
                }
            },
        }
    )
    monitor = BluezMonitor(bus)  # type: ignore[arg-type]

    await monitor.start()

    snapshot = monitor.state.snapshot
    assert snapshot.bluez_available is True
    assert snapshot.adapter is not None and snapshot.adapter.powered and snapshot.adapter.pairable
    assert snapshot.devices["AA:BB:CC:DD:EE:FF"].connected is True


async def test_start_without_bluez_running_leaves_the_state_unavailable():
    bus = FakeBus(fail_on="GetManagedObjects")
    monitor = BluezMonitor(bus)  # type: ignore[arg-type]

    await monitor.start()

    assert monitor.state.bluez_available is False


async def test_the_state_is_reloaded_when_bluetoothd_comes_back():
    bus = FakeBus(
        managed_objects={
            ADAPTER: {"org.bluez.Adapter1": {"Powered": Variant("b", True)}},
            DEVICE: {"org.bluez.Device1": {"Alias": Variant("s", "Apple TV"), "Paired": Variant("b", True)}},
        }
    )
    monitor = BluezMonitor(bus)  # type: ignore[arg-type]
    await monitor.start()
    monitor._on_message(_name_owner_changed("org.bluez", ":1.42", ""))
    assert monitor.state.snapshot.devices == {}

    monitor._on_message(_name_owner_changed("org.bluez", "", ":1.57"))
    await _finish_tasks(monitor)

    assert monitor.state.bluez_available is True
    assert monitor.state.snapshot.devices["AA:BB:CC:DD:EE:FF"].paired is True


async def test_a_failing_reload_is_logged_and_does_not_raise(caplog):
    bus = FakeBus()
    monitor = BluezMonitor(bus)  # type: ignore[arg-type]
    await monitor.start()

    async def broken_call(message):
        raise ConnectionError("bus gone")

    bus.call = broken_call  # type: ignore[method-assign]
    monitor._on_message(_name_owner_changed("org.bluez", "", ":1.57"))
    await _finish_tasks(monitor)

    assert "Couldn't reload the Bluetooth state" in caplog.text


async def test_stop_cancels_a_pending_reload():
    bus = FakeBus()
    monitor = BluezMonitor(bus)  # type: ignore[arg-type]
    await monitor.start()
    monitor._on_message(_name_owner_changed("org.bluez", "", ":1.57"))
    (task,) = monitor._tasks

    await monitor.stop()
    await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()


def test_the_monitor_uses_the_state_it_is_given():
    from ble_keyboard.bluetooth_state import BluetoothState

    state = BluetoothState()

    monitor = BluezMonitor(FakeBus(), state)  # type: ignore[arg-type]

    assert monitor.state is state
