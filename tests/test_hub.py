import asyncio
import json
from typing import ClassVar

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from Api.models.Command import Command
from Api.models.CommandGroupType import CommandGroupType
from Api.models.CommandType import CommandType
from Api.models.RemoteButton import RemoteButton
from hub.event_bus import Event
from hub.hub import Hub


class FakeInputSource:
    router = None
    capabilities: ClassVar[list[str]] = []

    def __init__(self, name: str = "fake"):
        self.name = name
        self.started = False
        self.stopped = False
        self._stop_event = asyncio.Event()

    async def start(self, bus) -> None:
        self.started = True
        await self._stop_event.wait()

    def stop(self) -> None:
        self.stopped = True
        self._stop_event.set()


class FakeInputSourceWithoutStop:
    """No stop() - only asyncio cancellation can end its task."""

    router = None
    capabilities: ClassVar[list[str]] = []

    def __init__(self, name: str = "fake-no-stop"):
        self.name = name
        self.started = False

    async def start(self, bus) -> None:
        self.started = True
        await asyncio.Event().wait()


class FakeExecutor:
    router = None
    capabilities: ClassVar[list[str]] = []

    def __init__(self, name: str):
        self.name = name
        self.calls: list[tuple] = []

    async def execute(self, directive, command) -> None:
        self.calls.append((directive, command))


class FakeBleExecutor:
    """Also duck-types the BLE-specific surface SceneManager/InputRouter
    need beyond the plain ActionExecutor interface."""

    router = None
    capabilities: ClassVar[list[str]] = []

    def __init__(self):
        self.name = "bluetooth"
        self.calls = []

    async def execute(self, directive, command) -> None:
        self.calls.append(("execute", directive, command))

    async def connect(self, address) -> None:
        self.calls.append(("connect", address))

    async def disconnect(self, address=None) -> None:
        self.calls.append(("disconnect", address))

    async def register_services(self) -> None:
        self.calls.append(("register_services",))

    async def unregister_services(self) -> None:
        self.calls.append(("unregister_services",))

    def release_keys(self) -> None:
        self.calls.append(("release_keys",))

    def release_media_keys(self) -> None:
        self.calls.append(("release_media_keys",))


class FakeIrExecutor:
    router = None
    capabilities: ClassVar[list[str]] = []

    def __init__(self):
        self.name = "ir"
        self.calls = []
        self.stop_repeating_calls = 0

    async def execute(self, directive, command) -> None:
        self.calls.append((directive, command))

    def stop_repeating(self) -> None:
        self.stop_repeating_calls += 1


def test_register_executor_is_keyed_by_name():
    hub = Hub()
    executor = FakeExecutor("ir")

    hub.register_executor(executor)

    assert hub.executors == {"ir": executor}


def test_register_source_appends():
    hub = Hub()
    source_a = FakeInputSource("a")
    source_b = FakeInputSource("b")

    hub.register_source(source_a)
    hub.register_source(source_b)

    assert hub.sources == [source_a, source_b]


async def test_start_runs_the_bus_and_every_registered_source():
    hub = Hub()
    source_a = FakeInputSource("a")
    source_b = FakeInputSource("b")
    hub.register_source(source_a)
    hub.register_source(source_b)

    await hub.start()
    await asyncio.sleep(0)

    assert source_a.started is True
    assert source_b.started is True

    received = []

    async def handler(event: Event) -> None:
        received.append(event)

    hub.bus.subscribe("key_pressed", handler)
    await hub.bus.publish(Event("key_pressed", {}))
    await asyncio.sleep(0.01)
    assert len(received) == 1

    await hub.shutdown()


async def test_shutdown_calls_stop_on_sources_that_have_it():
    hub = Hub()
    source = FakeInputSource()
    hub.register_source(source)
    await hub.start()
    await asyncio.sleep(0)

    await hub.shutdown()

    assert source.stopped is True


async def test_shutdown_ends_sources_without_a_stop_method():
    hub = Hub()
    source = FakeInputSourceWithoutStop()
    hub.register_source(source)
    await hub.start()
    await asyncio.sleep(0)
    assert source.started is True

    await asyncio.wait_for(hub.shutdown(), timeout=1)


async def test_shutdown_leaves_no_tasks_running():
    hub = Hub()
    hub.register_source(FakeInputSource("a"))
    hub.register_source(FakeInputSourceWithoutStop("b"))
    await hub.start()
    await asyncio.sleep(0)

    await hub.shutdown()

    assert all(task.done() for task in hub._source_tasks)
    assert hub._bus_task.done()


async def test_shutdown_without_start_does_not_raise():
    hub = Hub()
    hub.register_source(FakeInputSource())

    await hub.shutdown()


def test_assemble_builds_the_pipeline():
    hub = Hub()

    hub.assemble()

    assert hub.status_store is not None
    assert hub.keymap_resolver is not None
    assert hub.command_dispatcher is not None
    assert hub.scene_manager is not None
    assert hub.input_router is not None


def test_assemble_is_idempotent():
    hub = Hub()
    hub.assemble()
    status_store, command_dispatcher = hub.status_store, hub.command_dispatcher

    hub.assemble()

    assert hub.status_store is status_store
    assert hub.command_dispatcher is command_dispatcher


