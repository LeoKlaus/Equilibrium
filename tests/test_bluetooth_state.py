import pytest

from ble_keyboard.bluetooth_state import (
    AdapterChanged,
    AdapterState,
    AvailabilityChanged,
    BluetoothState,
    DeviceChanged,
    DeviceState,
    StateChange,
    address_from_path,
    normalize_address,
)

ADAPTER = "/org/bluez/hci0"
DEVICE = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
OTHER_DEVICE = "/org/bluez/hci0/dev_11_22_33_44_55_66"
ADDRESS = "AA:BB:CC:DD:EE:FF"


def _state_with_listener() -> tuple[BluetoothState, list[StateChange]]:
    state = BluetoothState()
    changes: list[StateChange] = []
    state.add_listener(changes.append)
    return state, changes


def _loaded(**kwargs) -> BluetoothState:
    state = BluetoothState()
    state.load(
        {
            ADAPTER: {
                "org.bluez.Adapter1": {"Powered": True, "Discoverable": False, "Pairable": False},
                "org.bluez.LEAdvertisingManager1": {"ActiveInstances": 0},
            },
            DEVICE: {"org.bluez.Device1": {"Alias": "Apple TV", "Connected": False, "Paired": True, **kwargs}},
        }
    )
    return state


# --- addresses ---

@pytest.mark.parametrize("typed", ["aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", " aa:bb:cc:dd:ee:ff ", ADDRESS])
def test_addresses_are_normalized(typed):
    assert normalize_address(typed) == ADDRESS


def test_the_address_is_read_from_the_object_path():
    assert address_from_path(DEVICE) == ADDRESS


# --- loading ---

def test_nothing_is_known_before_anything_is_loaded():
    state = BluetoothState()

    assert state.bluez_available is False
    assert state.adapter is None
    assert state.snapshot.devices == {}


def test_load_fills_the_state():
    state = _loaded()

    assert state.bluez_available is True
    assert state.adapter == AdapterState(powered=True, discoverable=False, pairable=False, advertising=False)
    assert state.snapshot.devices == {ADDRESS: DeviceState(ADDRESS, name="Apple TV", connected=False, paired=True)}


def test_load_tells_listeners_what_is_new():
    state, changes = _state_with_listener()

    state.load(
        {
            ADAPTER: {"org.bluez.Adapter1": {"Powered": True}},
            DEVICE: {"org.bluez.Device1": {"Alias": "Apple TV", "Paired": True}},
        }
    )

    assert changes == [
        DeviceChanged(ADDRESS, DeviceState(ADDRESS, "Apple TV", connected=False, paired=True)),
        AdapterChanged(AdapterState(powered=True)),
        AvailabilityChanged(True),
    ]


def test_reloading_the_same_state_tells_nobody():
    state = _loaded()
    changes: list[StateChange] = []
    state.add_listener(changes.append)

    state.load(
        {
            ADAPTER: {"org.bluez.Adapter1": {"Powered": True, "Discoverable": False, "Pairable": False}},
            DEVICE: {"org.bluez.Device1": {"Alias": "Apple TV", "Connected": False, "Paired": True}},
        }
    )

    assert changes == []


def test_reloading_only_reports_the_difference():
    state = _loaded()
    changes: list[StateChange] = []
    state.add_listener(changes.append)

    state.load(
        {
            ADAPTER: {"org.bluez.Adapter1": {"Powered": True, "Discoverable": False, "Pairable": False}},
            OTHER_DEVICE: {"org.bluez.Device1": {"Alias": "Speaker"}},
        }
    )

    assert changes == [
        DeviceChanged("11:22:33:44:55:66", DeviceState("11:22:33:44:55:66", name="Speaker")),
        DeviceChanged(ADDRESS, None),
    ]


# --- devices ---

def test_a_device_connecting_updates_it_and_is_reported():
    state = _loaded()
    changes: list[StateChange] = []
    state.add_listener(changes.append)

    state.properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True})

    assert state.device(ADDRESS) == DeviceState(ADDRESS, "Apple TV", connected=True, paired=True)
    assert changes == [DeviceChanged(ADDRESS, DeviceState(ADDRESS, "Apple TV", connected=True, paired=True))]


def test_a_repeated_value_is_not_a_change():
    state = _loaded(Connected=True)
    changes: list[StateChange] = []
    state.add_listener(changes.append)

    state.properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True})

    assert changes == []


