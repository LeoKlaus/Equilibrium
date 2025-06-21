import logging

from bluez_peripheral.gatt.service import Service
from bluez_peripheral.gatt.characteristic import characteristic, CharacteristicFlags as CharFlags

import struct


# battery service: type="primary" uuid="180F"
class BatteryService(Service):

    logger = logging.getLogger(__name__)

    def __init__(self):
        super().__init__("180F", True)
        self.battery_charge = 100


    # battery characteristic: name="Battery Level" uuid="2A19"
    #   ['read', 'notify'], value = Percentage Int
    @characteristic("2A19", CharFlags.READ | CharFlags.NOTIFY)
    def battery_state(self, options):
        # This function is called when the characteristic is read.
        return self.battery_charge.to_bytes(2, byteorder='big')


    def update_battery_state(self, new_state):
        """
        Send a notification for updated battery state.
        :param new_state: New value for battery charge (0-100)
        """
        # Note that notification is asynchronous (you must await something at some point after calling this).
        self.battery_charge = new_state
        flags = 0
        # Bluetooth data is little endian.
        state = struct.pack("<BB", flags, new_state)
        self.battery_state.changed(state)
        self.logger.debug(f"Updated state to {self.battery_charge}, {state}")