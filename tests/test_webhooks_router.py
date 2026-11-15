from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.models.scene import Scene
from api.models.webhook import Webhook
from api.routers import webhooks
from db_manager.db_manager import get_session


def _client_for(db_engine) -> TestClient:
    app = FastAPI()
    app.include_router(webhooks.router)
    app.dependency_overrides[get_session] = lambda: Session(db_engine)
    return TestClient(app)


def _create_scene(db_engine, name: str = "Movie Night") -> int:
    with Session(db_engine) as session:
        scene = Scene(name=name)
        session.add(scene)
        session.commit()
        session.refresh(scene)
        assert scene.id is not None
        return scene.id


def _payload(**overrides) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": "Lights", "url": "http://lights.local/hook"}
    payload.update(overrides)
    return payload


def _create(client: TestClient, **overrides) -> dict:
    response = client.post("/webhooks/", json=_payload(**overrides))
    assert response.status_code == 200, response.text
    return response.json()


def test_create_webhook_applies_defaults(db_engine):
    client = _client_for(db_engine)

    webhook = _create(client)

    assert webhook == {
        "id": 1,
        "name": "Lights",
        "url": "http://lights.local/hook",
        "method": "post",
        "headers": None,
        "body_template": None,
        "body_format": "json",
        "events": [],
        "scene_ids": [],
        "enabled": True,
    }


def test_create_webhook_stores_everything_it_is_given(db_engine):
    client = _client_for(db_engine)
    scene_id = _create_scene(db_engine)

    created = _create(
        client,
        method="put",
        headers={"Authorization": "Bearer abc", "X-Scene": "{{ SCENE_NAME }}"},
        body_template='{"scene": {{ SCENE_ID }}, "event": "{{ EVENT }}"}',
        events=["scene.started", "scene.stopped"],
        scene_ids=[scene_id],
        enabled=False,
    )

    shown = client.get(f"/webhooks/{created['id']}").json()
    assert shown == created
    assert shown["events"] == ["scene.started", "scene.stopped"]
    assert shown["scene_ids"] == [scene_id]
    assert shown["headers"]["X-Scene"] == "{{ SCENE_NAME }}"
    assert shown["enabled"] is False


def test_create_webhook_is_stored_in_the_database(db_engine):
    client = _client_for(db_engine)

    _create(client, events=["scene.starting"], headers={"A": "b"})

    with Session(db_engine) as session:
        stored = session.get(Webhook, 1)
        assert stored is not None
        assert [str(event) for event in stored.events] == ["scene.starting"]
        assert stored.headers == {"A": "b"}


def test_create_webhook_removes_duplicate_events_and_scenes(db_engine):
    client = _client_for(db_engine)
    scene_id = _create_scene(db_engine)

    webhook = _create(
        client, events=["scene.started", "scene.stopped", "scene.started"], scene_ids=[scene_id, scene_id]
    )

    assert webhook["events"] == ["scene.started", "scene.stopped"]
    assert webhook["scene_ids"] == [scene_id]


def test_create_webhook_rejects_an_unknown_event(db_engine):
    client = _client_for(db_engine)

    response = client.post("/webhooks/", json=_payload(events=["scene.exploded"]))

    assert response.status_code == 422


def test_create_webhook_rejects_an_unknown_method(db_engine):
    client = _client_for(db_engine)

    assert client.post("/webhooks/", json=_payload(method="connect")).status_code == 422


def test_create_webhook_rejects_urls_that_are_not_http(db_engine):
    client = _client_for(db_engine)

    for url in ("ftp://host/hook", "file:///etc/passwd", "lights.local/hook", "http://", ""):
        response = client.post("/webhooks/", json=_payload(url=url))
        assert response.status_code == 400, url
        assert "url" in response.json()["detail"]


def test_create_webhook_accepts_https_with_port_and_query(db_engine):
    client = _client_for(db_engine)

    _create(client, url="https://hooks.example.com:8443/a/b?token=1")


def test_create_webhook_rejects_a_blank_name(db_engine):
    client = _client_for(db_engine)

    response = client.post("/webhooks/", json=_payload(name="  "))

    assert response.status_code == 400
    assert "name" in response.json()["detail"]


def test_create_webhook_rejects_an_unknown_scene(db_engine):
    client = _client_for(db_engine)

    response = client.post("/webhooks/", json=_payload(scene_ids=[42]))

    assert response.status_code == 400
    assert response.json()["detail"] == "There is no scene with id 42"


