import json

from fastapi import FastAPI

from Api.lifespan import _lifespan, _load_ha_credentials, _load_rf_addresses


class FakeZeroconfManager:
    instances = []

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


async def test_lifespan_dev_yields_the_hub_pieces(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    monkeypatch.setattr("Api.lifespan.ZeroconfManager", FakeZeroconfManager)

    async with _lifespan(FastAPI(), dev=True) as state:
        assert set(state.keys()) == {
            "status_store", "keymap_resolver", "scene_manager",
            "command_dispatcher", "ble_keyboard", "ir_manager",
        }
        assert state["status_store"] is not None
        assert state["scene_manager"] is not None
        assert state["ble_keyboard"] is None  # dev mode skips hardware
        assert state["ir_manager"] is None

    zeroconf = FakeZeroconfManager.instances[-1]
    assert zeroconf.registered_name == "Test-Instance-Dev"
    assert zeroconf.unregistered is True


async def test_lifespan_mounts_module_routers_onto_the_app(tmp_path, monkeypatch):
    from fastapi import APIRouter

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    monkeypatch.setattr("Api.lifespan.ZeroconfManager", FakeZeroconfManager)

    class FakeExecutorWithRouter:
        name = "fake"

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

    monkeypatch.setattr("Api.lifespan.Hub.create", classmethod(fake_create))

    app = FastAPI()
    async with _lifespan(app, dev=True):
        paths = [route.path for route in app.routes]
        assert "/fake-module-ping" in paths


async def test_lifespan_non_dev_uses_the_non_dev_service_name(tmp_path, monkeypatch):
    # Avoids real Hub.create(dev=False), which would touch BLE/RF hardware -
    # only lifespan.py's own service-naming logic is under test here.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    monkeypatch.setattr("Api.lifespan.ZeroconfManager", FakeZeroconfManager)

    async def fake_create(cls, **kwargs):
        return cls()

    monkeypatch.setattr("Api.lifespan.Hub.create", classmethod(fake_create))

    async with _lifespan(FastAPI(), dev=False) as _:
        pass

    zeroconf = FakeZeroconfManager.instances[-1]
    assert zeroconf.registered_name == "Test-Instance"
