from enum import StrEnum
from typing import Literal

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

class BleAdapter(SQLModel):
    powered: bool = False
    discoverable: bool = False
    pairable: bool = False
    advertising: bool = False

class BluetoothSnapshotMessage(SQLModel):
    """Sent once when a client connects to /ws/bluetooth."""
    type: Literal["snapshot"] = "snapshot"
    bluez_available: bool
    adapter: BleAdapter | None
    devices: list[BleDevice]

class BluetoothAvailabilityMessage(SQLModel):
    """bluetoothd appeared or went away."""
    type: Literal["availability"] = "availability"
    available: bool

class BluetoothAdapterMessage(SQLModel):
    type: Literal["adapter"] = "adapter"
    adapter: BleAdapter | None  # None: the adapter is gone

class BluetoothDeviceMessage(SQLModel):
    type: Literal["device"] = "device"
    address: str
    device: BleDevice | None  # None: BlueZ forgot the device

BluetoothMessage = (
    BluetoothSnapshotMessage | BluetoothAvailabilityMessage | BluetoothAdapterMessage | BluetoothDeviceMessage
)

class WebsocketIrResponse(StrEnum):
    PRESS_KEY = "press_key"
    REPEAT_KEY = "repeat_key"
    SHORT_CODE = "short_code"
    DONE = "done"
    CANCELLED = "cancelled"
    TOO_MANY_RETRIES = "too_many_retries"