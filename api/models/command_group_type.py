from enum import StrEnum


class CommandGroupType(StrEnum):
    VOLUME  = "volume"
    NAVIGATION = "navigation"
    TRANSPORT = "transport"
    COLORED_BUTTONS = "colored_buttons"
    CHANNEL = "channel"
    POWER = "power"
    NUMERIC = "numeric"
    INPUT = "input"
    OTHER = "other"