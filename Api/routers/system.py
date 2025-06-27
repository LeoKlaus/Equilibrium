from fastapi import APIRouter
from starlette.requests import Request

from Api.models.Status import StatusReport
from RemoteController.RemoteController import RemoteController

router = APIRouter(
    prefix="/system",
    tags=["System"],
    responses={404: {"description": "Not found"}}
)

@router.get("/status", tags=["System"], response_model=StatusReport)
def get_current_system_status(request: Request) -> StatusReport:
    controller: RemoteController = request.state.controller

    return controller.get_current_status()