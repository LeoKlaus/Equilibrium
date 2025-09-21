from enum import Enum

class IntegrationAction(str, Enum):
    TOGGLE_LIGHT = "toggle_light"
    BRIGHTNESS_UP = "brightness_up"
    BRIGHTNESS_DOWN = "brightness_down"