import asyncio

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.log_broadcaster import LogBroadcaster
from api.models.health import ComponentHealth, ComponentStatus, HealthReport, HealthStatus
from api.models.log_line import LogLine
from api.routers import system


def _client_with_state(**state) -> TestClient:
    app = FastAPI()
    app.include_router(system.router)

    @app.middleware("http")
    async def inject_state(request: Request, call_next):
        for key, value in state.items():
            setattr(request.state, key, value)
        return await call_next(request)

    return TestClient(app)


def test_get_modules_manifest_returns_the_registered_modules():
    manifest = [
        {"name": "bluetooth", "capabilities": ["pairing"], "endpoints": {"devices": "/bluetooth/devices"}},
        {"name": "network", "capabilities": [], "endpoints": {}},
    ]
    client = _client_with_state(modules_manifest=manifest)

    response = client.get("/system/modules")

    assert response.status_code == 200
    assert response.json() == {"modules": manifest}


def test_get_modules_manifest_empty_when_nothing_registered():
    client = _client_with_state(modules_manifest=[])

    response = client.get("/system/modules")

    assert response.status_code == 200
    assert response.json() == {"modules": []}


def _line(message: str) -> LogLine:
    return LogLine(timestamp="12:00:00", level="INFO", logger="test", message=message, formatted=message)


async def test_get_logs_returns_the_backlog():
    broadcaster = LogBroadcaster(asyncio.get_running_loop())
    broadcaster.backlog.extend([_line("first"), _line("second")])
    client = _client_with_state(log_broadcaster=broadcaster)

    response = client.get("/system/logs")

    assert response.status_code == 200
    assert [line["message"] for line in response.json()["lines"]] == ["first", "second"]


async def test_get_logs_respects_limit():
    broadcaster = LogBroadcaster(asyncio.get_running_loop())
    broadcaster.backlog.extend([_line("first"), _line("second"), _line("third")])
    client = _client_with_state(log_broadcaster=broadcaster)

    response = client.get("/system/logs?limit=2")

    assert [line["message"] for line in response.json()["lines"]] == ["second", "third"]


async def test_get_logs_empty_backlog():
    client = _client_with_state(log_broadcaster=LogBroadcaster(asyncio.get_running_loop()))

    response = client.get("/system/logs")

    assert response.status_code == 200
    assert response.json() == {"lines": []}


class FakeHealthChecker:
    def __init__(self, report: HealthReport):
        self._report = report

    async def report(self) -> HealthReport:
        return self._report


def _report(status: HealthStatus, *components: ComponentHealth) -> HealthReport:
    return HealthReport(status=status, uptime_seconds=3725, components=list(components))


def test_get_health_ok_returns_200_with_the_report():
    report = _report(
        HealthStatus.OK,
        ComponentHealth(name="database", status=ComponentStatus.OK),
        ComponentHealth(name="rf", status=ComponentStatus.NOT_CONFIGURED, detail="No RF addresses configured"),
    )
    client = _client_with_state(health_checker=FakeHealthChecker(report))

    response = client.get("/system/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "uptime_seconds": 3725,
        "components": [
            {"name": "database", "status": "ok", "detail": None},
            {"name": "rf", "status": "not_configured", "detail": "No RF addresses configured"},
        ],
    }


def test_get_health_degraded_is_still_200_so_a_simple_monitor_only_alerts_on_real_outages():
    report = _report(
        HealthStatus.DEGRADED,
        ComponentHealth(name="bluetooth", status=ComponentStatus.DOWN, detail="Not connected to the system D-Bus"),
    )
    client = _client_with_state(health_checker=FakeHealthChecker(report))

    response = client.get("/system/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_get_health_down_is_503_but_still_carries_the_report():
    report = _report(
        HealthStatus.DOWN,
        ComponentHealth(name="database", status=ComponentStatus.DOWN, detail="Query failed: OperationalError"),
    )
    client = _client_with_state(health_checker=FakeHealthChecker(report))

    response = client.get("/system/health")

    assert response.status_code == 503
    assert response.json()["status"] == "down"
    assert response.json()["components"][0]["detail"] == "Query failed: OperationalError"
