from fastapi import APIRouter

from api.dependencies import LogBroadcasterDep, ModulesManifestDep, StatusStoreDep
from api.models.log_line import LogsResponse
from api.models.module_manifest import ModulesManifestResponse
from api.models.status import StatusReport

router = APIRouter(
    prefix="/system",
    tags=["System"],
    responses={404: {"description": "Not found"}}
)

@router.get("/status", tags=["System"], response_model=StatusReport)
def get_current_system_status(status_store: StatusStoreDep) -> StatusReport:
    return status_store.status

@router.get(
    "/modules",
    tags=["System"],
    response_model=ModulesManifestResponse,
    description="Lists every registered module's name, capabilities, and endpoint paths, "
                "so a client can discover what's available without hardcoding routes.",
)
def get_modules_manifest(modules_manifest: ModulesManifestDep) -> ModulesManifestResponse:
    return ModulesManifestResponse(modules=modules_manifest)

@router.get(
    "/logs",
    tags=["System"],
    response_model=LogsResponse,
    description="Returns the most recently logged lines. To follow logs, "
                "use /ws/logs.",
)
def get_logs(log_broadcaster: LogBroadcasterDep, limit: int | None = None) -> LogsResponse:
    lines = list(log_broadcaster.backlog)
    if limit is not None:
        lines = lines[-limit:]
    return LogsResponse(lines=lines)