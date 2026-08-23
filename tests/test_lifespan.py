import json
from typing import ClassVar

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.lifespan import _lifespan, _load_ha_credentials, _load_rf_addresses, _scripts_dir_from_env


class FakeZeroconfManager:
    instances: ClassVar[list["FakeZeroconfManager"]] = []

    def __init__(self):
        self.registered_name = None
        self.unregistered = False
        FakeZeroconfManager.instances.append(self)

    async def register_service(self, name, description=None):
        self.registered_name = name

    async def unregister_service(self):
        self.unregistered = True


def test_load_rf_addresses_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _load_rf_addresses() is None


def test_load_rf_addresses_parses_hex_strings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "rf_addresses.json").write_text(json.dumps(["deadbeef01", "deadbeef02"]))

    addresses = _load_rf_addresses()

    assert addresses == [bytes.fromhex("deadbeef01"), bytes.fromhex("deadbeef02")]


def test_load_ha_credentials_missing_file_returns_none_pair(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _load_ha_credentials() == (None, None)


def test_load_ha_credentials_parses_url_and_token(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "ha_credentials.json").write_text(json.dumps({"url": "http://ha.local", "token": "tok"}))

    assert _load_ha_credentials() == ("http://ha.local", "tok")


def test_load_ha_credentials_missing_key_returns_none_pair(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "ha_credentials.json").write_text(json.dumps({"url": "http://ha.local"}))

    assert _load_ha_credentials() == (None, None)


def test_scripts_dir_from_env_missing_var_is_disabled(monkeypatch):
    monkeypatch.delenv("ENABLE_SCRIPTS", raising=False)
    assert _scripts_dir_from_env() is None


def test_scripts_dir_from_env_false_is_disabled(monkeypatch):
    monkeypatch.setenv("ENABLE_SCRIPTS", "false")
    assert _scripts_dir_from_env() is None


def test_scripts_dir_from_env_true_enables_the_scripts_dir(monkeypatch):
    monkeypatch.setenv("ENABLE_SCRIPTS", "true")
    assert _scripts_dir_from_env() == "config/scripts"


def test_scripts_dir_from_env_accepts_1_and_yes(monkeypatch):
    monkeypatch.setenv("ENABLE_SCRIPTS", "1")
    assert _scripts_dir_from_env() == "config/scripts"

    monkeypatch.setenv("ENABLE_SCRIPTS", "YES")
    assert _scripts_dir_from_env() == "config/scripts"


async def test_lifespan_dev_yields_the_hub_pieces(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    monkeypatch.setattr("api.lifespan.ZeroconfManager", FakeZeroconfManager)
    monkeypatch.setattr("api.lifespan.run_migrations", lambda: None)

    async with _lifespan(FastAPI(), dev=True) as state:
        assert set(state.keys()) == {
            "status_store", "keymap_resolver", "scene_manager",
            "command_dispatcher", "ble_keyboard", "ir_manager", "modules_manifest",
        }
        assert state["status_store"] is not None
        assert state["scene_manager"] is not None
        assert state["ble_keyboard"] is None  # dev mode skips hardware
        assert state["ir_manager"] is None
        assert {module["name"] for module in state["modules_manifest"]} == {"network"}  # only the non-hardware executor in dev mode

    zeroconf = FakeZeroconfManager.instances[-1]
    assert zeroconf.registered_name == "Test-Instance-Dev"
    assert zeroconf.unregistered is True


async def test_lifespan_mounts_module_routers_onto_the_app(tmp_path, monkeypatch):
    from fastapi import APIRouter

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    monkeypatch.setattr("api.lifespan.ZeroconfManager", FakeZeroconfManager)
    monkeypatch.setattr("api.lifespan.run_migrations", lambda: None)

    class FakeExecutorWithRouter:
        name = "fake"
        capabilities: ClassVar[list[str]] = []

        def __init__(self):
            self.router = APIRouter()

            @self.router.get("/fake-module-ping")
            def ping():
                return {"ok": True}

        async def execute(self, directive, command) -> None:
            pass

    async def fake_create(cls, **kwargs):
        hub = cls()
        hub.register_executor(FakeExecutorWithRouter())
        return hub

    monkeypatch.setattr("api.lifespan.Hub.create", classmethod(fake_create))

    app = FastAPI()
    async with _lifespan(app, dev=True):
        client = TestClient(app)
        assert client.get("/fake-module-ping").json() == {"ok": True}


async def test_lifespan_non_dev_uses_the_non_dev_service_name(tmp_path, monkeypatch):
    # Avoids real Hub.create(dev=False), which would touch BLE/RF hardware -
    # only lifespan.py's own service-naming logic is under test here.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    monkeypatch.setattr("api.lifespan.ZeroconfManager", FakeZeroconfManager)
    monkeypatch.setattr("api.lifespan.run_migrations", lambda: None)

    async def fake_create(cls, **kwargs):
        return cls()

    monkeypatch.setattr("api.lifespan.Hub.create", classmethod(fake_create))

    async with _lifespan(FastAPI(), dev=False) as _:
        pass

    zeroconf = FakeZeroconfManager.instances[-1]
    assert zeroconf.registered_name == "Test-Instance"
