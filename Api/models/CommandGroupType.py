from enum import Enum


class CommandGroupType(str, Enum):
    VOLUME  = "volume"
    NAVIGATION = "navigation"
    TRANSPORT = "transport"
    COLORED_BUTTONS = "colored_buttons"
    CHANNEL = "channel"
    POWER = "power"
    NUMERIC = "numeric"
    OTHER = "other"