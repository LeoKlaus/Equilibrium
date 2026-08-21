import json
from typing import ClassVar

import pytest

from hub.hub import Hub


class FakeRfInput:
    name = "rf"
    router = None
    capabilities: ClassVar[list[str]] = []

    def __init__(self, addresses, config_dir="config"):
        self.addresses = addresses
        self.config_dir = config_dir

    async def start(self, bus) -> None:
        pass


class FakeBleKeyboard:
    name = "bluetooth"
    router = None
    capabilities: ClassVar[list[str]] = []

    def __init__(self):
        pass

    @classmethod
    async def create(cls):
        return cls()

    async def execute(self, directive, command) -> None:
        pass

    async def connect(self, address: str) -> None:
        pass

    async def disconnect(self, address: str | None = None) -> None:
        pass

    async def register_services(self) -> None:
        pass

    async def unregister_services(self) -> None:
        pass

    def release_keys(self) -> None:
        pass

    def release_media_keys(self) -> None:
        pass


class FakeIrManager:
    name = "ir"
    router = None
    capabilities: ClassVar[list[str]] = []

    def stop_repeating(self) -> None:
        pass

    async def execute(self, directive, command) -> None:
        pass


class FakeHaManager:
    name = "integration"
    router = None
    capabilities: ClassVar[list[str]] = []

    def __init__(self, url, token):
        self.url = url
        self.token = token

    async def execute(self, directive, command) -> None:
        pass


class FakeNetworkExecutor:
    name = "network"
    router = None
    capabilities: ClassVar[list[str]] = []

    async def execute(self, directive, command) -> None:
        pass


class FakeScriptExecutor:
    name = "script"
    router = None
    capabilities: ClassVar[list[str]] = []

    def __init__(self, scripts_dir):
        self.scripts_dir = scripts_dir

    async def execute(self, directive, command) -> None:
        pass


@pytest.fixture
def patched_modules(monkeypatch):
    monkeypatch.setattr("hub.hub.RfInput", FakeRfInput)
    monkeypatch.setattr("hub.hub.BleKeyboard", FakeBleKeyboard)
    monkeypatch.setattr("hub.hub.IrManager", FakeIrManager)
    monkeypatch.setattr("hub.hub.HaManager", FakeHaManager)
    monkeypatch.setattr("hub.hub.NetworkExecutor", FakeNetworkExecutor)
    monkeypatch.setattr("hub.hub.ScriptExecutor", FakeScriptExecutor)


@pytest.fixture
def empty_config_dir(tmp_path):
    return str(tmp_path)


async def test_create_registers_hardware_modules_by_default(patched_modules, empty_config_dir):
    hub = await Hub.create(rf_addresses=[b"a", b"b"], config_dir=empty_config_dir)

    assert len(hub.sources) == 1
    assert isinstance(hub.sources[0], FakeRfInput)
    assert "bluetooth" in hub.executors
    assert "ir" in hub.executors


async def test_create_dev_skips_hardware_modules(patched_modules, empty_config_dir):
    hub = await Hub.create(dev=True, config_dir=empty_config_dir)

    assert hub.sources == []
    assert "bluetooth" not in hub.executors
    assert "ir" not in hub.executors


async def test_create_registers_ha_manager_when_configured(patched_modules, empty_config_dir):
    hub = await Hub.create(dev=True, ha_url="http://ha.local", ha_token="tok", config_dir=empty_config_dir)

    assert "integration" in hub.executors
    assert hub.executors["integration"].url == "http://ha.local"


async def test_create_skips_ha_manager_when_not_configured(patched_modules, empty_config_dir):
    hub = await Hub.create(dev=True, config_dir=empty_config_dir)

    assert "integration" not in hub.executors


async def test_create_always_registers_network_executor(patched_modules, empty_config_dir):
    hub = await Hub.create(dev=True, config_dir=empty_config_dir)

    assert "network" in hub.executors


async def test_create_skips_script_executor_by_default(patched_modules, empty_config_dir):
    hub = await Hub.create(dev=True, config_dir=empty_config_dir)

    assert "script" not in hub.executors


async def test_create_registers_script_executor_when_scripts_dir_given(patched_modules, empty_config_dir, tmp_path):
    scripts_dir = str(tmp_path / "scripts")

    hub = await Hub.create(dev=True, scripts_dir=scripts_dir, config_dir=empty_config_dir)

    assert "script" in hub.executors
    assert hub.executors["script"].scripts_dir == scripts_dir


async def test_create_warns_when_scripts_enabled(patched_modules, empty_config_dir, tmp_path, caplog):
    await Hub.create(dev=True, scripts_dir=str(tmp_path), config_dir=empty_config_dir)

    assert "arbitrary" in caplog.text.lower() or "enabled" in caplog.text.lower()


async def test_create_loads_the_default_keymap_when_present(patched_modules, tmp_path, db_engine, monkeypatch):
    monkeypatch.setattr("hub.keymap_resolver.engine", db_engine)
    (tmp_path / "keymap_scenes.json").write_text(json.dumps({}))
    (tmp_path / "keymap_default.json").write_text(json.dumps({"Play": 1}))

    hub = await Hub.create(dev=True, config_dir=str(tmp_path))

    from hub.keymap_resolver import SendDirective
    resolution = hub.keymap_resolver.resolve("Play")
    assert isinstance(resolution, SendDirective)


async def test_create_warns_and_continues_when_keymap_missing(patched_modules, empty_config_dir, caplog):
    hub = await Hub.create(dev=True, config_dir=empty_config_dir)  # should not raise

    assert hub.keymap_resolver.resolve("Play") is None
    assert "keymap_default" in caplog.text


async def test_create_assembles_the_pipeline(patched_modules, empty_config_dir):
    hub = await Hub.create(dev=True, config_dir=empty_config_dir)

    assert hub.status_store is not None
    assert hub.input_router is not None
