import asyncio
import logging
import time
from typing import ClassVar

from bluez_peripheral.adapter import Adapter
from bluez_peripheral.advert import Advertisement
from bluez_peripheral.agent import NoIoAgent
from bluez_peripheral.util import get_message_bus
from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from api.models.command import Command
from api.models.health import ComponentHealth, ComponentStatus
from api.models.websocket_responses import (
    BleDevice,
    WebsocketBleCommand,
    WebsocketBleDeviceResponse,
    WebsocketBleSuccessResponse,
)
from ble_keyboard.battery_service import BatteryService
from ble_keyboard.bluetooth_events import (
    BluetoothEventBroadcaster,
    Subscription,
    change_message,
    device_for_address,
    snapshot_message,
)
from ble_keyboard.bluetooth_state import AvailabilityChanged, BluetoothState, DeviceChanged, StateChange
from ble_keyboard.bluez_monitor import BluezMonitor
from ble_keyboard.device_information_service import DeviceInformationService
from ble_keyboard.hid_service import HidService
from ble_keyboard.keymap_helper import create_keycode, create_media_keycode
from hub.event_bus import Directive
from hub.interfaces import ActionExecutor

# For Apple TV:
# 1. Advertise
# 2. (On Apple TV) connect
# 3. The hub initiates pairing by itself (see _pair_new_connection)
# 4. (On Apple TV) confirm pairing
# 5. send keystrokes
#
# Controls:
# esc                 = back
# esc (hold)          = home
# AC_HOME             = back
# AC_HOME (hold)      = home
# AC_HOME (double)    = app switcher
# MENU                = home
# MENU (hold)         = Control Center


