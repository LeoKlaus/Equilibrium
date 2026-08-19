from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from Api.models.WebsocketResponses import BleDevice
from BleKeyboard.BleKeyboard import BleKeyboard

router = APIRouter(
    prefix="/bluetooth",
    tags=["Bluetooth Devices"],
    responses={404: {"description": "Not found"}}
)


def _get_ble_keyboard(request: Request) -> BleKeyboard:
    ble_keyboard: BleKeyboard | None = request.state.ble_keyboard
    if ble_keyboard is None:
        raise HTTPException(status_code=503, detail="BLE is not available (dev mode or no adapter configured)")
    return ble_keyboard


@router.get("/devices", tags=["Bluetooth Devices"], response_model=list[BleDevice])
async def get_connected_ble_devices(request: Request) -> list[BleDevice]:
    return await _get_ble_keyboard(request).devices

@router.post("/start_advertisement", tags=["Bluetooth Devices"])
async def start_ble_discovery(request: Request):
    await _get_ble_keyboard(request).advertise()
    return {"success": True}

@router.post("/start_pairing", tags=["Bluetooth Devices"], description="Will initiate pairing with all connected bluetooth devices that are not currently paired. This is may be necessary for some devices (notably Apple TVs).")
async def start_ble_pairing(request: Request):
    await _get_ble_keyboard(request).initiate_pairing()
    return {"success": True}

@router.post("/connect/{mac_address}", tags=["Bluetooth Devices"])
async def connect_ble_device(mac_address: str, request: Request):
    await _get_ble_keyboard(request).connect(mac_address)
    return {"success": True}

@router.post("/disconnect", tags=["Bluetooth Devices"])
async def disconnect_ble_devices(request: Request):
    await _get_ble_keyboard(request).disconnect()
    return {"success": True}
