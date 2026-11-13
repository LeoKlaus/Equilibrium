from enum import StrEnum


class IntegrationAction(StrEnum):
    TOGGLE_LIGHT = "toggle_light"
    BRIGHTNESS_UP = "brightness_up"
    BRIGHTNESS_DOWN = "brightness_down"