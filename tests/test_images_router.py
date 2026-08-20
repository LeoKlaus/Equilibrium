from io import BytesIO

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session

from api.models.user_image import UserImage
from api.routers import images
from db_manager.db_manager import get_session


def _client_for(db_engine) -> TestClient:
    app = FastAPI()
    app.include_router(images.router)
    app.dependency_overrides[get_session] = lambda: Session(db_engine)
    return TestClient(app)


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (10, 10), color="red").save(buf, "PNG")
    return buf.getvalue()


def _create_image_row(db_engine, **overrides) -> int:
    defaults = {"filename": "cover.png", "path": "config/images/cover.png"}
    defaults.update(overrides)
    with Session(db_engine) as session:
        image = UserImage(**defaults)
        session.add(image)
        session.commit()
        session.refresh(image)
        assert image.id is not None
        return image.id


def test_list_images_empty(db_engine, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = _client_for(db_engine)

    response = client.get("/images/")

    assert response.status_code == 200
    assert response.json() == []


def test_list_images_returns_seeded_images(db_engine, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _create_image_row(db_engine, filename="cover.png")
    client = _client_for(db_engine)

    response = client.get("/images/")

    assert response.status_code == 200
    assert [image["filename"] for image in response.json()] == ["cover.png"]


def test_get_image_returns_404_when_missing(db_engine, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = _client_for(db_engine)

    response = client.get("/images/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Image not found"}


def test_get_image_returns_the_file(db_engine, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config" / "images").mkdir(parents=True)
    file_bytes = _png_bytes()
    (tmp_path / "config" / "images" / "cover.png").write_bytes(file_bytes)
    image_id = _create_image_row(db_engine, path="config/images/cover.png")
    client = _client_for(db_engine)

    response = client.get(f"/images/{image_id}")

    assert response.status_code == 200
    assert response.content == file_bytes


def test_upload_image_creates_a_row_and_writes_the_file(db_engine, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    client = _client_for(db_engine)

    response = client.post("/images/", files={"file": ("photo.png", _png_bytes(), "image/png")})

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "photo.png"
    assert body["id"] is not None

    saved_path = tmp_path / body["path"]
    assert saved_path.is_file()


def test_upload_image_with_corrupt_bytes_returns_500(db_engine, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    client = _client_for(db_engine)

    response = client.post("/images/", files={"file": ("photo.png", b"not an image", "image/png")})

    assert response.status_code == 500
    assert "Something went wrong" in response.json()["detail"]


def test_delete_image_returns_404_when_missing(db_engine, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = _client_for(db_engine)

    response = client.delete("/images/999")

    assert response.status_code == 404


def test_delete_image_removes_the_row_and_the_file(db_engine, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config" / "images").mkdir(parents=True)
    (tmp_path / "config" / "images" / "cover.png").write_bytes(_png_bytes())
    image_id = _create_image_row(db_engine, path="config/images/cover.png")
    client = _client_for(db_engine)

    response = client.delete(f"/images/{image_id}")

    assert response.status_code == 200
    assert response.json() == {"message": "Successfully deleted cover.png"}
    assert not (tmp_path / "config" / "images" / "cover.png").exists()
    assert client.get(f"/images/{image_id}").status_code == 404


def test_delete_image_when_the_file_is_already_missing_does_not_crash(db_engine, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    image_id = _create_image_row(db_engine, path="config/images/already-gone.png")
    client = _client_for(db_engine)

    response = client.delete(f"/images/{image_id}")

    assert response.status_code == 200
    assert response.json() == {"message": "Successfully deleted cover.png"}
