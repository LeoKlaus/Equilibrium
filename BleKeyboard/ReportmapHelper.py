# Taken from https://github.com/nkolban/esp32-snippets/blob/master/cpp_utils/HIDTypes.h
def HIDINPUT(size):
    return 0x80 | size

def HIDOUTPUT(size):
    return 0x90 | size

def INPUT(size):
    return 0x80 | size

def OUTPUT(size):
    return 0x90 | size

def FEATURE(size):
    return 0xb0 | size

def COLLECTION(size):
    return 0xa0 | size

def END_COLLECTION(size):
    return 0xc0 | size

def USAGE_PAGE(size):
    return 0x04 | size

def LOGICAL_MINIMUM(size):
    return 0x14 | size

def LOGICAL_MAXIMUM(size):
    return 0x24 | size

def PHYSICAL_MINIMUM(size):
    return 0x34 | size

def PHYSICAL_MAXIMUM(size):
    return 0x44 | size

def UNIT_EXPONENT(size):
    return 0x54 | size

def UNIT(size):
    return 0x64 | size

def REPORT_SIZE(size):
    return 0x74 | size

def REPORT_ID(size):
    return 0x84 | size

def REPORT_COUNT(size):
    return 0x94 | size

def PUSH(size):
    return 0xa4 | size

def POP(size):
    return 0xb4 | size

def USAGE(size):
    return 0x08 | size

def USAGE_MINIMUM(size):
    return 0x18 | size

def USAGE_MAXIMUM(size):
    return 0x28 | size

def DESIGNATOR_INDEX(size):
    return 0x38 | size

def DESIGNATOR_MINIMUM(size):
    return 0x48 | size

def DESIGNATOR_MAXIMUM(size):
    return 0x58 | size

def STRING_INDEX(size):
    return 0x78 | size

def STRING_MINIMUM(size):
    return 0x88 | size

def STRING_MAXIMUM(size):
    return 0x98 | size

def DELIMITER(size):
    return 0xa8 | size

KEYBOARD_ID = 0x01
MEDIA_KEYS_ID = 0x02

