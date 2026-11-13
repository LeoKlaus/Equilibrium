import asyncio
import time
from collections import namedtuple
from typing import ClassVar

import pytest
from sqlalchemy import create_engine, text

from api.health import HealthChecker
from api.models.health import ComponentHealth, ComponentStatus, HealthStatus
from hub.health import aggregate, run_check
from hub.hub import Hub

OK, DEGRADED, DOWN, NOT_CONFIGURED = (
    ComponentStatus.OK, ComponentStatus.DEGRADED, ComponentStatus.DOWN, ComponentStatus.NOT_CONFIGURED,
)


def _component(name: str, status: ComponentStatus, detail: str | None = None) -> ComponentHealth:
    return ComponentHealth(name=name, status=status, detail=detail)


# --- run_check ---------------------------------------------------------------

async def test_run_check_passes_the_result_through():
    async def check():
        return _component("x", OK, "fine")

    assert await run_check("x", check) == _component("x", OK, "fine")


async def test_run_check_turns_a_timeout_into_down():
    async def check():
        await asyncio.sleep(10)

    result = await run_check("slow", check, timeout=0.01)

    assert result.name == "slow"
    assert result.status == DOWN
    assert result.detail == "Health check timed out after 0.01s"


async def test_run_check_turns_an_exception_into_down_instead_of_raising():
    async def check():
        raise RuntimeError("boom")

    result = await run_check("broken", check)

    assert result.name == "broken"
    assert result.status == DOWN
    assert result.detail == "Health check failed: RuntimeError: boom"


# --- aggregate ---------------------------------------------------------------

def test_aggregate_ok_when_everything_is_ok():
    assert aggregate([_component("a", OK), _component("b", OK)]) == HealthStatus.OK


def test_aggregate_not_configured_never_counts_against_the_hub():
    assert aggregate([_component("a", OK), _component("rf", NOT_CONFIGURED)]) == HealthStatus.OK


def test_aggregate_degraded_if_any_component_is_degraded():
    assert aggregate([_component("a", OK), _component("b", DEGRADED)]) == HealthStatus.DEGRADED


def test_aggregate_a_non_critical_down_is_only_degraded():
    assert aggregate([_component("a", OK), _component("rf", DOWN)]) == HealthStatus.DEGRADED


def test_aggregate_a_critical_down_is_down():
    components = [_component("database", DOWN), _component("rf", OK)]
    assert aggregate(components, critical=frozenset({"database"})) == HealthStatus.DOWN


def test_aggregate_a_critical_that_is_merely_degraded_is_degraded():
    components = [_component("database", DEGRADED)]
    assert aggregate(components, critical=frozenset({"database"})) == HealthStatus.DEGRADED


# --- Hub.check_health --------------------------------------------------------

class FakeSource:
    router = None
    capabilities: ClassVar[list[str]] = []

    def __init__(self, name: str, behavior: str = "run"):
        self.name = name
        self.behavior = behavior

    async def start(self, bus) -> None:
        if self.behavior == "crash":
            raise RuntimeError("SPI exploded")
        if self.behavior == "return":
            return
        await asyncio.Event().wait()


class FakeReportingSource(FakeSource):
    async def health(self) -> ComponentHealth:
        return _component(self.name, NOT_CONFIGURED, "explained by the module")


class FakeExecutor:
    router = None
    capabilities: ClassVar[list[str]] = []

    def __init__(self, name: str):
        self.name = name

    async def execute(self, directive, command) -> None:
        pass


class FakeReportingExecutor(FakeExecutor):
    async def health(self) -> ComponentHealth:
        return _component(self.name, DEGRADED, "reported by the module")


async def _started_hub(*sources, executors=()) -> Hub:
    hub = Hub()
    for source in sources:
        hub.register_source(source)
    for executor in executors:
        hub.register_executor(executor)
    await hub.start()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    return hub


async def test_check_health_a_running_source_without_a_health_hook_is_ok():
    hub = await _started_hub(FakeSource("rf"))
    try:
        assert await hub.check_health() == [_component("rf", OK)]
    finally:
        await hub.shutdown()


async def test_check_health_a_crashed_source_task_is_down_with_the_exception():
    hub = await _started_hub(FakeSource("rf", behavior="crash"))
    try:
        [result] = await hub.check_health()
    finally:
        await hub.shutdown()

    assert result.name == "rf"
    assert result.status == DOWN
    assert result.detail == "Task crashed: RuntimeError: SPI exploded"


