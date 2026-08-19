from fastapi import APIRouter
from starlette.requests import Request

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