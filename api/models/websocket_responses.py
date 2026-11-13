from enum import StrEnum

from sqlmodel import SQLModel


class WebsocketBleCommand(StrEnum):
    ADVERTISE = "advertise"
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    DEVICES = "devices"

class WebsocketBleSuccessResponse(SQLModel):
    success: bool = True

class BleDevice(SQLModel):
    name: str = ""
    address: str = ""
    connected: bool = False
    paired: bool = False

class WebsocketBleDeviceResponse(SQLModel):
    devices: list[BleDevice]

class WebsocketIrResponse(StrEnum):
    PRESS_KEY = "press_key"
    REPEAT_KEY = "repeat_key"
    SHORT_CODE = "short_code"
    DONE = "done"
    CANCELLED = "cancelled"
    TOO_MANY_RETRIES = "too_many_retries"