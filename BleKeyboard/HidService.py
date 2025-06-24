import logging

from bluez_peripheral.gatt.descriptor import descriptor
from bluez_peripheral.gatt.service import Service
from bluez_peripheral.gatt.characteristic import characteristic, CharacteristicFlags as CharFlags, DescriptorFlags as DescFlags

from BleKeyboard.ReportmapHelper import REPORT_MAP

#hid service: type="primary" uuid="1812" 00001812-0000-1000-8000-00805F9B34FB
class HidService(Service):

    logger = logging.getLogger(__name__)

    def __init__(self):
        super().__init__("1812", True)
        self.pressed_keys: [int] = [00, 00, 00, 00, 00, 00, 00, 00]
        self.pressed_media_keys: [int] = [00, 00]


    # hid info characteristic: uuid="2A4A"
    #   ['read'], value = 01110002 (hex)
    @characteristic("2A4A", CharFlags.READ)
    def hid_info(self, options):
        bcd_version = [0x01, 0x11]  # USB HID Version (1.21)
        b_country_code = [0x00]     # Country code, should be 0
        flags = [0x03]              # NormallyConnectable second to last bit, RemoteWake last bit i.e.
        # 0 0 = 0x00 = False NormallyConnectable, False RemoteWake
        # 0 1 = 0x01 = False NormallyConnectable, True RemoteWake
        # 1 0 = 0x02 = True NormallyConnectable, False RemoteWake
        # 1 1 = 0x03 = True NormallyConnectable, True RemoteWake
        # NormallyConnectable should always be true, RemoteWake only if the keyboard is supposed to wake the device
        return bytes(bytearray(bcd_version + b_country_code + flags))


    # report map characteristic: uuid="2A4B"
    #   ['read'], value = reportmap (hex), see reportmap_helper for more info
    @characteristic("2A4B", CharFlags.READ)
    def report_map(self, options):
        # Report map is loaded from report_map_helper, look there for more info
        return bytes(REPORT_MAP)


    # control point characteristic: uuid="2A4C"
    #   ["write-without-response"], value = 00 (hex)
    @characteristic("2A4C", CharFlags.WRITE_WITHOUT_RESPONSE)
    def control_point(self, options):
        return bytes([0x00])


    @control_point.setter
    def control_point(self, value, options):
        self.logger.debug(f"control point set to {value} with {options}")


    # report characteristic: id="report" name="Report" sourceId="org.bluetooth.characteristic.report" uuid="2A4D"
    #   ['secure-read', 'notify'], value = (uint8_t modifiers; uint8_t reserved; uint8_t keys[6];), z.B: [00, 00, 6*[00]] für keine Taste
    #   for key press: set value, then Notify
    #   read must be encrypted for some devices (everything Apple, it seems)
    @characteristic("2A4D", CharFlags.SECURE_READ | CharFlags.NOTIFY)
    def report1(self, options):
        return bytes(self.pressed_keys)


    # report descriptor: type="org.bluetooth.descriptor.report_reference" uuid="2908"
    #    ['read'], value= 01 01 (first two -> Report-ID 0-255, second two -> report type (1=Input report, 2=output report, 3=feature report))
    #    Report-ID = KEYBOARD_ID from report_map
    @descriptor("2908", report1, DescFlags.READ)
    def report1_descriptor(self, options):
        return bytes([0x01, 0x01])


    def update_pressed_keys(self, new_state: [int]):
        """
        Update the currently pressed keys on the keyboard.
        :param new_state: New keys to be pressed
        """
        self.pressed_keys = new_state

        keys = bytes(bytearray(self.pressed_keys))
        self.report1.changed(keys)
        self.logger.debug(f"Notified with {keys}")


    # report characteristic(2): uuid="2A4D"
    #   ['secure-read', 'notify'], value = [00, 00] media key: (uint8_t MediaKeyReport[2];), i.e. [00,00] for none or [80, 00] for [128,0] -> definition in report_map->Media Keys...
    #   for key press: set value, then Notify
    #   read must be encrypted for some devices (everything Apple, it seems)
    @characteristic("2A4D", CharFlags.SECURE_READ | CharFlags.NOTIFY)
    def report2(self, options):
        return bytes(self.pressed_media_keys)


    # report descriptor: type="org.bluetooth.descriptor.report_reference" uuid="2908"
    #    ['read'], value= 02 01  (first two -> Report-ID 0-255, second two -> report type (1=Input report, 2=output report, 3=feature report))
    #    Report-ID = MEDIA_KEYS_ID from report_map
    @descriptor("2908", report2, DescFlags.READ)
    def report2_descriptor(self, options):
        return bytes([0x02, 0x01])


    def update_pressed_media_keys(self, new_state: [int]):
        """
        Update the currently pressed media keys on the keyboard.
        :param new_state: New keys to be pressed
        """
        self.pressed_media_keys = new_state

        keys = bytes(bytearray(new_state))
        self.report2.changed(keys)
        self.logger.debug(f"Notified with {keys}")


    # protocol mode characteristic: uuid="2A4E"
    #   ["read", "write-without-response"], value = 1
    @characteristic("2A4E", CharFlags.READ | CharFlags.WRITE_WITHOUT_RESPONSE)
    def protocol_mode(self, options):
        return bytes([0x01])

