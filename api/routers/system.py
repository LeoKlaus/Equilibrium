from fastapi import APIRouter, Response, status

from api.dependencies import HealthCheckerDep, LogBroadcasterDep, ModulesManifestDep, StatusStoreDep
from api.models.health import HealthReport, HealthStatus
from api.models.log_line import LogsResponse
from api.models.module_manifest import ModuleManifestEntry, ModulesManifestResponse
from api.models.status import StatusReport

router = APIRouter(
    prefix="/system",
    tags=["System"],
    responses={404: {"description": "Not found"}}
)

@router.get("/status", response_model=StatusReport)
def get_current_system_status(status_store: StatusStoreDep) -> StatusReport:
    return status_store.status

@router.get(
    "/modules",
    response_model=ModulesManifestResponse,
    description="Lists every registered module's name, capabilities, and endpoint paths, "
                "so a client can discover what's available without hardcoding routes.",
)
def get_modules_manifest(modules_manifest: ModulesManifestDep) -> ModulesManifestResponse:
    return ModulesManifestResponse(modules=[ModuleManifestEntry.model_validate(module) for module in modules_manifest])

@router.get(
    "/logs",
    response_model=LogsResponse,
    description="Returns the most recently logged lines. To follow logs, "
                "use /ws/logs.",
)
def get_logs(log_broadcaster: LogBroadcasterDep, limit: int | None = None) -> LogsResponse:
    lines = list(log_broadcaster.backlog)
    if limit is not None:
        lines = lines[-limit:]
    return LogsResponse(lines=lines)

@router.get(
    "/health",
    response_model=HealthReport,
    responses={503: {"model": HealthReport, "description": "A critical component (the database) is down."}},
    description="State of individual hub components (where reported)."
                "Info: `degraded` (e.g. a hardware module is down) still returns 200,"
                "only failures send 503.",
)
async def get_health(health_checker: HealthCheckerDep, response: Response) -> HealthReport:
    report = await health_checker.report()
    if report.status == HealthStatus.DOWN:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report
