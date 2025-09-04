TARGET_LENGTH = 6

KEY_TABLE = {
    "KEY_RESERVED": 0,
    "KEY_ESC": 41,
    "KEY_1": 30,
    "KEY_2": 31,
    "KEY_3": 32,
    "KEY_4": 33,
    "KEY_5": 34,
    "KEY_6": 35,
    "KEY_7": 36,
    "KEY_8": 37,
    "KEY_9": 38,
    "KEY_0": 39,
    "KEY_MINUS": 45,
    "KEY_EQUAL": 46,
    "KEY_BACKSPACE": 42,
    "KEY_TAB": 43,
    "KEY_Q": 20,
    "KEY_W": 26,
    "KEY_E": 8,
    "KEY_R": 21,
    "KEY_T": 23,
    "KEY_Y": 28,
    "KEY_U": 24,
    "KEY_I": 12,
    "KEY_O": 18,
    "KEY_P": 19,
    "KEY_LEFTBRACE": 47,
    "KEY_RIGHTBRACE": 48,
    "KEY_ENTER": 40,
    "KEY_LEFTCTRL": 224,
    "KEY_A": 4,
    "KEY_S": 22,
    "KEY_D": 7,
    "KEY_F": 9,
    "KEY_G": 10,
    "KEY_H": 11,
    "KEY_J": 13,
    "KEY_K": 14,
    "KEY_L": 15,
    "KEY_SEMICOLON": 51,
    "KEY_APOSTROPHE": 52,
    "KEY_GRAVE": 53,
    "KEY_LEFTSHIFT": 225,
    "KEY_BACKSLASH": 50,
    "KEY_Z": 29,
    "KEY_X": 27,
    "KEY_C": 6,
    "KEY_V": 25,
    "KEY_B": 5,
    "KEY_N": 17,
    "KEY_M": 16,
    "KEY_COMMA": 54,
    "KEY_DOT": 55,
    "KEY_SLASH": 56,
    "KEY_RIGHTSHIFT": 229,
    "KEY_KPASTERISK": 85,
    "KEY_LEFTALT": 226,
    "KEY_SPACE": 44,
    "KEY_CAPSLOCK": 57,
    "KEY_F1": 58,
    "KEY_F2": 59,
    "KEY_F3": 60,
    "KEY_F4": 61,
    "KEY_F5": 62,
    "KEY_F6": 63,
    "KEY_F7": 64,
    "KEY_F8": 65,
    "KEY_F9": 66,
    "KEY_F10": 67,
    "KEY_NUMLOCK": 83,
    "KEY_SCROLLLOCK": 71,
    "KEY_KP7": 95,
    "KEY_KP8": 96,
    "KEY_KP9": 97,
    "KEY_KPMINUS": 86,
    "KEY_KP4": 92,
    "KEY_KP5": 93,
    "KEY_KP6": 94,
    "KEY_KPPLUS": 87,
    "KEY_KP1": 89,
    "KEY_KP2": 90,
    "KEY_KP3": 91,
    "KEY_KP0": 98,
    "KEY_KPDOT": 99,
    "KEY_ZENKAKUHANKAKU": 148,
    "KEY_102ND": 100,
    "KEY_F11": 68,
    "KEY_F12": 69,
    "KEY_RO": 135,
    "KEY_KATAKANA": 146,
    "KEY_HIRAGANA": 147,
    "KEY_HENKAN": 138,
    "KEY_KATAKANAHIRAGANA": 136,
    "KEY_MUHENKAN": 139,
    "KEY_KPJPCOMMA": 140,
    "KEY_KPENTER": 88,
    "KEY_RIGHTCTRL": 228,
    "KEY_KPSLASH": 84,
    "KEY_SYSRQ": 70,
    "KEY_RIGHTALT": 230,
    "KEY_HOME": 74,
    "KEY_UP": 82,
    "KEY_PAGEUP": 75,
    "KEY_LEFT": 80,
    "KEY_RIGHT": 79,
    "KEY_END": 77,
    "KEY_DOWN": 81,
    "KEY_PAGEDOWN": 78,
    "KEY_INSERT": 73,
    "KEY_DELETE": 76,
    "KEY_MUTE": 239,
    "KEY_VOLUMEDOWN": 238,
    "KEY_VOLUMEUP": 237,
    "KEY_POWER": 102,
    "KEY_KPEQUAL": 103,
    "KEY_PAUSE": 72,
    "KEY_KPCOMMA": 133,
    "KEY_HANGEUL": 144,
    "KEY_HANJA": 145,
    "KEY_YEN": 137,
    "KEY_LEFTMETA": 227,
    "KEY_RIGHTMETA": 231,
    "KEY_COMPOSE": 101,
    "KEY_STOP": 243,
    "KEY_AGAIN": 121,
    "KEY_PROPS": 118,
    "KEY_UNDO": 122,
    "KEY_FRONT": 119,
    "KEY_COPY": 124,
    "KEY_OPEN": 116,
    "KEY_PASTE": 125,
    "KEY_FIND": 244,
    "KEY_CUT": 123,
    "KEY_HELP": 117,
    "KEY_CALC": 251,
    "KEY_SLEEP": 248,
    "KEY_WWW": 240,
    "KEY_COFFEE": 249,
    "KEY_BACK": 241,
    "KEY_FORWARD": 242,
    "KEY_EJECTCD": 236,
    "KEY_NEXTSONG": 235,
    "KEY_PLAYPAUSE": 232,
    "KEY_PREVIOUSSONG": 234,
    "KEY_STOPCD": 233,
    "KEY_REFRESH": 250,
    "KEY_EDIT": 247,
    "KEY_SCROLLUP": 245,
    "KEY_SCROLLDOWN": 246,
    "KEY_F13": 104,
    "KEY_F14": 105,
    "KEY_F15": 106,
    "KEY_F16": 107,
    "KEY_F17": 108,
    "KEY_F18": 109,
    "KEY_F19": 110,
    "KEY_F20": 111,
    "KEY_F21": 112,
    "KEY_F22": 113,
    "KEY_F23": 114,
    "KEY_F24": 115
}