def test_untracked_device_properties_are_not_changes():
    state = _loaded()
    changes: list[StateChange] = []
    state.add_listener(changes.append)

    state.properties_changed(DEVICE, "org.bluez.Device1", {"RSSI": -60, "Trusted": True})

    assert changes == []


def test_an_alias_change_is_a_device_change():
    state = _loaded()
    changes: list[StateChange] = []
    state.add_listener(changes.append)

    state.properties_changed(DEVICE, "org.bluez.Device1", {"Alias": "Living room"})

    assert state.device(ADDRESS).name == "Living room"  # type: ignore[union-attr]
    assert len(changes) == 1


def test_changes_for_an_unknown_device_are_ignored():
    state, changes = _state_with_listener()

    state.properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True})

    assert state.snapshot.devices == {}
    assert changes == []


def test_a_new_device_is_added_with_what_bluez_announces():
    state, changes = _state_with_listener()

    state.interfaces_added(DEVICE, {"org.bluez.Device1": {"Alias": "Apple TV", "Connected": True}})

    assert state.device(ADDRESS) == DeviceState(ADDRESS, "Apple TV", connected=True, paired=False)
    assert changes == [DeviceChanged(ADDRESS, DeviceState(ADDRESS, "Apple TV", connected=True))]


def test_a_forgotten_device_is_removed_and_reported():
    state = _loaded()
    changes: list[StateChange] = []
    state.add_listener(changes.append)

    state.interfaces_removed(DEVICE, ["org.bluez.Device1"])

    assert state.device(ADDRESS) is None
    assert changes == [DeviceChanged(ADDRESS, None)]


def test_removing_other_interfaces_leaves_the_device_alone():
    state = _loaded()
    changes: list[StateChange] = []
    state.add_listener(changes.append)

    state.interfaces_removed(DEVICE, ["org.bluez.Battery1"])

    assert state.device(ADDRESS) is not None
    assert changes == []


def test_a_device_is_found_by_an_address_in_any_format():
    state = _loaded()

    assert state.device("aa:bb:cc:dd:ee:ff") is state.device(ADDRESS)
    assert state.device("AA-BB-CC-DD-EE-FF") is state.device(ADDRESS)
    assert state.device("11:22:33:44:55:66") is None


def test_a_device_is_found_by_its_path():
    state = _loaded()

    assert state.device_at(DEVICE) == state.device(ADDRESS)
    assert state.device_at(OTHER_DEVICE) is None


def test_the_name_falls_back_to_the_bluetooth_name():
    state = BluetoothState()

    state.interfaces_added(DEVICE, {"org.bluez.Device1": {"Name": "TV"}})

    assert state.device(ADDRESS).name == "TV"  # type: ignore[union-attr]


# --- adapter ---

def test_adapter_power_changes_are_reported():
    state = _loaded()
    changes: list[StateChange] = []
    state.add_listener(changes.append)

    state.properties_changed(ADAPTER, "org.bluez.Adapter1", {"Powered": False})

    assert state.adapter == AdapterState(powered=False)
    assert changes == [AdapterChanged(AdapterState(powered=False))]


def test_advertising_follows_the_number_of_active_instances():
    state = _loaded()

    state.properties_changed(ADAPTER, "org.bluez.LEAdvertisingManager1", {"ActiveInstances": 2})
    assert state.adapter.advertising is True  # type: ignore[union-attr]

    state.properties_changed(ADAPTER, "org.bluez.LEAdvertisingManager1", {"ActiveInstances": 0})
    assert state.adapter.advertising is False  # type: ignore[union-attr]


def test_the_free_advertising_slots_are_not_tracked():
    state = _loaded()
    changes: list[StateChange] = []
    state.add_listener(changes.append)

    state.properties_changed(ADAPTER, "org.bluez.LEAdvertisingManager1", {"SupportedInstances": 4})

    assert changes == []


def test_untracked_adapter_properties_are_not_changes():
    state = _loaded()
    changes: list[StateChange] = []
    state.add_listener(changes.append)

    state.properties_changed(ADAPTER, "org.bluez.Adapter1", {"Class": 4194304, "PowerState": "on"})

    assert changes == []


