from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.models.device import Device
from api.models.user_image import UserImage
from api.routers import devices
from db_manager.db_manager import get_session


def _client_for(db_engine) -> TestClient:
    app = FastAPI()
    app.include_router(devices.router)
    app.dependency_overrides[get_session] = lambda: Session(db_engine)
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


def _create_image(db_engine, **overrides) -> int:
    defaults = {"filename": "cover.png", "path": "/tmp/cover.png"}
    defaults.update(overrides)
    with Session(db_engine) as session:
        image = UserImage(**defaults)
        session.add(image)
        session.commit()
        session.refresh(image)
        assert image.id is not None
        return image.id


def test_list_devices_empty(db_engine):
    client = _client_for(db_engine)

    response = client.get("/devices/")

    assert response.status_code == 200
    assert response.json() == []


def test_list_devices_returns_seeded_devices(db_engine):
    _create_device(db_engine, name="TV")
    client = _client_for(db_engine)

    response = client.get("/devices/")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "TV"
    assert body[0]["commands"] == []
    assert body[0]["scenes"] == []
    assert body[0]["macros"] == []
    assert body[0]["image"] is None


def test_read_device_returns_404_when_missing(db_engine):
    client = _client_for(db_engine)

    response = client.get("/devices/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Device not found"}


def test_read_device_returns_the_device(db_engine):
    device_id = _create_device(db_engine, name="Amp", manufacturer="Yamaha")
    client = _client_for(db_engine)

    response = client.get(f"/devices/{device_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == device_id
    assert body["name"] == "Amp"
    assert body["manufacturer"] == "Yamaha"


def test_delete_device_returns_404_when_missing(db_engine):
    client = _client_for(db_engine)

    response = client.delete("/devices/999")

    assert response.status_code == 404


def test_delete_device_removes_the_row(db_engine):
    device_id = _create_device(db_engine)
    client = _client_for(db_engine)

    response = client.delete(f"/devices/{device_id}")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert client.get(f"/devices/{device_id}").status_code == 404


def test_update_device_returns_404_when_missing(db_engine):
    client = _client_for(db_engine)

    response = client.patch("/devices/999", json={"name": "New Name"})

    assert response.status_code == 404


def test_update_device_only_changes_fields_that_were_sent(db_engine):
    device_id = _create_device(db_engine, name="TV", manufacturer="Sony")
    client = _client_for(db_engine)

    response = client.patch(f"/devices/{device_id}", json={"name": "New TV"})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "New TV"
    assert body["manufacturer"] == "Sony"


def test_update_device_with_valid_image_id_associates_it(db_engine):
    device_id = _create_device(db_engine)
    image_id = _create_image(db_engine)
    client = _client_for(db_engine)

    response = client.patch(f"/devices/{device_id}", json={"name": "TV", "image_id": image_id})

    # update_device has no response_model, so unlike create_device (which
    # returns DeviceWithRelationships and expands the image relationship),
    # the raw device is serialized as-is: only the image_id FK, no nested
    # "image" object.
    assert response.status_code == 200
    assert response.json()["image_id"] == image_id


def test_update_device_with_invalid_image_id_returns_404(db_engine):
    device_id = _create_device(db_engine)
    client = _client_for(db_engine)

    response = client.patch(f"/devices/{device_id}", json={"name": "TV", "image_id": 999})

    assert response.status_code == 404
    assert response.json() == {"detail": "Image 999 not found"}


def test_create_device_returns_the_new_device(db_engine):
    client = _client_for(db_engine)

    response = client.post("/devices/", json={"name": "Speaker"})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Speaker"
    assert body["id"] is not None


def test_create_device_with_valid_image_id_associates_it(db_engine):
    image_id = _create_image(db_engine)
    client = _client_for(db_engine)

    response = client.post("/devices/", json={"name": "Speaker", "image_id": image_id})

    assert response.status_code == 200
    assert response.json()["image"]["id"] == image_id


def test_create_device_with_invalid_image_id_returns_404(db_engine):
    client = _client_for(db_engine)

    response = client.post("/devices/", json={"name": "Speaker", "image_id": 999})

    assert response.status_code == 404
    assert response.json() == {"detail": "Image 999 not found"}