REPORT_MAP = [
  USAGE_PAGE(1),      0x01,          #   USAGE_PAGE (Generic Desktop Ctrls)
  USAGE(1),           0x06,          #   USAGE (Keyboard)
  COLLECTION(1),      0x01,          #   COLLECTION (Application)
  # -------------------------------- #   Keyboard
  REPORT_ID(1),       KEYBOARD_ID,   #   REPORT_ID (1)
  USAGE_PAGE(1),      0x07,          #   USAGE_PAGE (Kbrd/Keypad)
  USAGE_MINIMUM(1),   0xE0,          #   USAGE_MINIMUM (0xE0)
  USAGE_MAXIMUM(1),   0xE7,          #   USAGE_MAXIMUM (0xE7)
  LOGICAL_MINIMUM(1), 0x00,          #   LOGICAL_MINIMUM (0)
  LOGICAL_MAXIMUM(1), 0x01,          #   Logical Maximum (1)
  REPORT_COUNT(1),    0x08,          #   REPORT_COUNT (8)
  REPORT_SIZE(1),     0x01,          #   REPORT_SIZE (1)
  HIDINPUT(1),        0x02,          #   INPUT (Data,Var,Abs,No Wrap,Linear,Preferred State,No Null Position)
  REPORT_COUNT(1),    0x01,          #   REPORT_COUNT (1) ; 1 byte (Reserved)
  REPORT_SIZE(1),     0x08,          #   REPORT_SIZE (8)
  HIDINPUT(1),        0x01,          #   INPUT (Const,Array,Abs,No Wrap,Linear,Preferred State,No Null Position)
  REPORT_COUNT(1),    0x05,          #   REPORT_COUNT (5) ; 5 bits (Num lock, Caps lock, Scroll lock, Compose, Kana)
  REPORT_SIZE(1),     0x01,          #   REPORT_SIZE (1)
  USAGE_PAGE(1),      0x08,          #   USAGE_PAGE (LEDs)
  USAGE_MINIMUM(1),   0x01,          #   USAGE_MINIMUM (0x01) ; Num Lock
  USAGE_MAXIMUM(1),   0x05,          #   USAGE_MAXIMUM (0x05) ; Kana
  HIDOUTPUT(1),       0x02,          #   OUTPUT (Data,Var,Abs,No Wrap,Linear,Preferred State,No Null Position,Non-volatile)
  REPORT_COUNT(1),    0x01,          #   REPORT_COUNT (1) ; 3 bits (Padding)
  REPORT_SIZE(1),     0x03,          #   REPORT_SIZE (3)
  HIDOUTPUT(1),       0x01,          #   OUTPUT (Const,Array,Abs,No Wrap,Linear,Preferred State,No Null Position,Non-volatile)
  REPORT_COUNT(1),    0x06,          #   REPORT_COUNT (6) ; 6 bytes (Keys)
  REPORT_SIZE(1),     0x08,          #   REPORT_SIZE(8)
  LOGICAL_MINIMUM(1), 0x00,          #   LOGICAL_MINIMUM(0)
  LOGICAL_MAXIMUM(1), 0x65,          #   LOGICAL_MAXIMUM(0x65) ; 101 keys
  USAGE_PAGE(1),      0x07,          #   USAGE_PAGE (Kbrd/Keypad)
  USAGE_MINIMUM(1),   0x00,          #   USAGE_MINIMUM (0)
  USAGE_MAXIMUM(1),   0x65,          #   USAGE_MAXIMUM (0x65)
  HIDINPUT(1),        0x00,          #   INPUT (Data,Array,Abs,No Wrap,Linear,Preferred State,No Null Position)
  END_COLLECTION(0),                 #   END_COLLECTION
  # -------------------------------- #   Media Keys
  USAGE_PAGE(1),      0x0C,          #   Usage Page (Consumer)
  USAGE(1),           0x01,          #   Usage (Consumer Control)
  COLLECTION(1),      0x01,          #   Collection (Application)
  REPORT_ID(1),       MEDIA_KEYS_ID, #   Report ID (2)
  USAGE_PAGE(1),      0x0C,          #   Usage Page (Consumer)
  LOGICAL_MINIMUM(1), 0x00,          #   Logical Minimum (0)
  LOGICAL_MAXIMUM(1), 0x01,          #   Logical Maximum (1)
  REPORT_SIZE(1),     0x01,          #   Report Size (1)
  REPORT_COUNT(1),    0x10,          #   Report Count (16)
  USAGE(1),           0xB0,          #   Usage (Play) 1 0
  USAGE(1),           0xB1,          #   Usage (Pause) 2 0
  USAGE(1),           0xCD,          #   Usage (Play/Pause) 4 0
  USAGE(1),           0xB3,          #   Usage (Fast Forward) 8 0
  USAGE(1),           0xB4,          #   Usage (Rewind) 16 0
  USAGE(1),           0xB5,          #   Usage (Scan Next Track) 32 0
  USAGE(1),           0xB6,          #   Usage (Scan Previous Track) 64 0
  USAGE(1),           0xB7,          #   Usage (Stop) 128 0
  USAGE(1),           0x40,          #   Usage (Menu) 0 1 Should be "Home" on Apple TV
  USAGE(1),           0xE9,          #   Usage (Volume Increment) 0 2
  USAGE(1),           0xEA,          #   Usage (Volume Decrement) 0 4
  USAGE(1),           0xE2,          #   Usage (Mute) 0 8
  USAGE(1),           0x30,          #   Usage (Power) 0 16
  USAGE(1),           0x41,          #   Usage (Menu Pick ) 0 32 Should be used for "Select" on Apple TV, as "Enter" dismisses search bars
  USAGE(2),           0x21, 0x02,    #   Usage (AC Search) 0 64
  USAGE(2),           0x23, 0x02,    #   Usage (AC Home) 0 128 "Back" on Apple TV
  HIDINPUT(1),        0x02,          #   Input (Data,Var,Abs,No Wrap,Linear,Preferred State,No Null Position)
  END_COLLECTION(0)                  # End Collection
]


def formatted_hex_str(value: int):
    """
    Formats a one byte integer value into a hex string.
    value: The integer value to format.
    """
    return f"0x{value:0{2}x}"


def generate_report_map_str(report_map: [int]):
    """
    Generates a formatted string of the entire report map that can be pasted into a parser like this one:
    https://eleccelerator.com/usbdescreqparser/
    """
    hex_values = map(formatted_hex_str, report_map)
    return ", ".join(hex_values)