MOD_KEYS = {
    "KEY_RIGHTMETA": 0,
    "KEY_RIGHTALT": 1,
    "KEY_RIGHTSHIFT": 2,
    "KEY_RIGHTCTRL": 3,
    "KEY_LEFTMETA": 4,
    "KEY_LEFTALT": 5,
    "KEY_LEFTSHIFT": 6,
    "KEY_LEFTCTRL": 7
}

MEDIA_KEYS = {
    "KEY_PLAY": [1, 0],             # 0xB0
    "KEY_PAUSE": [2, 0],            # 0xB1
    "KEY_PLAY_PAUSE": [4, 0],       # 0xCD
    "KEY_FAST_FORWARD": [8, 0],     # 0xB3
    "KEY_REWIND": [16, 0],          # 0xB4
    "KEY_NEXT_TRACK": [32, 0],      # 0xB5
    "KEY_PREVIOUS_TRACK": [64, 0],  # 0xB6
    "KEY_STOP": [128, 0],           # 0xB7
    "KEY_MENU": [0, 1],             # 0x40 (Home on Apple TV)
    "KEY_VOLUME_UP": [0, 2],        # 0xE9
    "KEY_VOLUME_DOWN": [0, 4],      # 0xEA
    "KEY_MUTE": [0, 8],             # 0xE2
    "KEY_POWER": [0, 16],           # 0x30
    "KEY_MENU_PICK": [0, 32],       # 0x32
    "KEY_AC_SEARCH": [0, 64],       # 0x221
    "KEY_AC_HOME": [0, 128]         # 0x223
}

mod_keys = 0b00000000
pressed_keys = []


def to_mod_key(key_str):
    if key_str in MOD_KEYS:
        return MOD_KEYS[key_str]
    else:
        return -1


def update_mod_keys(mod_key, value):
    global mod_keys
    bit_mask = 1 << (7 - mod_key)
    if value:
        mod_keys |= bit_mask
    else:
        mod_keys &= ~bit_mask


def to_ord_key(key_str):
    if key_str in KEY_TABLE:
        return KEY_TABLE[key_str]
    else:
        return -1


def update_ord_keys(ord_key, value):
    global pressed_keys
    if value == 0:
        pressed_keys.remove(ord_key)
    elif ord_key not in pressed_keys:
        pressed_keys.insert(0, ord_key)

    len_delta = TARGET_LENGTH - len(pressed_keys)
    if len_delta < 0:
        pressed_keys = pressed_keys[:len_delta]
    elif len_delta > 0:
        pressed_keys.extend([0] * len_delta)


def encode_keys():
    return [mod_keys, 0, *pressed_keys]


def create_keycode(ord_key_str: str | None = None, mod_key_str: str | None = None):
    """
    Create the key code for the given keys.
    :param ord_key_str: Key to be pressed (from KEY_TABLE)
    :param mod_key_str: Modifier key to be pressed (from MOD_KEYS)
    :return: The key code for the given keys
    """
    global pressed_keys, mod_keys

    pressed_keys = []
    mod_keys = 0b00000000

    if not ord_key_str and not mod_key_str:
        return [0, 0, 0, 0, 0, 0, 0, 0]

    mod_key = to_mod_key(mod_key_str)
    ord_key = to_ord_key(ord_key_str)

    if mod_key != -1:
        update_mod_keys(mod_key, 1)

    if ord_key != -1:
        update_ord_keys(ord_key, 1)

    return encode_keys()


def create_media_keycode(media_key_str: str | None = None):
    """
    Create the key code for the given keys.
    :param media_key_str: Key to be pressed (from KEY_TABLE)
    :return: The key code for the given keys
    """
    media_key = MEDIA_KEYS.get(media_key_str)
    if not media_key:
        return [0, 0]

    return [media_key[0], media_key[1]]