async def test_shutdown_tolerates_a_source_that_already_crashed(caplog):
    healthy = FakeSource("healthy")
    hub = await _started_hub(FakeSource("rf", behavior="crash"), healthy)

    await hub.shutdown()  # must not raise

    assert "A hub task had crashed before shutdown" in caplog.text
    assert "SPI exploded" in caplog.text  # its traceback finally gets logged


async def test_check_health_a_crash_outranks_what_the_module_would_report():
    class CrashingButCheerful(FakeSource):
        async def health(self) -> ComponentHealth:
            return _component(self.name, OK)

    hub = await _started_hub(CrashingButCheerful("rf", behavior="crash"))
    try:
        [result] = await hub.check_health()
    finally:
        await hub.shutdown()

    assert result.status == DOWN


async def test_check_health_a_source_that_returned_is_down_unless_the_module_explains_it():
    hub = await _started_hub(FakeSource("silent", behavior="return"))
    try:
        [result] = await hub.check_health()
    finally:
        await hub.shutdown()

    assert result.status == DOWN
    assert result.detail == "Task exited unexpectedly"


async def test_check_health_a_module_can_explain_an_early_return():
    hub = await _started_hub(FakeReportingSource("rf", behavior="return"))
    try:
        assert await hub.check_health() == [_component("rf", NOT_CONFIGURED, "explained by the module")]
    finally:
        await hub.shutdown()


async def test_check_health_only_includes_executors_that_can_report():
    hub = await _started_hub(executors=[FakeExecutor("network"), FakeReportingExecutor("integration")])
    try:
        assert await hub.check_health() == [_component("integration", DEGRADED, "reported by the module")]
    finally:
        await hub.shutdown()


async def test_check_health_a_module_whose_health_raises_is_reported_down_not_a_500():
    class Throwing(FakeExecutor):
        async def health(self) -> ComponentHealth:
            raise ValueError("bad state")

    hub = await _started_hub(executors=[Throwing("integration")])
    try:
        [result] = await hub.check_health()
    finally:
        await hub.shutdown()

    assert result.status == DOWN
    assert result.detail == "Health check failed: ValueError: bad state"


# --- HealthChecker -----------------------------------------------------------

class FakeHub:
    def __init__(self, components: list[ComponentHealth] | None = None):
        self._components = components or []

    async def check_health(self) -> list[ComponentHealth]:
        return self._components


class FakeZeroconf:
    def __init__(self, ip: str | None = "192.168.1.5", name: str = "Equilibrium", port: int = 8000):
        self.advertised_ip = ip
        self.advertised_name = name
        self.advertised_port = port


@pytest.fixture
def healthy_env(db_engine, monkeypatch, tmp_path):
    """A working database, plenty of free space and an unchanged IP."""
    monkeypatch.setattr("api.health.engine", db_engine)
    monkeypatch.setattr("api.health.get_lan_ip", lambda: "192.168.1.5")
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr("api.health.shutil.disk_usage", lambda path: Usage(10**12, 10**11, 5 * 1024**3))
    return tmp_path


def _checker(config_dir, hub=None, zeroconf=None, started_at=None) -> HealthChecker:
    return HealthChecker(
        hub=hub or FakeHub(),  # type: ignore[arg-type]  # duck-typed fake
        zeroconf=zeroconf or FakeZeroconf(),  # type: ignore[arg-type]  # duck-typed fake
        started_at=time.monotonic() if started_at is None else started_at,
        config_dir=str(config_dir),
    )


def _by_name(report) -> dict[str, ComponentHealth]:
    return {component.name: component for component in report.components}


async def test_report_is_ok_when_everything_works(healthy_env):
    report = await _checker(healthy_env).report()

    assert report.status == HealthStatus.OK
    assert [c.name for c in report.components] == ["database", "storage", "zeroconf"]
    assert all(c.status == OK for c in report.components)


async def test_report_includes_the_hubs_modules_after_the_infrastructure(healthy_env):
    hub = FakeHub([_component("rf", NOT_CONFIGURED, "no remote paired")])

    report = await _checker(healthy_env, hub=hub).report()

    assert [c.name for c in report.components] == ["database", "storage", "zeroconf", "rf"]
    assert report.status == HealthStatus.OK  # not_configured doesn't count


