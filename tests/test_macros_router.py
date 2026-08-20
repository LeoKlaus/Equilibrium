from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.dependencies import get_command_dispatcher
from api.models.command import Command
from api.models.device import Device
from api.models.macro import Macro
from api.models.scene import Scene
from api.routers import macros
from db_manager.db_manager import get_session


class FakeCommandDispatcher:
    def __init__(self):
        self.executed = []

    async def execute_macro(self, macro, from_start=False, from_stop=False) -> None:
        self.executed.append(macro)


def _client_for(db_engine, command_dispatcher=None) -> TestClient:
    app = FastAPI()
    app.include_router(macros.router)
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


def _create_macro(db_engine, **overrides) -> int:
    defaults = {"name": "My Macro", "command_ids": [], "delays": []}
    defaults.update(overrides)
    with Session(db_engine) as session:
        macro = Macro(**defaults)
        session.add(macro)
        session.commit()
        session.refresh(macro)
        assert macro.id is not None
        return macro.id


def test_list_macros_empty(db_engine):
    client = _client_for(db_engine)

    response = client.get("/macros/")

    assert response.status_code == 200
    assert response.json() == []


def test_list_macros_returns_seeded_macros(db_engine):
    _create_macro(db_engine, name="Movie Macro")
    client = _client_for(db_engine)

    response = client.get("/macros/")

    assert response.status_code == 200
    assert [m["name"] for m in response.json()] == ["Movie Macro"]


def test_get_macro_returns_404_when_missing(db_engine):
    client = _client_for(db_engine)

    response = client.get("/macros/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Macro not found"}


def test_get_macro_returns_the_macro(db_engine):
    macro_id = _create_macro(db_engine, name="Movie Macro")
    client = _client_for(db_engine)

    response = client.get(f"/macros/{macro_id}")

    assert response.status_code == 200
    assert response.json()["name"] == "Movie Macro"


def test_create_macro_happy(db_engine):
    command_1 = _create_command(db_engine)
    command_2 = _create_command(db_engine)
    client = _client_for(db_engine)

    response = client.post(
        "/macros/", json={"name": "My Macro", "command_ids": [command_1, command_2], "delays": [500]}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "My Macro"
    assert {c["id"] for c in body["commands"]} == {command_1, command_2}
    assert body["delays"] == [500]


def test_create_macro_with_no_commands_returns_400(db_engine):
    client = _client_for(db_engine)

    response = client.post("/macros/", json={"name": "Empty", "command_ids": [], "delays": []})

    assert response.status_code == 400
    assert response.json() == {"detail": "You have to include at least one command."}


def test_create_macro_with_mismatched_delays_returns_400(db_engine):
    command_1 = _create_command(db_engine)
    command_2 = _create_command(db_engine)
    client = _client_for(db_engine)

    response = client.post(
        "/macros/", json={"name": "Bad", "command_ids": [command_1, command_2], "delays": [500, 500]}
    )

    assert response.status_code == 400
    assert "one delay for all but the last command" in response.json()["detail"]


def test_create_macro_with_nonexistent_command_id_returns_404(db_engine):
    client = _client_for(db_engine)

    response = client.post("/macros/", json={"name": "Bad", "command_ids": [999], "delays": []})

    assert response.status_code == 404
    assert response.json() == {"detail": "Command 999 not found"}


def test_create_macro_with_nonexistent_scene_id_returns_404(db_engine):
    command_id = _create_command(db_engine)
    client = _client_for(db_engine)

    response = client.post(
        "/macros/", json={"name": "Bad", "command_ids": [command_id], "delays": [], "scene_ids": [999]}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Scene 999 not found"}


def test_create_macro_populates_devices_from_commands_deduped(db_engine):
    device_id = _create_device(db_engine)
    command_1 = _create_command(db_engine, device_id=device_id)
    command_2 = _create_command(db_engine, device_id=device_id)
    client = _client_for(db_engine)

    response = client.post(
        "/macros/", json={"name": "My Macro", "command_ids": [command_1, command_2], "delays": [500]}
    )

    assert response.status_code == 200
    assert [d["id"] for d in response.json()["devices"]] == [device_id]


def test_update_macro_returns_404_when_missing(db_engine):
    client = _client_for(db_engine)

    response = client.patch("/macros/999", json={"command_ids": [], "delays": []})

    assert response.status_code == 404


def test_update_macro_with_no_commands_returns_400(db_engine):
    macro_id = _create_macro(db_engine)
    client = _client_for(db_engine)

    response = client.patch(f"/macros/{macro_id}", json={"name": "x", "command_ids": [], "delays": []})

    assert response.status_code == 400
    assert response.json() == {"detail": "You have to include at least one command."}


def test_update_macro_replaces_commands_and_delays(db_engine):
    old_command = _create_command(db_engine)
    new_command_1 = _create_command(db_engine)
    new_command_2 = _create_command(db_engine)
    macro_id = _create_macro(db_engine, command_ids=[old_command], delays=[])
    client = _client_for(db_engine)

    response = client.patch(
        f"/macros/{macro_id}",
        json={"name": "Renamed", "command_ids": [new_command_1, new_command_2], "delays": [200]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed"
    assert {c["id"] for c in body["commands"]} == {new_command_1, new_command_2}
    assert body["delays"] == [200]


def test_update_macro_with_a_device_less_command_succeeds(db_engine):
    """Regression test: update_macro used to append command_db.device_id
    unconditionally, unlike create_macro which already guarded it - so
    PATCHing a macro containing a device-less command (e.g. an
    integration/bluetooth/script command with no device attached) would
    append None into device_ids and then fail looking it up as a Device.
    """
    device_less_command = _create_command(db_engine)  # device_id defaults to None
    macro_id = _create_macro(db_engine, command_ids=[], delays=[])
    client = _client_for(db_engine)

    response = client.patch(
        f"/macros/{macro_id}", json={"name": "x", "command_ids": [device_less_command], "delays": []}
    )

    assert response.status_code == 200
    assert response.json()["devices"] == []


def test_delete_macro_returns_404_when_missing(db_engine):
    client = _client_for(db_engine)

    response = client.delete("/macros/999")

    assert response.status_code == 404


def test_delete_macro_removes_the_row(db_engine):
    macro_id = _create_macro(db_engine, name="Doomed")
    client = _client_for(db_engine)

    response = client.delete(f"/macros/{macro_id}")

    assert response.status_code == 200
    assert response.json() == {"message": "Successfully deleted Doomed"}
    assert client.get(f"/macros/{macro_id}").status_code == 404


def test_execute_macro_returns_404_when_missing(db_engine):
    dispatcher = FakeCommandDispatcher()
    client = _client_for(db_engine, command_dispatcher=dispatcher)

    response = client.post("/macros/999/execute")

    assert response.status_code == 404
    assert dispatcher.executed == []


def test_execute_macro_dispatches_it(db_engine):
    dispatcher = FakeCommandDispatcher()
    macro_id = _create_macro(db_engine)
    client = _client_for(db_engine, command_dispatcher=dispatcher)

    response = client.post(f"/macros/{macro_id}/execute")

    assert response.status_code == 200
    assert response.json() == "Macro executed"
    assert len(dispatcher.executed) == 1
    assert dispatcher.executed[0].id == macro_id
