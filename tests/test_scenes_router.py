from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.dependencies import get_keymap_resolver, get_scene_manager
from api.models.device import Device
from api.models.macro import Macro
from api.models.scene import Scene
from api.models.user_image import UserImage
from api.routers import scenes
from db_manager.db_manager import get_session
from hub.scene_manager import NoActiveSceneError, SceneNotFoundError


class FakeSceneManager:
    def __init__(self):
        self.started = []
        self.set_current_calls = []
        self.stopped = 0
        self.start_scene_exception = None
        self.set_current_scene_exception = None
        self.stop_current_scene_exception = None

    async def start_scene(self, scene_id: int) -> None:
        if self.start_scene_exception is not None:
            raise self.start_scene_exception
        self.started.append(scene_id)

    async def set_current_scene(self, scene_id: int) -> None:
        if self.set_current_scene_exception is not None:
            raise self.set_current_scene_exception
        self.set_current_calls.append(scene_id)

    async def stop_current_scene(self) -> None:
        if self.stop_current_scene_exception is not None:
            raise self.stop_current_scene_exception
        self.stopped += 1


class FakeKeymapResolver:
    def __init__(self, suggestion=None):
        self.suggestion = suggestion if suggestion is not None else {}
        self.suggest_keymap_calls = []

    def suggest_keymap(self, scene):
        self.suggest_keymap_calls.append(scene)
        return self.suggestion


def _client_for(db_engine, scene_manager=None, keymap_resolver=None) -> TestClient:
    app = FastAPI()
    app.include_router(scenes.router)
    app.dependency_overrides[get_session] = lambda: Session(db_engine)
    if scene_manager is not None:
        app.dependency_overrides[get_scene_manager] = lambda: scene_manager
    if keymap_resolver is not None:
        app.dependency_overrides[get_keymap_resolver] = lambda: keymap_resolver
    return TestClient(app)


def _create_device(db_engine, **overrides) -> int:
    defaults = {"name": "TV"}
    defaults.update(overrides)
    with Session(db_engine) as session:
        device = Device(**defaults)
        session.add(device)
        session.commit()
        session.refresh(device)
        assert device.id is not None
        return device.id


def _create_macro(db_engine, device_ids=None, **overrides) -> int:
    defaults = {"name": "My Macro", "command_ids": [], "delays": []}
    defaults.update(overrides)
    with Session(db_engine) as session:
        macro = Macro(**defaults)
        if device_ids:
            devices = []
            for did in device_ids:
                device = session.get(Device, did)
                assert device is not None
                devices.append(device)
            macro.devices = devices
        session.add(macro)
        session.commit()
        session.refresh(macro)
        assert macro.id is not None
        return macro.id


def _create_image(db_engine, **overrides) -> int:
    defaults = {"filename": "cover.png", "path": "config/images/cover.png"}
    defaults.update(overrides)
    with Session(db_engine) as session:
        image = UserImage(**defaults)
        session.add(image)
        session.commit()
        session.refresh(image)
        assert image.id is not None
        return image.id


def _create_scene(db_engine, **overrides) -> int:
    defaults = {"name": "Movie Night"}
    defaults.update(overrides)
    with Session(db_engine) as session:
        scene = Scene(**defaults)
        session.add(scene)
        session.commit()
        session.refresh(scene)
        assert scene.id is not None
        return scene.id


def test_create_scene_happy_minimal(db_engine):
    client = _client_for(db_engine)

    response = client.post("/scenes/", json={"name": "Movie Night"})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Movie Night"
    assert body["devices"] == []
    assert body["macros"] == []


def test_create_scene_with_valid_macro_ids_pulls_in_their_devices(db_engine):
    device_id = _create_device(db_engine)
    start_macro_id = _create_macro(db_engine, device_ids=[device_id])
    client = _client_for(db_engine)

    response = client.post("/scenes/", json={"name": "Movie Night", "start_macro_id": start_macro_id})

    assert response.status_code == 200
    body = response.json()
    assert body["start_macro"]["id"] == start_macro_id
    assert [d["id"] for d in body["devices"]] == [device_id]


