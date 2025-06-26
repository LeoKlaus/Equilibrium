from enum import Enum


class RemoteButton(str, Enum):
    # Power
    POWER_TOGGLE = "power_toggle"
    POWER_OFF = "power_off"
    POWER_ON = "power_on"
    # Volume
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    MUTE = "mute"
    # Navigation
    DIRECTION_UP = "direction_up"
    DIRECTION_DOWN = "direction_down"
    DIRECTION_LEFT = "direction_left"
    DIRECTION_RIGHT = "direction_right"
    SELECT = "select"
    GUIDE = "guide"
    BACK = "back"
    MENU = "menu"
    HOME = "home"
    EXIT = "exit"
    # Transport
    PLAY = "play"
    PAUSE = "pause"
    PLAYPAUSE = "playpause"
    STOP = "stop"
    FAST_FORWARD = "fast_forward"
    REWIND = "rewind"
    NEXT_TRACK = "next_track"
    PREVIOUS_TRACK = "previous_track"
    RECORD = "record"
    CHANNEL_UP = "channel_up"
    CHANNEL_DOWN = "channel_down"
    # Colored buttons
    GREEN = "green"
    RED = "red"
    BLUE = "blue"
    YELLOW = "yellow"
    # Numbers
    NUMBER_ZERO = "number_zero"
    NUMBER_ONE = "number_one"
    NUMBER_TWO = "number_two"
    NUMBER_THREE = "number_three"
    NUMBER_FOUR = "number_four"
    NUMBER_FIVE = "number_five"
    NUMBER_SIX = "number_six"
    NUMBER_SEVEN = "number_seven"
    NUMBER_EIGHT = "number_eight"
    NUMBER_NINE = "number_nine"
    # Integration
    BRIGHTNESS_UP = "brightness_up"
    BRIGHTNESS_DOWN = "brightness_down"
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    # Fallback
    OTHER = "other"