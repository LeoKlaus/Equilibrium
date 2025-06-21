from enum import Enum


class DeviceType(str, Enum):
    DISPLAY = "display"         # Should receive input changes
    AMPLIFIER = "amplifier"     # Should be default for handling audio
    PLAYER = "player"           # Should be default for transport controls (play, pause, ff, etc.)
    INTEGRATION = "integration" # Device that isn't directly connected to media playback (smart lights, blinds, etc.)
    OTHER = "other"             # Device that doesn't match any of the above