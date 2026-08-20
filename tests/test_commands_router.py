from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.dependencies import get_command_dispatcher
from api.models.command import Command
from api.models.device import Device
from api.routers import commands
from db_manager.db_manager import get_session
from hub.event_bus import Directive


class FakeCommandDispatcher:
    def __init__(self):
        self.dispatched = []

    async def dispatch(self, directive: Directive, from_start=False, from_stop=False) -> None:
        self.dispatched.append(directive)


def _client_for(db_engine, command_dispatcher=None) -> TestClient:
    app = FastAPI()
    app.include_router(commands.router)
    app.dependency_overrides[get_session] = lambda: Session(db_engine)
    if command_dispatcher is not None:
        app.dependency_overrides[get_command_dispatcher] = lambda: command_dispatcher
    return TestClient(app)


def _create_command(db_engine, **overrides) -> int:
    defaults = {
        "name": "cmd",
        "button": "power_toggle",
        "type": "network",
        "command_group": "power",
        "host": "http://tv.local",
        "method": "get",
    }
    defaults.update(overrides)
    with Session(db_engine) as session:
        command = Command(**defaults)
        session.add(command)
        session.commit()
        session.refresh(command)
        assert command.id is not None
        return command.id


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


def _payload(**overrides) -> dict:
    defaults = {
        "name": "cmd",
        "button": "power_toggle",
        "type": "network",
        "command_group": "power",
        "host": "http://tv.local",
        "method": "get",
    }
    defaults.update(overrides)
    return defaults


def test_list_commands_empty(db_engine):
    client = _client_for(db_engine)

    response = client.get("/commands/")

    assert response.status_code == 200
    assert response.json() == []


def test_list_commands_returns_seeded_commands(db_engine):
    _create_command(db_engine, name="Power")
    client = _client_for(db_engine)

    response = client.get("/commands/")

    assert response.status_code == 200
    assert [c["name"] for c in response.json()] == ["Power"]


def test_show_command_returns_404_when_missing(db_engine):
    client = _client_for(db_engine)

    response = client.get("/commands/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Command not found"}


def test_show_command_returns_the_command(db_engine):
    command_id = _create_command(db_engine, name="Power")
    client = _client_for(db_engine)

    response = client.get(f"/commands/{command_id}")

    assert response.status_code == 200
    assert response.json()["name"] == "Power"


def test_create_command_ir_is_always_rejected(db_engine):
    # CommandBase has no ir_action field at all - IR commands can only be
    # created through /ws/commands, which is what this 400 enforces.
    client = _client_for(db_engine)

    response = client.post("/commands/", json=_payload(type="ir", button="play", command_group="transport"))

    assert response.status_code == 400
    assert "WebSocket" in response.json()["detail"]


def test_create_command_network_missing_host_returns_400(db_engine):
    client = _client_for(db_engine)

    response = client.post("/commands/", json=_payload(host=None))

    assert response.status_code == 400
    assert response.json() == {"detail": "Network commands require a host to be set."}


def test_create_command_network_missing_method_returns_400(db_engine):
    client = _client_for(db_engine)

    response = client.post("/commands/", json=_payload(method=None))

    assert response.status_code == 400
    assert response.json() == {"detail": "Network commands require a method to be set."}


def test_create_command_network_happy(db_engine):
    client = _client_for(db_engine)

    response = client.post("/commands/", json=_payload())

    assert response.status_code == 200
    assert response.json()["host"] == "http://tv.local"