def test_create_webhook_rejects_unknown_placeholders_in_the_body_and_headers(db_engine):
    client = _client_for(db_engine)

    response = client.post(
        "/webhooks/", json=_payload(body_template='{"a": {{ NOPE }}}', headers={"X-A": "{{ OTHER }}"})
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Body: Unknown placeholder NOPE" in detail
    assert "Header X-A: Unknown placeholder OTHER" in detail


def test_create_webhook_rejects_a_stray_brace_pair_in_the_body(db_engine):
    client = _client_for(db_engine)

    response = client.post("/webhooks/", json=_payload(body_template="scene {{ SCENE_ID"))

    assert response.status_code == 400
    assert "Body" in response.json()["detail"]


def test_create_webhook_rejects_invalid_header_names(db_engine):
    client = _client_for(db_engine)

    for name in ("Bad Name", "X:Y", "X\r\nInjected", ""):
        response = client.post("/webhooks/", json=_payload(headers={name: "v"}))
        assert response.status_code == 400, repr(name)
        assert "header name" in response.json()["detail"]


def test_create_webhook_rejects_a_body_for_a_method_without_one(db_engine):
    client = _client_for(db_engine)

    for method in ("get", "delete", "head"):
        response = client.post("/webhooks/", json=_payload(method=method, body_template="x"))
        assert response.status_code == 400, method
        assert f"A {method} request can't have a body" in response.json()["detail"]


def test_create_webhook_rejects_a_json_body_that_is_not_json(db_engine):
    client = _client_for(db_engine)

    response = client.post("/webhooks/", json=_payload(body_template='{"scene": {{ SCENE_NAME }}}'))

    assert response.status_code == 400
    assert "isn't valid JSON" in response.json()["detail"]


def test_create_webhook_accepts_a_json_body_with_placeholders(db_engine):
    client = _client_for(db_engine)

    _create(client, body_template='{"scene": "{{ SCENE_NAME }}", "id": {{ SCENE_ID }}, "e": {"n": "{{ EVENT }}"}}')


def test_create_webhook_does_not_check_a_text_body_for_json(db_engine):
    client = _client_for(db_engine)

    _create(client, body_format="text", body_template="Scene {{ SCENE_NAME }} is {{ SCENE_STATUS }}")


def test_create_webhook_reports_every_problem_at_once(db_engine):
    client = _client_for(db_engine)

    response = client.post("/webhooks/", json=_payload(name="", url="nope", scene_ids=[7]))

    detail = response.json()["detail"]
    assert "name" in detail
    assert "url" in detail
    assert "scene with id 7" in detail


def test_list_webhooks(db_engine):
    client = _client_for(db_engine)
    assert client.get("/webhooks/").json() == []
    _create(client, name="One")
    _create(client, name="Two")

    assert [webhook["name"] for webhook in client.get("/webhooks/").json()] == ["One", "Two"]


def test_show_webhook_returns_404_for_an_unknown_id(db_engine):
    assert _client_for(db_engine).get("/webhooks/9").status_code == 404


def test_update_webhook_changes_only_what_is_given(db_engine):
    client = _client_for(db_engine)
    created = _create(client, headers={"A": "b"}, events=["scene.started"])

    response = client.patch(f"/webhooks/{created['id']}", json={"enabled": False, "name": "Renamed"})

    assert response.status_code == 200
    assert response.json() == {**created, "enabled": False, "name": "Renamed"}
    assert client.get(f"/webhooks/{created['id']}").json() == response.json()


def test_update_webhook_can_clear_headers_and_body(db_engine):
    client = _client_for(db_engine)
    created = _create(client, headers={"A": "b"}, body_template="{}")

    response = client.patch(f"/webhooks/{created['id']}", json={"headers": None, "body_template": None})

    assert response.status_code == 200
    assert response.json()["headers"] is None
    assert response.json()["body_template"] is None


def test_update_webhook_can_clear_events_and_scenes_with_empty_lists(db_engine):
    client = _client_for(db_engine)
    scene_id = _create_scene(db_engine)
    created = _create(client, events=["scene.started"], scene_ids=[scene_id])

    response = client.patch(f"/webhooks/{created['id']}", json={"events": [], "scene_ids": []})

    assert response.json()["events"] == []
    assert response.json()["scene_ids"] == []


def test_update_webhook_validates_the_result_as_a_whole(db_engine):
    client = _client_for(db_engine)
    created = _create(client, body_template='{"a": 1}')

    response = client.patch(f"/webhooks/{created['id']}", json={"method": "get"})

    assert response.status_code == 400
    assert "can't have a body" in response.json()["detail"]
    assert client.get(f"/webhooks/{created['id']}").json()["method"] == "post"


def test_update_webhook_rechecks_the_body_against_a_new_format(db_engine):
    client = _client_for(db_engine)
    created = _create(client, body_format="text", body_template="Scene {{ SCENE_NAME }}")

    response = client.patch(f"/webhooks/{created['id']}", json={"body_format": "json"})

    assert response.status_code == 400
    assert "isn't valid JSON" in response.json()["detail"]


def test_update_webhook_rejects_a_null_for_a_required_field(db_engine):
    client = _client_for(db_engine)
    created = _create(client)

    for field in ("name", "url", "method", "body_format", "events", "scene_ids", "enabled"):
        response = client.patch(f"/webhooks/{created['id']}", json={field: None})
        assert response.status_code == 400, field
        assert response.json()["detail"] == f"{field} can't be null"


def test_update_webhook_returns_404_for_an_unknown_id(db_engine):
    assert _client_for(db_engine).patch("/webhooks/9", json={"enabled": False}).status_code == 404


def test_delete_webhook(db_engine):
    client = _client_for(db_engine)
    created = _create(client)

    assert client.delete(f"/webhooks/{created['id']}").json() == {"ok": True}
    assert client.get(f"/webhooks/{created['id']}").status_code == 404


def test_delete_webhook_returns_404_for_an_unknown_id(db_engine):
    assert _client_for(db_engine).delete("/webhooks/9").status_code == 404


def test_placeholders_lists_names_and_descriptions(db_engine):
    placeholders = _client_for(db_engine).get("/webhooks/placeholders").json()

    names = [placeholder["name"] for placeholder in placeholders]
    assert "SCENE_NAME" in names
    assert "EVENT" in names
    assert all(placeholder["description"] for placeholder in placeholders)


def test_events_lists_the_scene_events(db_engine):
    assert _client_for(db_engine).get("/webhooks/events").json() == [
        "scene.starting", "scene.started", "scene.stopping", "scene.stopped",
    ]
