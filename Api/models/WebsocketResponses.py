from enum import Enum

from sqlmodel import SQLModel


class WebsocketBleCommand(str, Enum):
    ADVERTISE = "advertise"
    CONNECT = "connect"
    DEVICES = "devices"

class WebsocketBleAdvertisementResponse(SQLModel):
    success: bool = True

class BleDevice(SQLModel):
    name: str = ""
    address: str = ""
    connected: bool = False
    paired: bool = False

class WebsocketBleDeviceResponse(SQLModel):
    devices: list[BleDevice]

class WebsocketIrResponse(str, Enum):
    PRESS_KEY = "press_key"
    REPEAT_KEY = "repeat_key"
    SHORT_CODE = "short_code"
    DONE = "done"
    CANCELLED = "cancelled"
    TOO_MANY_RETRIES = "too_many_retries"