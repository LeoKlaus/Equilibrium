from bluez_peripheral.gatt.service import Service
from bluez_peripheral.gatt.characteristic import characteristic, CharacteristicFlags as CharFlags


# device info service: type="primary" uuid="180A"
# Could also include manufacturer , device and version:
# vendor characteristic: uuid="2A29"
#   ["read"], value = Manufacturer
#
# product characteristic: uuid="2A24"
#   ["read"], value = Name
#
# version characteristic: uuid="2A28"
#   ["read"], value = Version

class DeviceInformationService(Service):
    def __init__(self):
        super().__init__("180A", True)


    # pnp characteristic: name="PNP Characteristic?" uuid="2A50"
    #   ["read"], value = 0x0205AC820A0210 (more infos at https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/DIS_v1.2/out/en/index-en.html#UUID-f5dd4f05-fa26-cee7-a413-81ed0ee437d1)
    @characteristic("2A50", CharFlags.READ)
    def pnp(self, options):
        # Example from a Logitech G915 TKL: 02 6d 04 5f b3 22 00
        return bytes.fromhex('0205AC820A0210')