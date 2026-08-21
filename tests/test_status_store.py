from api.models.scene_status import SceneStatus
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