def test_assemble_passes_the_executor_registry_to_command_dispatcher():
    hub = Hub()
    hub.register_executor(FakeExecutor("script"))

    hub.assemble()

    assert hub.command_dispatcher._executors is hub.executors


def test_assemble_pulls_ble_and_ir_from_the_registry():
    hub = Hub()
    ble = FakeBleExecutor()
    ir = FakeIrExecutor()
    hub.register_executor(ble)
    hub.register_executor(ir)

    hub.assemble()

    assert hub.scene_manager._ble_keyboard is ble
    assert hub.input_router._ble_keyboard is ble
    assert hub.input_router._ir_manager is ir


def test_assemble_works_with_no_ble_or_ir_registered():
    hub = Hub()

    hub.assemble()

    assert hub.scene_manager._ble_keyboard is None
    assert hub.input_router._ble_keyboard is None
    assert hub.input_router._ir_manager is None


async def test_start_calls_assemble_automatically():
    hub = Hub()

    await hub.start()

    assert hub.input_router is not None
    await hub.shutdown()


async def test_full_pipeline_from_bus_event_to_executor(db_engine, tmp_path, monkeypatch):
    # Proves assemble()'s wiring is actually correct end to end: a raw
    # key_pressed event reaches the right executor via the real
    # KeymapResolver/CommandDispatcher/InputRouter, not just that the
    # right objects got constructed.
    monkeypatch.setattr("hub.keymap_resolver.engine", db_engine)
    (tmp_path / "keymap_scenes.json").write_text(json.dumps({}))
    (tmp_path / "keymap_default.json").write_text(json.dumps({"Play": 1}))

    with Session(db_engine) as session:
        session.add(Command(
            name="Play",
            button=RemoteButton.PLAY,
            type=CommandType.IR,
            command_group=CommandGroupType.TRANSPORT,
            ir_action=[100, 200],
        ))
        session.commit()

    hub = Hub(config_dir=str(tmp_path))
    ir = FakeIrExecutor()
    hub.register_executor(ir)
    hub.assemble()
    hub.keymap_resolver.load_key_map()

    bus_task = asyncio.create_task(hub.bus.run())
    try:
        await hub.bus.publish(Event("key_pressed", {"button": "Play"}))

        for _ in range(20):
            if ir.calls:
                break
            await asyncio.sleep(0.01)

        assert len(ir.calls) == 1
        _, command = ir.calls[0]
        assert command.name == "Play"
    finally:
        bus_task.cancel()


class FakeModuleWithRouter:
    capabilities: ClassVar[list[str]] = []

    def __init__(self, name: str = "with-router", path: str = "/fake-ping"):
        self.name = name
        self.router = APIRouter()

        @self.router.get(path)
        def ping():
            return {"ok": True}

    async def start(self, bus) -> None:
        pass

    async def execute(self, directive, command) -> None:
        pass


def test_mount_routers_includes_routers_from_sources_and_executors():
    hub = Hub()
    source = FakeModuleWithRouter("source", "/fake-source-ping")
    executor = FakeModuleWithRouter("executor", "/fake-executor-ping")
    hub.register_source(source)
    hub.register_executor(executor)

    app = FastAPI()
    hub.mount_routers(app)

    paths = [route.path for route in app.routes]
    assert "/fake-source-ping" in paths
    assert "/fake-executor-ping" in paths


def test_mount_routers_skips_modules_without_a_router():
    hub = Hub()
    hub.register_source(FakeInputSource())
    hub.register_executor(FakeExecutor("ir"))

    app = FastAPI()
    routes_before = len(app.routes)
    hub.mount_routers(app)

    assert len(app.routes) == routes_before


def test_mount_routers_endpoint_is_actually_callable():
    hub = Hub()
    hub.register_executor(FakeModuleWithRouter("with-router", "/fake-ping"))

    app = FastAPI()
    hub.mount_routers(app)

    with TestClient(app) as client:
        response = client.get("/fake-ping")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_build_modules_manifest_includes_name_capabilities_and_endpoints():
    hub = Hub()
    ble = FakeBleExecutor()
    ble.capabilities = ["pairing", "device_list"]
    ble.router = APIRouter()

    @ble.router.get("/bluetooth/devices")
    def devices():
        return []

    hub.register_executor(ble)

    manifest = hub.build_modules_manifest()

    assert manifest == [{
        "name": "bluetooth",
        "capabilities": ["pairing", "device_list"],
        "endpoints": {"devices": "/bluetooth/devices"},
    }]


def test_build_modules_manifest_empty_endpoints_for_modules_without_a_router():
    hub = Hub()
    hub.register_executor(FakeExecutor("network"))

    manifest = hub.build_modules_manifest()

    assert manifest == [{"name": "network", "capabilities": [], "endpoints": {}}]


def test_build_modules_manifest_covers_sources_and_executors():
    hub = Hub()
    hub.register_source(FakeInputSource("rf"))
    hub.register_executor(FakeExecutor("ir"))

    manifest = hub.build_modules_manifest()

    assert {module["name"] for module in manifest} == {"rf", "ir"}
