import asyncio
import logging
from random import randint

from bluez_peripheral.advert import Advertisement
from bluez_peripheral.agent import NoIoAgent
from bluez_peripheral.util import get_message_bus, Adapter

from BleKeyboard.BatteryService import BatteryService
from BleKeyboard.DeviceInformationService import DeviceInformationService
from BleKeyboard.HidService import HidService
from BleKeyboard.KeymapHelper import create_keycode, create_media_keycode


# For Apple TV:
# 1. Advertise
# 2. (On Apple TV) connect
# 3. Connect to initiate pairing
# 4. (On Apple TV) confirm pairing
# 6. send keystrokes
#
# Controls:
# esc                 = back
# esc (hold)          = home
# AC_HOME             = back
# AC_HOME (hold)      = home
# AC_HOME (double)    = app switcher
# MENU                = home
# MENU (hold)         = Control Center


class BleKeyboard:
    """
    Class representing a BLE keyboard.
    """
    logger = logging.getLogger(__package__)

    bus = None
    battery_service = None
    device_info_service = None
    hid_service = None

    pressed_keys = []
    pressed_media_keys = []

    @classmethod
    async def create(cls):
        self = cls()
        self.bus = await get_message_bus()
        await self.register_services()
        return self

    async def register_services(self):
        self.battery_service = BatteryService()
        self.device_info_service = DeviceInformationService()
        self.hid_service = HidService()

        await self.battery_service.register(self.bus, "/me/wehrfritz/bluez_peripheral/service_battery")
        await self.device_info_service.register(self.bus, "/me/wehrfritz/bluez_peripheral/service_info")
        await self.hid_service.register(self.bus, "/me/wehrfritz/bluez_peripheral/service_hid")
        self.logger.debug("Registered services")

    async def unregister_services(self):
        if self.battery_service is not None:
            await self.battery_service.unregister()
        if self.device_info_service is not None:
            await self.device_info_service.unregister()
        if self.hid_service is not None:
            await self.hid_service.unregister()

    async def advertise(self):
        """
        Starts advertisement for the keyboard service. Call this to make the keyboard discoverable.
        Warning: Starting the advertisement might lead to previously connected devices reconnecting.
        """

        agent = NoIoAgent()

        await agent.register(self.bus)

        adapter = await Adapter.get_first(self.bus)

        # Start an advert that will last for 60 seconds.
        advert = Advertisement("Virtual Keyboard", [
            "0000180F-0000-1000-8000-00805F9B34FB",
            "0000180A-0000-1000-8000-00805F9B34FB",
            "00001812-0000-1000-8000-00805F9B34FB"
        ], 0x03C1, 60)

        await advert.register(self.bus, adapter)
        self.logger.info("Started advertising!")


    def press_key(self, key_str: str):
        """
        Send a key press to the connected device
        :param key_str: Key descriptor from key_map_helper.KEY_TABLE
        """

        key = create_keycode(key_str)
        if key:
            self.release_keys()
            self.pressed_keys.append(key)
            self.hid_service.update_pressed_keys(key)

    def release_keys(self):
        """
        Send a key release to the connected device
        """
        if self.pressed_keys:
            self.hid_service.update_pressed_keys([00, 00, 00, 00, 00, 00, 00, 00])
            self.pressed_keys = []


    async def send_key(self, key_str: str, delay=0.1):
        """
        Send a single key to the connected device
        :param key_str: Key descriptor from key_map_helper.KEY_TABLE
        :param delay: Delay after which the key is released
        """
        self.press_key(key_str)
        await asyncio.sleep(delay)
        self.release_keys()


    def press_media_key(self, key_str: str):
        """
        Send a media key press to the connected device
        :param key_str: Key descriptor from key_map_helper.MEDIA_KEYS
        """

        key = create_media_keycode(key_str)
        if key:
            self.release_media_keys()
            self.pressed_media_keys.append(key)
            self.hid_service.update_pressed_media_keys(key)

    def release_media_keys(self):
        """
        Send a key release to the connected device
        """
        if self.pressed_media_keys:
            self.hid_service.update_pressed_media_keys([00, 00])
            self.pressed_media_keys = []

    async def send_media_key(self, key_str, delay=0.1):
        """
        Send a single media key to the connected device
        :param key_str: Key descriptor from keymap_helper.MEDIA_KEYS
        :param delay: Delay after which the key is released
        """
        self.press_media_key(key_str)
        await asyncio.sleep(delay)
        self.release_media_keys()


    def update_battery_state(self, new_level=randint(1, 100)):
        """
        Update the reported battery state of the keyboard. I don't think this has any practical use
        :param new_level: Battery level to set (0-100)
        """
        self.battery_service.update_battery_state(new_level)


    async def _get_device_interface(self, path):
        """
        Gets the DBUS interface for the device at the given path
        :param path:
        :return:
        """
        introspection = await self.bus.introspect("org.bluez", path)
        proxy_object = self.bus.get_proxy_object("org.bluez", path, introspection)
        return proxy_object.get_interface("org.bluez.Device1")


    @property
    async def devices(self):
        """
        Get all connected or paired devices.
        :return: A list of all connected or paired devices
        """
        introspection = await self.bus.introspect("org.bluez", "/")
        proxy_object = self.bus.get_proxy_object("org.bluez", "/", introspection)
        interface = proxy_object.get_interface('org.freedesktop.DBus.ObjectManager')
        managed_objects = await interface.call_get_managed_objects()

        connected_devices = []

        for path in managed_objects:
            device = managed_objects[path].get("org.bluez.Device1", {})
            alias = device.get("Alias")
            address = device.get("Address")
            paired = device.get("Paired", False)
            connected = device.get("Connected", False)

            # My ATV 4K doesn't pair automatically after connecting...
            if address and paired and connected:
                if not paired.value and connected.value:
                    self.logger.info(f"Trying to pair with {address.value}")
                    interface = await self._get_device_interface(path)
                    self.logger.info("Trying to pair, confirm pairing on your device...")
                    await interface.call_pair()

            if address and alias and (paired or connected):
                connected_devices.append({
                    "path": path,
                    "address": None if not address else address.value,
                    "alias": None if not alias else alias.value,
                    "paired": None if not paired else paired.value,
                    "connected": None if not connected else connected.value
                })
        return connected_devices


    @property
    async def is_connected(self):
        """
        Get current connection status
        :return: `True` if a device is currently connected and paired, `False` else
        """
        devices = await self.devices
        for device in devices:
            if device.get("paired") and device.get("connected"):
                return True
        return False


    async def connect(self, address: str):
        """
        Attempt to connect to the device with the given MAC address
        :param address: The address of the device that should be connected
        """
        await self.disconnect()

        devices = await self.devices
        for device in devices:
            if device.get("address") == address:
                path = device.get("path")
                if not path:
                    self.logger.error("No path found for connected device")
                    return

                interface = await self._get_device_interface(path)
                await interface.call_connect()
                return
        self.logger.error(f"No device with address {address} found")


    async def disconnect(self, address=None):
        """
        Attempt to disconnect from the currently connected device(s)
        :param address: The address of the device that should be disconnected
        """
        devices = await self.devices
        for device in devices:
            if device.get("connected") and (address is None or address == device.get("address")):
                path = device.get("path")
                if path:
                    interface = await self._get_device_interface(path)
                    await interface.call_disconnect()
                else:
                    self.logger.error("No path found for connected device")