def test_changes_for_an_unknown_adapter_are_ignored():
    state, changes = _state_with_listener()

    state.properties_changed(ADAPTER, "org.bluez.Adapter1", {"Powered": True})

    assert state.adapter is None
    assert changes == []


def test_a_new_adapter_is_added_from_its_announcement():
    state, changes = _state_with_listener()

    state.interfaces_added(
        ADAPTER,
        {"org.bluez.Adapter1": {"Powered": True}, "org.bluez.LEAdvertisingManager1": {"ActiveInstances": 0}},
    )

    assert state.adapter == AdapterState(powered=True)
    assert changes == [AdapterChanged(AdapterState(powered=True))]


def test_the_first_adapter_is_the_one_tracked():
    state = BluetoothState()
    state.interfaces_added("/org/bluez/hci1", {"org.bluez.Adapter1": {"Powered": False}})
    state.interfaces_added("/org/bluez/hci0", {"org.bluez.Adapter1": {"Powered": True}})

    assert state.adapter == AdapterState(powered=True)


def test_a_change_on_a_second_adapter_is_not_reported():
    state = BluetoothState()
    state.interfaces_added("/org/bluez/hci0", {"org.bluez.Adapter1": {"Powered": True}})
    state.interfaces_added("/org/bluez/hci1", {"org.bluez.Adapter1": {"Powered": True}})
    changes: list[StateChange] = []
    state.add_listener(changes.append)

    state.properties_changed("/org/bluez/hci1", "org.bluez.Adapter1", {"Powered": False})

    assert changes == []


def test_a_removed_adapter_is_reported():
    state = _loaded()
    changes: list[StateChange] = []
    state.add_listener(changes.append)

    state.interfaces_removed(ADAPTER, ["org.bluez.Adapter1"])

    assert state.adapter is None
    assert changes == [AdapterChanged(None)]


# --- bluetoothd going away ---

def test_losing_bluez_clears_everything_and_reports_it():
    state = _loaded()
    changes: list[StateChange] = []
    state.add_listener(changes.append)

    state.bluez_lost()

    assert state.bluez_available is False
    assert state.adapter is None
    assert state.snapshot.devices == {}
    assert changes == [DeviceChanged(ADDRESS, None), AdapterChanged(None), AvailabilityChanged(False)]


def test_losing_bluez_twice_only_reports_once():
    state = _loaded()
    state.bluez_lost()
    changes: list[StateChange] = []
    state.add_listener(changes.append)

    state.bluez_lost()

    assert changes == []


# --- snapshot and listeners ---

def test_a_snapshot_is_not_affected_by_later_changes():
    state = _loaded()
    snapshot = state.snapshot

    state.properties_changed(DEVICE, "org.bluez.Device1", {"Connected": True})

    assert snapshot.devices[ADDRESS].connected is False
    assert state.snapshot.devices[ADDRESS].connected is True


def test_a_snapshot_cannot_be_modified():
    snapshot = _loaded().snapshot

    with pytest.raises(TypeError):
        snapshot.devices["11:22:33:44:55:66"] = DeviceState("11:22:33:44:55:66")  # type: ignore[index]


def test_listeners_see_a_consistent_state():
    state = _loaded()
    seen: list[tuple[bool, int]] = []
    state.add_listener(lambda change: seen.append((state.bluez_available, len(state.snapshot.devices))))

    state.bluez_lost()

    # Every notification of a single update sees the final state: unavailable, no devices
    assert seen == [(False, 0)] * 3


def test_a_listener_can_be_removed():
    state, changes = _state_with_listener()
    state.remove_listener(changes.append)

    state.interfaces_added(DEVICE, {"org.bluez.Device1": {}})

    assert changes == []


def test_a_failing_listener_neither_stops_the_others_nor_the_update(caplog):
    state = BluetoothState()
    received: list[StateChange] = []

    def broken(change: StateChange) -> None:
        raise RuntimeError("listener bug")

    state.add_listener(broken)
    state.add_listener(received.append)

    state.interfaces_added(DEVICE, {"org.bluez.Device1": {"Connected": True}})

    assert len(received) == 1
    assert state.device(ADDRESS) is not None
    assert "A Bluetooth state listener raised" in caplog.text


def test_device_path_finds_a_device_by_any_spelling_of_its_address():
    state = _loaded()

    assert state.device_path("aa-bb-cc-dd-ee-ff") == DEVICE
    assert state.device_path("11:22:33:44:55:66") is None
