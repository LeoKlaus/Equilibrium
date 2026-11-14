from api.models.scene import SceneWithRelationships
from api.models.scene_status import SceneStatus
from api.models.websocket_responses import BleDevice
from hub.status_store import StatusStore


async def test_set_device_state_notifies_and_powering_off_clears_input():
    store = StatusStore()
    notifications = []

    async def callback(status):
        notifications.append(status)

    store.set_callback(callback)

    await store.set_device_state(1, new_power_state=True, new_input=42)
    state = store.status.devices.state(for_device_id=1)
    assert state.powered is True
    assert state.input == 42
    assert len(notifications) == 1

    await store.set_device_state(1, new_power_state=False)
    assert store.status.devices.state(for_device_id=1).input is None
    assert len(notifications) == 2


async def test_set_scene_status_notifies():
    store = StatusStore()
    notifications = []

    async def callback(status):
        notifications.append(status.scene_status)

    store.set_callback(callback)
    await store.set_scene_status(SceneStatus.STARTING)

    assert store.status.scene_status == SceneStatus.STARTING
    assert notifications == [SceneStatus.STARTING]


async def test_set_scene_updates_scene_and_status_together():
    store = StatusStore()

    await store.set_scene(scene=None, status=SceneStatus.ACTIVE)

    assert store.status.current_scene is None
    assert store.status.scene_status == SceneStatus.ACTIVE


async def test_no_callback_is_a_safe_no_op():
    store = StatusStore()
    await store.set_scene_status(SceneStatus.ACTIVE)
    assert store.status.scene_status == SceneStatus.ACTIVE


def _resolver(address: str) -> BleDevice:
    return BleDevice(name="Apple TV", address=address.upper(), connected=True, paired=True)


def _scene(address: str | None) -> SceneWithRelationships:
    return SceneWithRelationships(id=1, name="Movie", bluetooth_address=address)


async def test_set_scene_resolves_the_scenes_bluetooth_device():
    store = StatusStore(bluetooth_device_resolver=_resolver)

    await store.set_scene(_scene("aa:bb:cc:dd:ee:ff"), SceneStatus.ACTIVE)

    assert store.status.bluetooth_device == _resolver("AA:BB:CC:DD:EE:FF")


async def test_bluetooth_device_is_none_for_a_scene_without_an_address():
    store = StatusStore(bluetooth_device_resolver=_resolver)

    await store.set_scene(_scene(None), SceneStatus.ACTIVE)

    assert store.status.bluetooth_device is None


async def test_bluetooth_device_is_cleared_when_the_scene_stops():
    store = StatusStore(bluetooth_device_resolver=_resolver)
    await store.set_scene(_scene("AA:BB:CC:DD:EE:FF"), SceneStatus.ACTIVE)

    await store.set_scene(None, None)

    assert store.status.bluetooth_device is None


async def test_bluetooth_device_is_none_without_a_resolver():
    store = StatusStore()

    await store.set_scene(_scene("AA:BB:CC:DD:EE:FF"), SceneStatus.ACTIVE)

    assert store.status.bluetooth_device is None


async def test_refresh_bluetooth_device_rereads_and_notifies():
    current = BleDevice(address="AA:BB:CC:DD:EE:FF")
    store = StatusStore(bluetooth_device_resolver=lambda address: current)
    await store.set_scene(_scene("AA:BB:CC:DD:EE:FF"), SceneStatus.ACTIVE)
    notifications = []

    async def callback(status):
        notifications.append(status.bluetooth_device)

    store.set_callback(callback)
    current = BleDevice(address="AA:BB:CC:DD:EE:FF", connected=True)

    await store.refresh_bluetooth_device()

    assert notifications == [current]


async def test_refresh_bluetooth_device_without_a_scene_leaves_it_empty():
    store = StatusStore(bluetooth_device_resolver=_resolver)

    await store.refresh_bluetooth_device()

    assert store.status.bluetooth_device is None
