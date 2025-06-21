from enum import Enum


class CommandType(str, Enum):
    IR = "ir"
    BLUETOOTH = "bluetooth"
    NETWORK = "network"
    SCRIPT = "script"