class BleKeyboard(ActionExecutor):
    """
    Class representing a BLE keyboard.
    """

    name = "bluetooth"
    capabilities: ClassVar[list[str]] = ["pairing", "device_list"]

    logger = logging.getLogger(__package__)

    AGENT_PATH = "/me/wehrfritz/bluez_peripheral/agent"
    ADVERTISEMENT_TIMEOUT = 60  # seconds
    # How long after advertise() a new, unpaired connection is paired automatically
    PAIRING_WINDOW = ADVERTISEMENT_TIMEOUT + 10

    def __init__(self, auto_pair: bool = True) -> None:
        self.auto_pair = auto_pair
        self.bus = None
        self.battery_service: BatteryService | None = None
        self.device_info_service: DeviceInformationService | None = None
        self.hid_service: HidService | None = None
        self.agent: NoIoAgent | None = None
        self.monitor: BluezMonitor | None = None
        self.state = BluetoothState()
        self.events = BluetoothEventBroadcaster(self.state)
        self._services_lost = False
        self._pairing_window_until = 0.0
        self._pairing: set[str] = set()  # addresses with a Pair call in progress
        self._pairing_tasks: set[asyncio.Task[None]] = set()
        self.state.add_listener(self._on_state_change)

        self.pressed_keys: list[list[int]] = []
        self.pressed_media_keys: list[list[int]] = []

        self.router = self._build_router()

    def _build_router(self) -> APIRouter:
        router = APIRouter(responses={404: {"description": "Not found"}})
        self._add_http_routes(router)
        self._add_websocket_routes(router)
        return router

    def _add_http_routes(self, router: APIRouter) -> None:
        @router.get("/bluetooth/devices", tags=["Bluetooth Devices"], response_model=list[BleDevice])
        async def get_connected_ble_devices() -> list[BleDevice]:
            return await self.devices

        @router.post("/bluetooth/start_advertisement", tags=["Bluetooth Devices"])
        async def start_ble_discovery():
            await self.advertise()
            return {"success": True}

        @router.post(
            "/bluetooth/start_pairing",
            tags=["Bluetooth Devices"],
            description="Will initiate pairing with all connected bluetooth devices that are not currently "
                        "paired. This is may be necessary for some devices (notably Apple TVs).",
        )
        async def start_ble_pairing():
            await self.initiate_pairing()
            return {"success": True}

        @router.post("/bluetooth/connect/{mac_address}", tags=["Bluetooth Devices"])
        async def connect_ble_device(mac_address: str):
            await self.connect(mac_address)
            return {"success": True}

        @router.post("/bluetooth/disconnect", tags=["Bluetooth Devices"])
        async def disconnect_ble_devices():
            await self.disconnect()
            return {"success": True}

    def _add_websocket_routes(self, router: APIRouter) -> None:
        # Pairing flow (e.g. for an ATV 4K, where the pairing prompt only appears if the hub
        # initiates pairing within a short time after connecting for the first time - done
        # automatically by _pair_new_connection):
        # 1. Start advertisement
        # 2. Select "Virtual Keyboard" in the target's bluetooth settings
        # 3. Confirm pairing on the target device
        # A devices query over this socket still triggers pairing for a connected, unpaired device.
        @router.websocket("/ws/bt_pairing")
        async def websocket_bt_pairing(websocket: WebSocket):
            await websocket.accept()

            try:
                while websocket.client_state == WebSocketState.CONNECTED:
                    command = await websocket.receive_text()
                    if command == WebsocketBleCommand.ADVERTISE:
                        await self.advertise()
                        await websocket.send_json(WebsocketBleSuccessResponse().model_dump())

                    if command == WebsocketBleCommand.CONNECT:
                        devices = await self.devices
                        await websocket.send_json(WebsocketBleDeviceResponse(devices=devices).model_dump())
                        addr = await websocket.receive_text()
                        await self.connect(addr)

                    if command == WebsocketBleCommand.DISCONNECT:
                        await self.disconnect()
                        await websocket.send_json(WebsocketBleSuccessResponse().model_dump())

                    if command == WebsocketBleCommand.DEVICES:
                        devices = await self.devices
                        await websocket.send_json(WebsocketBleDeviceResponse(devices=devices).model_dump())
            except WebSocketDisconnect:
                self.logger.debug("Client disconnected from bt_pairing websocket")

        # The state of the adapter and devices: a snapshot on connect, then every change
        @router.websocket("/ws/bluetooth")
        async def websocket_bluetooth(websocket: WebSocket):
            await websocket.accept()

            with self.events.subscribe() as subscription:
                await websocket.send_json(snapshot_message(self.state.snapshot).model_dump())

                sender = asyncio.create_task(self._send_changes(websocket, subscription))
                receiver = asyncio.create_task(self._reject_inbound(websocket))
                try:
                    done, _ = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                except WebSocketDisconnect:
                    self.logger.debug("Client disconnected from bluetooth websocket")
                finally:
                    sender.cancel()
                    receiver.cancel()

    @staticmethod
    async def _send_changes(websocket: WebSocket, subscription: Subscription) -> None:
        while True:
            change = await subscription.queue.get()
            if change is None:
                # Too far behind; reconnecting gets a fresh snapshot
                await websocket.close(code=1013)
                return
            await websocket.send_json(change_message(change).model_dump())

    @staticmethod
    async def _reject_inbound(websocket: WebSocket) -> None:
        while True:
            await websocket.receive_text()
            await websocket.send_text("This endpoint should only be used to receive Bluetooth updates!")

    def _on_state_change(self, change: StateChange) -> None:
        if isinstance(change, DeviceChanged):
            self._pair_new_connection(change)
            return
        if not isinstance(change, AvailabilityChanged) or self.hid_service is None:
            return
        if not change.available:
            self._services_lost = True
        elif self._services_lost:
            self.logger.warning(
                "bluetoothd is back, but the Bluetooth services and the pairing agent were lost with the "
                "restart and aren't registered again. Restart the hub to restore the virtual keyboard."
            )

    def _pair_new_connection(self, change: DeviceChanged) -> None:
        """Some hosts (notably Apple TVs) only show their pairing prompt once
        the hub initiates pairing, shortly after they connected. Done for
        devices that connect right after advertise(), and only then: this is
        what keeps anything else that connects from being paired."""
        device = change.device
        if not self.auto_pair or device is None or not device.connected or device.paired:
            return
        if time.monotonic() > self._pairing_window_until:
            return
        path = self.state.device_path(change.address)
        if path is None:
            return

        task = asyncio.create_task(self._pair_automatically(path, change.address))
        self._pairing_tasks.add(task)
        task.add_done_callback(self._pairing_tasks.discard)

    async def _pair_automatically(self, path: str, address: str) -> None:
        try:
            await self._pair_device(path, address)
        except Exception:
            self.logger.warning(f"Couldn't pair with {address}", exc_info=True)

    async def _pair_device(self, path: str, address: str) -> None:
        """Asks BlueZ to pair with the device, which returns once the host
        confirmed or gave up. Does nothing if that is already going on."""
        if address in self._pairing:
            self.logger.debug(f"Already pairing with {address}")
            return
        self._pairing.add(address)
        try:
            self.logger.info(f"Trying to pair with {address}, confirm pairing on your device...")
            interface = await self._get_device_interface(path)
            await interface.call_pair()
        finally:
            self._pairing.discard(address)

    def bluetooth_device(self, address: str) -> BleDevice:
        """The current state of the device with this address (a scene's
        bluetooth_address); disconnected and unpaired if BlueZ doesn't know it."""
        return device_for_address(self.state.device(address), address)

    @classmethod
    async def create(cls, auto_pair: bool = True):
        self = cls(auto_pair=auto_pair)
        self.bus = await get_message_bus()
        await self.register_services()
        await self._start_monitor()
        return self

    async def _start_monitor(self) -> None:
        """Starts logging BlueZ's state changes. Purely diagnostic, so a
        failure here must not keep the keyboard itself from starting."""
        assert self.bus is not None
        monitor = BluezMonitor(self.bus, self.state)
        try:
            await monitor.start()
        except Exception:
            self.logger.warning("Couldn't start the Bluetooth state monitor", exc_info=True)
            return
        self.monitor = monitor

    async def stop(self) -> None:
        for task in list(self._pairing_tasks):
            task.cancel()
        if self.monitor is not None:
            monitor, self.monitor = self.monitor, None
            await monitor.stop()

    async def execute(self, directive: Directive, command: Command) -> None:
        if command.bt_action:
            if directive.press_without_release:
                self.press_key(command.bt_action)
            else:
                await self.send_key(command.bt_action)
            self.logger.debug(f"Sent command {command.name}")
        elif command.bt_media_action:
            if directive.press_without_release:
                self.press_media_key(command.bt_media_action)
            else:
                await self.send_media_key(command.bt_media_action)
            self.logger.debug(f"Sent media command {command.name}")
        else:
            self.logger.error(f"Command {command.name} doesn't include a bluetooth action")

    async def health(self) -> ComponentHealth:
        """Whether the D-Bus connection is alive and a Bluetooth adapter is
        present and powered, from the monitor's cached state."""
        if self.bus is None or not self.bus.connected:
            return ComponentHealth(
                name=self.name, status=ComponentStatus.DOWN, detail="Not connected to the system D-Bus"
            )
        if self.monitor is None:
            return await self._probe_health()
        return self._cached_health()

    def _cached_health(self) -> ComponentHealth:
        if not self.state.bluez_available:
            return ComponentHealth(
                name=self.name, status=ComponentStatus.DOWN, detail="bluetoothd isn't available"
            )
        adapter = self.state.adapter
        if adapter is None:
            return ComponentHealth(name=self.name, status=ComponentStatus.DOWN, detail="No Bluetooth adapter")
        if self._services_lost:
            return ComponentHealth(
                name=self.name,
                status=ComponentStatus.DEGRADED,
                detail="bluetoothd restarted and the Bluetooth services were lost, restart the hub",
            )
        if not adapter.powered:
            return ComponentHealth(
                name=self.name, status=ComponentStatus.DEGRADED, detail="Bluetooth adapter is powered off"
            )
        return ComponentHealth(name=self.name, status=ComponentStatus.OK)

    async def _probe_health(self) -> ComponentHealth:
        try:
            adapter = await Adapter.get_first(self.bus)
            powered = await adapter.get_powered()
        except Exception as error:
            return ComponentHealth(
                name=self.name,
                status=ComponentStatus.DOWN,
                detail=f"No usable Bluetooth adapter: {type(error).__name__}: {error}",
            )
        if not powered:
            return ComponentHealth(
                name=self.name, status=ComponentStatus.DEGRADED, detail="Bluetooth adapter is powered off"
            )
        return ComponentHealth(name=self.name, status=ComponentStatus.OK)

    async def register_services(self):
        self.battery_service = BatteryService()
        self.device_info_service = DeviceInformationService()
        self.hid_service = HidService()

        await self.battery_service.register(self.bus, path="/me/wehrfritz/bluez_peripheral/service_battery")
        await self.device_info_service.register(self.bus, path="/me/wehrfritz/bluez_peripheral/service_info")
        await self.hid_service.register(self.bus, path="/me/wehrfritz/bluez_peripheral/service_hid")
        self.logger.debug("Registered services")

    async def unregister_services(self):
        if self.battery_service is not None:
            await self.battery_service.unregister()
        if self.device_info_service is not None:
            await self.device_info_service.unregister()
        if self.hid_service is not None:
            await self.hid_service.unregister()

    async def _ensure_agent_registered(self) -> None:
        """Registers the pairing agent once; advertise() may be called repeatedly.

        The path has to be passed explicitly: bluez_peripheral 0.2.0a5's
        BaseAgent.register() hands its `path` argument (None by default) to
        BlueZ's RegisterAgent instead of the generated export path, which
        makes BlueZ reject the call.
        """
        if self.agent is not None:
            return

        agent = NoIoAgent()
        try:
            await agent.register(self.bus, path=self.AGENT_PATH)
        except Exception:
            # register() exports the object before calling BlueZ; undo that so a retry can export again
            if agent.is_exported:
                agent.unexport()
            raise
        self.agent = agent

    async def advertise(self):
        """
        Starts advertisement for the keyboard service. Call this to make the keyboard discoverable.
        Warning: Starting the advertisement might lead to previously connected devices reconnecting.
        """

        await self._ensure_agent_registered()

        adapter = await Adapter.get_first(self.bus)

        # Start an advert that will last for 60 seconds.
        advert = Advertisement("Virtual Keyboard", [
            "0000180F-0000-1000-8000-00805F9B34FB",
            "0000180A-0000-1000-8000-00805F9B34FB",
            "00001812-0000-1000-8000-00805F9B34FB"
        ], appearance=0x03C1, timeout=self.ADVERTISEMENT_TIMEOUT)

        await advert.register(self.bus, adapter=adapter)
        self._pairing_window_until = time.monotonic() + self.PAIRING_WINDOW
        self.logger.info("Started advertising!")


    def press_key(self, key_str: str):
        """
        Send a key press to the connected device
        :param key_str: Key descriptor from key_map_helper.KEY_TABLE
        """
        assert self.hid_service is not None  # create() already registered services

        key = create_keycode(key_str)
        if key:
            self.release_keys()
            self.pressed_keys.append(key)
            self.hid_service.update_pressed_keys(key)

    def release_keys(self):
        """
        Send a key release to the connected device
        """
        assert self.hid_service is not None  # create() already registered services
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
        assert self.hid_service is not None  # create() already registered services

        key = create_media_keycode(key_str)
        if key:
            self.release_media_keys()
            self.pressed_media_keys.append(key)
            self.hid_service.update_pressed_media_keys(key)

    def release_media_keys(self):
        """
        Send a key release to the connected device
        """
        assert self.hid_service is not None  # create() already registered services
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


    def update_battery_state(self, new_level: int = 100):
        """
        Update the reported battery state of the keyboard. I don't think this has any practical use
        :param new_level: Battery level to set (0-100)
        """
        assert self.battery_service is not None  # create() already registered services
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

    async def initiate_pairing(self):
        """
        Will initiate pairing with all connected devices that are not currently paired. This is necessary for my Apple TV.
        """
        introspection = await self.bus.introspect("org.bluez", "/")
        proxy_object = self.bus.get_proxy_object("org.bluez", "/", introspection)
        interface = proxy_object.get_interface('org.freedesktop.DBus.ObjectManager')
        managed_objects = await interface.call_get_managed_objects()

        for path in managed_objects:
            device = managed_objects[path].get("org.bluez.Device1", {})
            address = device.get("Address")
            paired = device.get("Paired", False)
            connected = device.get("Connected", False)

            if address and paired and connected and not paired.value and connected.value:
                await self._pair_device(path, address.value)

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
            if address and paired and connected and not paired.value and connected.value:
                await self._pair_device(path, address.value)

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
        return any(device.get("paired") and device.get("connected") for device in devices)


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
