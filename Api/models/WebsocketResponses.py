from enum import Enum

from pydantic import BaseModel


class WebsocketBleCommand(str, Enum):
    ADVERTISE = "advertise"
    CONNECT = "connect"
    DEVICES = "devices"

class WebsocketBleAdvertisementResponse(BaseModel):
    success: bool = True

class BleDevice(BaseModel):
    name: str = ""
    address: str = ""
    connected: bool = False
    paired: bool = False

class WebsocketBleDeviceResponse(BaseModel):
    devices: list[BleDevice]

class WebsocketIrResponse(str, Enum):
    PRESS_KEY = "press_key"
    REPEAT_KEY = "repeat_key"
    SHORT_CODE = "short_code"
    DONE = "done"
    CANCELLED = "cancelled"
    TOO_MANY_RETRIES = "too_many_retries"