from enum import StrEnum


class CommandType(StrEnum):
    IR = "ir"
    BLUETOOTH = "bluetooth"
    NETWORK = "network"
    SCRIPT = "script"
    INTEGRATION = "integration"