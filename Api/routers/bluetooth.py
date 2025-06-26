from fastapi import APIRouter
from starlette.requests import Request

from Api.models.WebsocketResponses import BleDevice
from RemoteController.RemoteController import RemoteController

router = APIRouter(
    prefix="/bluetooth",
    tags=["Bluetooth Devices"],
    responses={404: {"description": "Not found"}}
)

@router.get("/devices", tags=["Bluetooth Devices"], response_model=list[BleDevice])
async def get_connected_ble_devices(request: Request) -> list[BleDevice]:
    controller: RemoteController = request.state.controller
    return await controller.get_ble_devices()

@router.post("/start_advertisement", tags=["Bluetooth Devices"])
async def start_ble_discovery(request: Request):
    controller: RemoteController = request.state.controller
    await controller.start_ble_advertisement()
    return {"success": True}

@router.post("/start_pairing", tags=["Bluetooth Devices"], description="Will initiate pairing with all connected bluetooth devices that are not currently paired. This is may be necessary for some devices (notably Apple TVs).")
async def start_ble_pairing(request: Request):
    controller: RemoteController = request.state.controller
    await controller.start_ble_pairing()
    return {"success": True}

@router.post("/connect/{mac_address}", tags=["Bluetooth Devices"])
async def connect_ble_device(mac_address: str, request: Request):
    controller: RemoteController = request.state.controller
    await controller.ble_connect(mac_address)
    return {"success": True}

@router.post("/disconnect", tags=["Bluetooth Devices"])
async def disconnect_ble_devices(request: Request):
    controller: RemoteController = request.state.controller
    await controller.ble_disconnect()
    return {"success": True}