def test_create_scene_with_invalid_start_macro_id_returns_400(db_engine):
    client = _client_for(db_engine)

    response = client.post("/scenes/", json={"name": "Movie Night", "start_macro_id": 999})

    assert response.status_code == 400
    assert response.json() == {"detail": "Macro 999 not found"}


def test_create_scene_with_invalid_stop_macro_id_returns_400(db_engine):
    # Pre-existing bug, asserted as-is rather than fixed here: this branch's
    # error message interpolates start_macro_id instead of stop_macro_id.
    client = _client_for(db_engine)

    response = client.post("/scenes/", json={"name": "Movie Night", "stop_macro_id": 999})

    assert response.status_code == 400
    assert response.json() == {"detail": "Macro None not found"}


def test_create_scene_with_invalid_image_id_returns_404(db_engine):
    client = _client_for(db_engine)

    response = client.post("/scenes/", json={"name": "Movie Night", "image_id": 999})

    assert response.status_code == 404
    assert response.json() == {"detail": "Image 999 not found"}


def test_create_scene_with_invalid_device_id_returns_404(db_engine):
    client = _client_for(db_engine)

    response = client.post("/scenes/", json={"name": "Movie Night", "device_ids": [999]})

    assert response.status_code == 404
    assert response.json() == {"detail": "Device 999 not found"}


def test_create_scene_with_invalid_macro_id_returns_404(db_engine):
    client = _client_for(db_engine)

    response = client.post("/scenes/", json={"name": "Movie Night", "macro_ids": [999]})

    assert response.status_code == 404
    assert response.json() == {"detail": "Macro 999 not found"}


def test_create_scene_with_matching_bluetooth_address_auto_associates_device(db_engine):
    device_id = _create_device(db_engine, bluetooth_address="AA:BB:CC:DD:EE:FF")
    client = _client_for(db_engine)

    response = client.post("/scenes/", json={"name": "Movie Night", "bluetooth_address": "AA:BB:CC:DD:EE:FF"})

    assert response.status_code == 200
    assert [d["id"] for d in response.json()["devices"]] == [device_id]


def test_list_scenes_empty(db_engine):
    client = _client_for(db_engine)

    response = client.get("/scenes/")

    assert response.status_code == 200
    assert response.json() == []


def test_list_scenes_returns_seeded_scenes(db_engine):
    _create_scene(db_engine, name="Movie Night")
    client = _client_for(db_engine)

    response = client.get("/scenes/")

    assert response.status_code == 200
    assert [s["name"] for s in response.json()] == ["Movie Night"]


def test_get_scene_returns_404_when_missing(db_engine):
    client = _client_for(db_engine)

    response = client.get("/scenes/999")

    assert response.status_code == 404


def test_get_scene_returns_full_device_details(db_engine):
    # get_scene uses SceneWithRelationshipsAndFullDevices, a richer shape
    # than list/create's SceneWithRelationships - devices come back with
    # their own full fields, not just id.
    device_id = _create_device(db_engine, name="TV", manufacturer="Sony")
    scene_id = _create_scene(db_engine, name="Movie Night")
    with Session(db_engine) as session:
        scene = session.get(Scene, scene_id)
        scene.devices = [session.get(Device, device_id)]
        session.add(scene)
        session.commit()
    client = _client_for(db_engine)

    response = client.get(f"/scenes/{scene_id}")

    assert response.status_code == 200
    devices = response.json()["devices"]
    assert len(devices) == 1
    assert devices[0]["name"] == "TV"
    assert devices[0]["manufacturer"] == "Sony"


def test_update_scene_returns_404_when_missing(db_engine):
    client = _client_for(db_engine)

    response = client.patch("/scenes/999", json={"name": "x"})

    assert response.status_code == 404


def test_update_scene_happy(db_engine):
    scene_id = _create_scene(db_engine, name="Old Name")
    client = _client_for(db_engine)

    response = client.patch(f"/scenes/{scene_id}", json={"name": "New Name"})

    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


def test_update_scene_with_invalid_stop_macro_id_returns_400(db_engine):
    # Unlike create_scene, this branch's message is correct.
    scene_id = _create_scene(db_engine)
    client = _client_for(db_engine)

    response = client.patch(f"/scenes/{scene_id}", json={"name": "x", "stop_macro_id": 999})

    assert response.status_code == 400
    assert response.json() == {"detail": "Stop macro 999 not found"}