async def test_report_a_down_module_degrades_but_does_not_down_the_hub(healthy_env):
    hub = FakeHub([_component("rf", DOWN, "RF hardware is not responding")])

    report = await _checker(healthy_env, hub=hub).report()

    assert report.status == HealthStatus.DEGRADED


async def test_report_uptime_is_measured_from_started_at(healthy_env):
    report = await _checker(healthy_env, started_at=time.monotonic() - 125).report()

    assert report.uptime_seconds == 125


async def test_database_down_makes_the_whole_hub_down(healthy_env, monkeypatch):
    broken = create_engine("sqlite:////nonexistent-directory/db.sqlite")
    monkeypatch.setattr("api.health.engine", broken)

    report = await _checker(healthy_env).report()

    database = _by_name(report)["database"]
    assert database.status == DOWN
    assert database.detail is not None
    assert database.detail.startswith("Query failed: OperationalError:")
    assert "unable to open database file" in database.detail
    assert "sqlalche.me" not in database.detail
    assert report.status == HealthStatus.DOWN


async def test_database_corrupted_after_startup_is_down(healthy_env, monkeypatch):
    db_file = healthy_env / "live.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE t (id INTEGER)"))
    with engine.connect() as connection:  # warm the pool
        connection.execute(text("SELECT id FROM t")).all()
    monkeypatch.setattr("api.health.engine", engine)

    with open(db_file, "r+b") as file:
        file.write(b"this is definitely not a sqlite database " * 200)

    database = _by_name(await _checker(healthy_env).report())["database"]

    assert database.status == DOWN
    assert database.detail is not None
    assert "file is not a database" in database.detail


@pytest.mark.parametrize(("free", "expected"), [
    (5 * 1024**3, OK),
    (99 * 1024**2, DEGRADED),
    (9 * 1024**2, DOWN),
])
async def test_storage_status_by_free_space(healthy_env, monkeypatch, free, expected):
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr("api.health.shutil.disk_usage", lambda path: Usage(10**12, 0, free))

    storage = _by_name(await _checker(healthy_env).report())["storage"]

    assert storage.status == expected


async def test_storage_reports_free_space_in_a_readable_unit(healthy_env, monkeypatch):
    storage = _by_name(await _checker(healthy_env).report())["storage"]
    assert storage.detail == "5.0 GB free"

    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr("api.health.shutil.disk_usage", lambda path: Usage(10**12, 0, 42 * 1024**2))
    storage = _by_name(await _checker(healthy_env).report())["storage"]
    assert storage.detail == "Only 42 MB free"


async def test_storage_not_writable_is_down_even_with_plenty_of_space(healthy_env, monkeypatch):
    monkeypatch.setattr("api.health.os.access", lambda path, mode: False)

    storage = _by_name(await _checker(healthy_env).report())["storage"]

    assert storage.status == DOWN
    assert storage.detail is not None
    assert "not writable" in storage.detail


async def test_zeroconf_ok_reports_what_is_advertised(healthy_env):
    zeroconf = _by_name(await _checker(healthy_env).report())["zeroconf"]

    assert zeroconf.status == OK
    assert zeroconf.detail == "Equilibrium at 192.168.1.5:8000"


async def test_zeroconf_not_registered_is_down(healthy_env):
    checker = _checker(healthy_env, zeroconf=FakeZeroconf(ip=None))

    zeroconf = _by_name(await checker.report())["zeroconf"]

    assert zeroconf.status == DOWN
    assert zeroconf.detail == "Service is not registered"


async def test_zeroconf_degraded_when_the_hosts_ip_changed_after_registration(healthy_env, monkeypatch):
    monkeypatch.setattr("api.health.get_lan_ip", lambda: "192.168.1.99")

    zeroconf = _by_name(await _checker(healthy_env).report())["zeroconf"]

    assert zeroconf.status == DEGRADED
    assert zeroconf.detail is not None
    assert "192.168.1.5" in zeroconf.detail
    assert "192.168.1.99" in zeroconf.detail


async def test_zeroconf_down_when_there_is_no_network_route(healthy_env, monkeypatch):
    def no_route():
        raise OSError(101, "Network is unreachable")

    monkeypatch.setattr("api.health.get_lan_ip", no_route)

    zeroconf = _by_name(await _checker(healthy_env).report())["zeroconf"]

    assert zeroconf.status == DOWN
    assert zeroconf.detail is not None
    assert zeroconf.detail.startswith("No network route:")
