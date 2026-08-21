from fastapi import APIRouter

from api.dependencies import ModulesManifestDep, StatusStoreDep
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