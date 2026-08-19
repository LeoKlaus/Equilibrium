from fastapi import APIRouter
from starlette.requests import Request

from Api.models.ModuleManifest import ModulesManifestResponse
from Api.models.Status import StatusReport
from Hub.StatusStore import StatusStore

router = APIRouter(
    prefix="/system",
    tags=["System"],
    responses={404: {"description": "Not found"}}
)

@router.get("/status", tags=["System"], response_model=StatusReport)
def get_current_system_status(request: Request) -> StatusReport:
    status_store: StatusStore = request.state.status_store

    return status_store.status

@router.get(
    "/modules",
    tags=["System"],
    response_model=ModulesManifestResponse,
    description="Lists every registered module's name, capabilities, and endpoint paths, "
                "so a client can discover what's available without hardcoding routes.",
)
def get_modules_manifest(request: Request) -> ModulesManifestResponse:
    return ModulesManifestResponse(modules=request.state.modules_manifest)