def test_create_command_bluetooth_missing_both_actions_returns_400(db_engine):
    client = _client_for(db_engine)

    response = client.post(
        "/commands/", json=_payload(type="bluetooth", button="select", command_group="other", host=None, method=None)
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Bluetooth commands require either an action or a media action."}


def test_create_command_bluetooth_with_bt_action_is_happy(db_engine):
    client = _client_for(db_engine)

    response = client.post(
        "/commands/",
        json=_payload(
            type="bluetooth", button="select", command_group="other", host=None, method=None, bt_action="a",
        ),
    )

    assert response.status_code == 200


def test_create_command_bluetooth_with_bt_media_action_is_happy(db_engine):
    client = _client_for(db_engine)

    response = client.post(
        "/commands/",
        json=_payload(
            type="bluetooth", button="select", command_group="other", host=None, method=None, bt_media_action="a",
        ),
    )

    assert response.status_code == 200


def test_create_command_integration_missing_action_returns_400(db_engine):
    client = _client_for(db_engine)

    response = client.post(
        "/commands/",
        json=_payload(type="integration", button="select", command_group="other", host=None, method=None),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Integration commands require an integration action."}


def test_create_command_toggle_light_missing_entity_returns_400(db_engine):
    client = _client_for(db_engine)

    response = client.post(
        "/commands/",
        json=_payload(
            type="integration", button="select", command_group="other", host=None, method=None,
            integration_action="toggle_light",
        ),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "A toggle_light command requires an entity."}


def test_create_command_toggle_light_with_entity_is_happy(db_engine):
    client = _client_for(db_engine)

    response = client.post(
        "/commands/",
        json=_payload(
            type="integration", button="select", command_group="other", host=None, method=None,
            integration_action="toggle_light", integration_entity="light.living_room",
        ),
    )

    assert response.status_code == 200


def test_create_command_brightness_up_without_entity_is_happy(db_engine):
    # Proves the entity requirement is specific to toggle_light, not every
    # integration action.
    client = _client_for(db_engine)

    response = client.post(
        "/commands/",
        json=_payload(
            type="integration", button="select", command_group="other", host=None, method=None,
            integration_action="brightness_up",
        ),
    )

    assert response.status_code == 200


def test_create_command_script_missing_script_path_returns_400(db_engine):
    client = _client_for(db_engine)

    response = client.post(
        "/commands/", json=_payload(type="script", button="select", command_group="other", host=None, method=None)
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Script commands require a script_path to be set."}


def test_create_command_script_happy(db_engine):
    client = _client_for(db_engine)

    response = client.post(
        "/commands/",
        json=_payload(
            type="script", button="select", command_group="other", host=None, method=None,
            script_path="./scripts/foo.sh",
        ),
    )

    assert response.status_code == 200


def test_create_command_with_invalid_device_id_returns_400(db_engine):
    client = _client_for(db_engine)

    response = client.post("/commands/", json=_payload(device_id=999))

    assert response.status_code == 400
    assert response.json() == {"detail": "There is no device with id 999."}


def test_create_command_with_valid_device_id_associates_it(db_engine):
    device_id = _create_device(db_engine)
    client = _client_for(db_engine)

    response = client.post("/commands/", json=_payload(device_id=device_id))

    assert response.status_code == 200
    assert response.json()["device"]["id"] == device_id


def test_send_command_dispatches_a_directive(db_engine):
    dispatcher = FakeCommandDispatcher()
    command_id = _create_command(db_engine)
    client = _client_for(db_engine, command_dispatcher=dispatcher)

    response = client.post(f"/commands/{command_id}/send")

    assert response.status_code == 200
    assert response.json() == "Command sent"
    assert len(dispatcher.dispatched) == 1
    assert dispatcher.dispatched[0].command_id == command_id


def test_delete_command_returns_404_when_missing(db_engine, monkeypatch):
    monkeypatch.setattr("api.models.command.engine", db_engine)
    client = _client_for(db_engine)

    response = client.delete("/commands/999")

    assert response.status_code == 404


def test_delete_command_removes_the_row(db_engine, monkeypatch):
    monkeypatch.setattr("api.models.command.engine", db_engine)
    command_id = _create_command(db_engine)
    client = _client_for(db_engine)

    response = client.delete(f"/commands/{command_id}")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert client.get(f"/commands/{command_id}").status_code == 404