def test_delete_scene_returns_404_when_missing(db_engine):
    client = _client_for(db_engine)

    response = client.delete("/scenes/999")

    assert response.status_code == 404


def test_delete_scene_removes_the_row(db_engine):
    scene_id = _create_scene(db_engine, name="Doomed")
    client = _client_for(db_engine)

    response = client.delete(f"/scenes/{scene_id}")

    assert response.status_code == 200
    assert response.json() == {"message": "Successfully deleted Doomed"}
    assert client.get(f"/scenes/{scene_id}").status_code == 404


def test_start_scene_delegates_to_scene_manager(db_engine):
    scene_id = _create_scene(db_engine)
    scene_manager = FakeSceneManager()
    client = _client_for(db_engine, scene_manager=scene_manager)

    response = client.post(f"/scenes/{scene_id}/start")

    assert response.status_code == 200
    assert response.json() == f"Started scene {scene_id}"
    assert scene_manager.started == [scene_id]


def test_start_scene_returns_404_when_scene_manager_raises_not_found(db_engine):
    scene_manager = FakeSceneManager()
    scene_manager.start_scene_exception = SceneNotFoundError("no such scene")
    client = _client_for(db_engine, scene_manager=scene_manager)

    response = client.post("/scenes/999/start")

    assert response.status_code == 404
    assert response.json() == {"detail": "Scene not found"}


def test_set_current_scene_delegates_to_scene_manager(db_engine):
    scene_id = _create_scene(db_engine)
    scene_manager = FakeSceneManager()
    client = _client_for(db_engine, scene_manager=scene_manager)

    response = client.post(f"/scenes/{scene_id}/set_current")

    assert response.status_code == 200
    assert scene_manager.set_current_calls == [scene_id]


def test_set_current_scene_returns_404_when_scene_manager_raises_not_found(db_engine):
    scene_manager = FakeSceneManager()
    scene_manager.set_current_scene_exception = SceneNotFoundError("no such scene")
    client = _client_for(db_engine, scene_manager=scene_manager)

    response = client.post("/scenes/999/set_current")

    assert response.status_code == 404
    assert response.json() == {"detail": "Scene not found"}


def test_keymap_suggestions_returns_404_when_scene_missing(db_engine):
    client = _client_for(db_engine, keymap_resolver=FakeKeymapResolver())

    response = client.get("/scenes/999/keymap_suggestions")

    assert response.status_code == 404


def test_keymap_suggestions_returns_the_resolvers_suggestion(db_engine):
    scene_id = _create_scene(db_engine)
    keymap_resolver = FakeKeymapResolver(suggestion={"Play": 5})
    client = _client_for(db_engine, keymap_resolver=keymap_resolver)

    response = client.get(f"/scenes/{scene_id}/keymap_suggestions")

    assert response.status_code == 200
    assert response.json() == {"Play": 5}
    assert len(keymap_resolver.suggest_keymap_calls) == 1


def test_stop_current_scene_delegates_to_scene_manager(db_engine):
    scene_manager = FakeSceneManager()
    client = _client_for(db_engine, scene_manager=scene_manager)

    response = client.post("/scenes/stop")

    assert response.status_code == 200
    assert response.json() == "Stopped current scene."
    assert scene_manager.stopped == 1


def test_stop_current_scene_returns_404_when_no_active_scene(db_engine):
    scene_manager = FakeSceneManager()
    scene_manager.stop_current_scene_exception = NoActiveSceneError("nothing active")
    client = _client_for(db_engine, scene_manager=scene_manager)

    response = client.post("/scenes/stop")

    assert response.status_code == 404
    assert response.json() == {"detail": "No scene active"}


def test_stop_current_scene_returns_404_when_scene_not_found(db_engine):
    scene_manager = FakeSceneManager()
    scene_manager.stop_current_scene_exception = SceneNotFoundError("no such scene")
    client = _client_for(db_engine, scene_manager=scene_manager)

    response = client.post("/scenes/stop")

    assert response.status_code == 404
    assert response.json() == {"detail": "no such scene"}
