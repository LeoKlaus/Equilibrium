import asyncio
import json
import logging
from asyncio import CancelledError
from typing import Dict

import httpx
from fastapi import HTTPException
from sqlalchemy import Boolean
from sqlmodel import Session
from starlette.websockets import WebSocket, WebSocketState

from Api.WebsocketConnectionManager.WebsocketConnectionManager import AsyncJsonCallback
from Api.models import Device, Macro
from Api.models.Command import CommandBase, Command
from Api.models.CommandGroupType import CommandGroupType
from Api.models.CommandType import CommandType
from Api.models.DeviceType import DeviceType
from Api.models.IntegrationAction import IntegrationAction
from Api.models.NetworkRequestType import NetworkRequestType
from Api.models.RemoteButton import RemoteButton
from Api.models.Scene import Scene
from Api.models.SceneStatus import SceneStatus
from Api.models.Status import StatusReport
from Api.models.WebsocketResponses import BleDevice, WebsocketIrResponse
from BleKeyboard.BleKeyboard import BleKeyboard
from DbManager.DbManager import engine
from IrManager.IrManager import IrManager
from RemoteController.AsyncQueueManager import AsyncQueueManager
from RfManager.RfManager import RfManager
from HaManager.HaManager import HaManager

class RemoteController:

    status: StatusReport = StatusReport()

    keymap: Dict[str, int] = []
    keymap_scene: Dict[str, int] = []

    logger: logging
    is_dev: Boolean
    ble_keyboard: BleKeyboard
    rf_manager: RfManager
    ir_manager: IrManager
    ha_manager: HaManager|None = None
    queue: AsyncQueueManager

    status_callback: AsyncJsonCallback|None = None

    cached_commands: {int:Command} = None

    @classmethod
    async def create(cls, rf_addresses: list[bytes], ha_url: str|None = None, ha_token: str|None = None):
        self = cls()

        self.logger = logging.getLogger(__package__)

        self.is_dev = False

        self.ble_keyboard = await BleKeyboard.create()

        self.rf_manager = RfManager()
        self.rf_manager.start_listener(addresses=rf_addresses)

        self.ir_manager = IrManager()

        self.queue = AsyncQueueManager()

        if ha_url is not None and ha_token is not None:
            self.ha_manager = HaManager(ha_url, ha_token)

        try:
            self.load_key_map()
        except FileNotFoundError:
            self.logger.warning("Couldn't find \"keymap_default.json\", no keymap will be active.")

        self.logger.debug("Remote controller ready")

        return self

    @classmethod
    async def create_dev(cls, ha_url: str|None = None, ha_token: str|None = None):
        self = cls()

        self.logger = logging.getLogger(__package__)

        self.is_dev = True

        self.queue = AsyncQueueManager()

        if ha_url is not None and ha_token is not None:
            self.ha_manager = HaManager(ha_url, ha_token)

        try:
            self.load_key_map()
        except FileNotFoundError:
            self.logger.warning("Couldn't find \"keymap_default.json\", no keymap will be active.")

        self.logger.debug("Remote controller ready")

        return self


    async def shutdown(self):
        if not self.is_dev:
            self.ir_manager.cancel_recording()
            self.rf_manager.stop_listener()
            await self.ble_keyboard.disconnect()

    async def record_ir_command(self, data, websocket: WebSocket):
        self.ir_manager.cancel_recording()

        with Session(engine) as session:

            new_command = CommandBase.model_validate(data)
            if new_command:
                db_command = Command.model_validate(data)

                if new_command.device_id:
                    db_device = session.get(Device, new_command.device_id)
                    db_command.device_id = new_command.device_id
                    db_command.device = db_device

                db_command.type = new_command.type

                try:
                    code = await self.ir_manager.record_command(new_command.name, websocket)

                    if code:
                        db_command.ir_action = code

                        session.add(db_command)
                        session.commit()
                        session.refresh(db_command)
                        await websocket.send_json(WebsocketIrResponse.DONE)

                except CancelledError:
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.send_json(WebsocketIrResponse.CANCELLED)
                        await websocket.close()

    async def execute_macro(self, macro: Macro, from_start: bool = False, from_stop: bool = False):
        for index, command_id in enumerate(macro.command_ids):
            await self.send_command(command_id, from_start=from_start, from_stop=from_stop)
            #await self.send_db_command(command, from_start=from_start, from_stop=from_stop)

            if index < len(macro.delays):
                await asyncio.sleep(macro.delays[index] / 1000)


    async def send_db_command(self, command: Command, press_without_release = False, from_start: bool = False, from_stop: bool = False):

        if from_start and command.device_id is not None:
            current_status = self.status.devices.state(for_device_id=command.device_id)
            # Device is already powered on
            if (command.button == RemoteButton.POWER_ON or command.button == RemoteButton.POWER_TOGGLE) and current_status.powered:
                return
            # Device is already on correct input
            if command.command_group == CommandGroupType.INPUT and current_status.input == command.id:
                return

        if from_stop and command.device_id is not None:
            current_status = self.status.devices.state(for_device_id=command.device_id)
            # Device is already powered off
            if (command.button == RemoteButton.POWER_OFF or command.button == RemoteButton.POWER_TOGGLE) and not current_status.powered:
                return

        match command.type:
            case CommandType.IR:
                await self.send_ir_command(command, press_without_release=press_without_release)
            case CommandType.BLUETOOTH:
                await self.send_bt_command(command, press_without_release=press_without_release)
            case CommandType.NETWORK:
                await self.send_network_command(command)
            case CommandType.SCRIPT:
                await self.send_script_command(command)
            case CommandType.INTEGRATION:
                self.send_integration_command(command)

        # TODO: Maybe make this configurable?
        # In my usage, this was more annoying than helpful as it lead to breakage of scenes when manually
        # correcting things, like turning on the TV after it missed the initial command
        if from_start or from_stop:
            await self.set_state_for_command(command)


    async def send_command(self, command_id: int, press_without_release = False, from_start: bool = False, from_stop: bool = False):
        command_db = self.cached_commands.get(command_id)

        if command_db:
            await self.send_db_command(command_db, press_without_release, from_start=from_start, from_stop=from_stop)
        else:
            self.logger.debug(f"Command {command_id} is not cached, loading from db...")
            with Session(engine) as session:
                command_db = session.get(Command, command_id)
                if command_db:
                    self.cached_commands[command_id] = command_db
                    self.logger.debug(f"Loaded and cached command {command_id} from db.")
                    await self.send_db_command(command_db, press_without_release, from_start=from_start, from_stop=from_stop)
                else:
                    self.logger.error(f"Tried to send command {command_id}, which doesn't exist in the database.")



    async def send_ir_command(self, command: Command, press_without_release = False):

        if self.is_dev:
            return

        ir_command = command.ir_action

        if ir_command:
            if press_without_release:
                await self.ir_manager.send_and_repeat(ir_command)
            else:
                await self.ir_manager.send_command(ir_command)
            return "Command sent"
        else:
            raise HTTPException(status_code=500, detail="Command doesn't include executable action")

    async def send_bt_command(self, command: Command, press_without_release = False, release_only=False):

        if self.is_dev:
            return

        bt_command = command.bt_action
        bt_media_command = command.bt_media_action
        if bt_command:
            if release_only:
                self.ble_keyboard.release_keys()
            elif press_without_release:
                self.ble_keyboard.press_key(bt_command)
            else:
                await self.ble_keyboard.send_key(bt_command)
            self.logger.debug(f"Sent command {command.name}")
            return "Command sent"
        elif bt_media_command:
            if release_only:
                self.ble_keyboard.release_media_keys()
            elif press_without_release:
                self.ble_keyboard.press_media_key(bt_media_command)
            else:
                await self.ble_keyboard.send_media_key(bt_media_command)
            self.logger.debug(f"Sent media command {command.name}")
            return "Command sent"
        else:
            raise HTTPException(status_code=500, detail="Command doesn't include executable action")

    async def send_network_command(self, command: Command):
        try:
            match command.method:
                case NetworkRequestType.GET:
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(command.host)
                        self.logger.debug(f"Sent network command and received {resp.status_code}: {resp.content}")
                        return {
                            "status": resp.status_code,
                            "response": resp.content
                        }
                case NetworkRequestType.POST:
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(command.host, content=command.body)
                        self.logger.debug(f"Sent network command and received {resp.status_code}: {resp.content}")
                        return {
                            "status": resp.status_code,
                            "response": resp.content
                        }
                case NetworkRequestType.DELETE:
                    async with httpx.AsyncClient() as client:
                        resp = await client.delete(command.host)
                        self.logger.debug(f"Sent network command and received {resp.status_code}: {resp.content}")
                        return {
                            "status": resp.status_code,
                            "response": resp.content
                        }
                case NetworkRequestType.HEAD:
                    async with httpx.AsyncClient() as client:
                        resp = await client.head(command.host)
                        self.logger.debug(f"Sent network command and received {resp.status_code}: {resp.content}")
                        return {
                            "status": resp.status_code,
                            "response": resp.content
                        }
                case NetworkRequestType.PATCH:
                    async with httpx.AsyncClient() as client:
                        resp = await client.patch(command.host, content=command.body)
                        self.logger.debug(f"Sent network command and received {resp.status_code}: {resp.content}")
                        return {
                            "status": resp.status_code,
                            "response": resp.content
                        }
                case NetworkRequestType.PUT:
                    async with httpx.AsyncClient() as client:
                        resp = await client.put(command.host, content=command.body)
                        self.logger.debug(f"Sent network command and received {resp.status_code}: {resp.content}")
                        return {
                            "status": resp.status_code,
                            "response": resp.content
                        }
                case None:
                    raise HTTPException(status_code=500, detail="Command doesn't include executable action")

        except httpx.ReadTimeout:
            return "Encountered a timeout"
        except httpx.ConnectError:
            return "All connection attempts failed"

    async def send_script_command(self, command: Command):
        raise HTTPException(status_code=400, detail="Script commands are not implemented yet")

    def send_integration_command(self, command: Command):
        if self.ha_manager is None:
            self.logger.error("Tried to send integration command but HA integration is not set up")
            return

        match command.integration_action:
            case IntegrationAction.TOGGLE_LIGHT:
                self.ha_manager.toggle_light(command.integration_entity)
            case IntegrationAction.BRIGHTNESS_UP:
                self.ha_manager.increase_brightness()
            case IntegrationAction.BRIGHTNESS_DOWN:
                self.ha_manager.decrease_brightness()

    async def start_scene(self, scene_id: int):

        with Session(engine) as session:
            scene_db = session.get(Scene, scene_id)

            if not scene_db:
                raise HTTPException(status_code=404, detail="Scene not found")

            previous_scene = self.status.current_scene
            if previous_scene is not None and scene_db.start_macro is not None:
                skip_power_down_for = set()
                for command in scene_db.start_macro.commands:
                    if command.device_id is not None and (command.button == RemoteButton.POWER_TOGGLE or command.button == RemoteButton.POWER_ON):
                        skip_power_down_for.add(command.device_id)

                await self.stop_current_scene(skip_power_down_for=skip_power_down_for)

            await self._update_current_scene(new_scene=scene_db, new_scene_state=SceneStatus.STARTING)

            bt_address = scene_db.bluetooth_address
            if bt_address and not self.is_dev:
                await self.ble_keyboard.unregister_services()
                await self.ble_keyboard.connect(bt_address)
                await self.ble_keyboard.register_services()

            if scene_db.start_macro is not None:
                await self.execute_macro(scene_db.start_macro, from_start=True)
                #for index, command in enumerate(scene_db.start_macro.commands):
                #    await self.send_db_command(command, from_start=True)
                #    if index < len(scene_db.start_macro.commands)-1:
                #        await asyncio.sleep(scene_db.start_macro.delays[index]/1000)

            if scene_db.keymap:
                self.load_key_map(scene_db.keymap)

            await self._update_current_scene(new_scene=scene_db, new_scene_state=SceneStatus.ACTIVE)

            self.logger.info(f"Scene {scene_db.name} started!")

    def get_current_status(self) -> StatusReport:
        return self.status

    # Updates active scene without executing start commands
    async def set_current_scene(self, scene_id: int):

        with Session(engine) as session:
            scene_db = session.get(Scene, scene_id)

            if not scene_db:
                raise HTTPException(status_code=404, detail="Scene not found")

            bt_address = scene_db.bluetooth_address
            if bt_address:
                await self.ble_keyboard.unregister_services()
                await self.ble_keyboard.connect(bt_address)
                await self.ble_keyboard.register_services()

            previous_scene = self.status.current_scene
            if previous_scene is not None and previous_scene.stop_macro is not None:
                previous_scene_stop_commands = previous_scene.stop_macro.commands
                if previous_scene_stop_commands:
                    await self.set_states_for_commands(previous_scene_stop_commands)

            new_scene_commands = scene_db.start_macro.commands
            if new_scene_commands:
                await self.set_states_for_commands(new_scene_commands)

            await self._update_current_scene(new_scene=scene_db, new_scene_state=SceneStatus.ACTIVE)

            if scene_db.keymap:
                self.load_key_map(scene_db.keymap)

            self.logger.info(f"Set {scene_db.name} as current scene.")

    async def set_state_for_command(self, command: Command):
        if command.device_id is not None:
            if command.command_group == CommandGroupType.INPUT:
                await self.update_device_status(command.device_id, new_power_state=True, new_input=command.id)
            match command.button:
                case RemoteButton.POWER_ON:
                    await self.update_device_status(command.device_id, new_power_state=True)
                case RemoteButton.POWER_OFF:
                    await self.update_device_status(command.device_id, new_power_state=False)
                case RemoteButton.POWER_TOGGLE:
                    await self.update_device_status(command.device_id, toggle_power=True)

    async def set_states_for_commands(self, commands: list[Command]):
        for command in commands:
            await self.set_state_for_command(command)

    async def stop_current_scene(self, skip_power_down_for=None):
        if skip_power_down_for is None:
            skip_power_down_for = set()

        if not self.status.current_scene.id:
            raise HTTPException(status_code=404, detail="No scene active")

        with Session(engine) as session:
            scene_db = session.get(Scene, self.status.current_scene.id)

            self.load_key_map("default")

            if not scene_db:
                raise HTTPException(status_code=404, detail=f"Couldn't find scene with ID {self.status.current_scene.id}.")

            await self._update_current_scene_status(new_scene_state=SceneStatus.STOPPING)

            bt_address = scene_db.bluetooth_address
            if bt_address and not self.is_dev:
                await self.ble_keyboard.disconnect(bt_address)

            if scene_db.stop_macro is not None:
                for index, command_id in enumerate(scene_db.stop_macro.command_ids):
                    command = session.get(Command, command_id)
                    if command is not None:
                        if ((command.device_id is None or command.device_id not in skip_power_down_for)
                                and (command.button == RemoteButton.POWER_TOGGLE or command.button == RemoteButton.POWER_OFF)):
                            await self.send_command(command_id, from_stop=True)
                            if index < len(scene_db.stop_macro.delays):
                                await asyncio.sleep(scene_db.stop_macro.delays[index]/1000)

            await self._update_current_scene(new_scene=None, new_scene_state=None)

            self.logger.info(f"Scene {scene_db.name} stopped!")


    def load_key_map(self, keymap_name: str = "default"):

        with open("config/keymap_scenes.json", "r") as file:
            keymap_scene_data = file.read()
            self.keymap_scene = json.loads(keymap_scene_data)

        with open(f"config/keymap_{keymap_name}.json") as file:
            keymap_data = file.read()
            self.keymap = json.loads(keymap_data)

        self.cached_commands = {}
        for command_id in self.keymap.values():
            if command_id:
                with Session(engine) as session:
                    command_db = session.get(Command, command_id)
                    if command_db:
                        self.cached_commands[command_id] = command_db

        if not self.is_dev:
            self.rf_manager.set_callback(self.handle_button_press)
            self.rf_manager.set_release_callback(self.handle_button_release)
        self.logger.debug(f"Loaded keymap {keymap_name}")

    def suggest_keymap(self, scene: Scene):
        try:
            with open("config/remote_keymap.json", "r") as file:
                keymap_data = file.read()

            keymap_json = json.loads(keymap_data)

        except FileNotFoundError:
            self.logger.warning("\"config/remote_keymap.json\" could not be opened. Can't generate suggested keymap.")
            return {}

        available_buttons = {}
        keymap_suggestion = {}

        for key, value in keymap_json.items():
            available_buttons[value["button"]] = key
            keymap_suggestion[key] = None

        def assign_key_if_exists(device: Device, button: RemoteButton):
            matching_remote_button = available_buttons.get(button)
            if matching_remote_button is not None:
                matching_command = next((x for x in device.commands if x.button == button), None)
                if matching_command is not None:
                    keymap_suggestion[matching_remote_button] = matching_command.id

        # Audio controls
        amplifier = next((x for x in scene.devices if x.type == DeviceType.AMPLIFIER), None)
        if amplifier is not None:
            assign_key_if_exists(amplifier, RemoteButton.VOLUME_UP)
            assign_key_if_exists(amplifier, RemoteButton.VOLUME_DOWN)
            assign_key_if_exists(amplifier, RemoteButton.MUTE)

        player = next((x for x in scene.devices if x.type == DeviceType.PLAYER), None)
        if player is None:
            player = next((x for x in scene.devices if x.type == DeviceType.DISPLAY), None)

        if player is not None:
            assign_key_if_exists(player, RemoteButton.RED)
            assign_key_if_exists(player, RemoteButton.GREEN)
            assign_key_if_exists(player, RemoteButton.YELLOW)
            assign_key_if_exists(player, RemoteButton.BLUE)

            assign_key_if_exists(player, RemoteButton.GUIDE)
            assign_key_if_exists(player, RemoteButton.INFO)

            assign_key_if_exists(player, RemoteButton.EXIT)
            assign_key_if_exists(player, RemoteButton.MENU)

            assign_key_if_exists(player, RemoteButton.DIRECTION_UP)
            assign_key_if_exists(player, RemoteButton.DIRECTION_DOWN)
            assign_key_if_exists(player, RemoteButton.DIRECTION_LEFT)
            assign_key_if_exists(player, RemoteButton.DIRECTION_RIGHT)
            assign_key_if_exists(player, RemoteButton.SELECT)
            assign_key_if_exists(player, RemoteButton.BACK)

            if keymap_suggestion.get(RemoteButton.VOLUME_UP) is None:
                assign_key_if_exists(player, RemoteButton.VOLUME_UP)
            if keymap_suggestion.get(RemoteButton.VOLUME_DOWN) is None:
                assign_key_if_exists(player, RemoteButton.VOLUME_DOWN)
            if keymap_suggestion.get(RemoteButton.MUTE) is None:
                assign_key_if_exists(player, RemoteButton.MUTE)

            assign_key_if_exists(player, RemoteButton.CHANNEL_UP)
            assign_key_if_exists(player, RemoteButton.CHANNEL_DOWN)

            assign_key_if_exists(player, RemoteButton.REWIND)
            assign_key_if_exists(player, RemoteButton.FAST_FORWARD)
            # TODO: Merge Play, Pause and Playpause here (i.e. put play on playpause and vice versa)?
            assign_key_if_exists(player, RemoteButton.PLAY)
            assign_key_if_exists(player, RemoteButton.PAUSE)
            assign_key_if_exists(player, RemoteButton.PLAYPAUSE)
            assign_key_if_exists(player, RemoteButton.STOP)
            assign_key_if_exists(player, RemoteButton.RECORD)

            assign_key_if_exists(player, RemoteButton.NUMBER_ONE)
            assign_key_if_exists(player, RemoteButton.NUMBER_TWO)
            assign_key_if_exists(player, RemoteButton.NUMBER_THREE)
            assign_key_if_exists(player, RemoteButton.NUMBER_FOUR)
            assign_key_if_exists(player, RemoteButton.NUMBER_FIVE)
            assign_key_if_exists(player, RemoteButton.NUMBER_SIX)
            assign_key_if_exists(player, RemoteButton.NUMBER_SEVEN)
            assign_key_if_exists(player, RemoteButton.NUMBER_EIGHT)
            assign_key_if_exists(player, RemoteButton.NUMBER_NINE)
            assign_key_if_exists(player, RemoteButton.NUMBER_ZERO)

        return keymap_suggestion

    def handle_button_press(self, button):
        if button == "Off":
            self.queue.enqueue_task(self.stop_current_scene())
            return

        scene_id = self.keymap_scene.get(button)
        if scene_id:
            self.queue.enqueue_task(self.start_scene(scene_id))
            return

        command_id = self.keymap.get(button)
        if command_id:
            self.queue.enqueue_task(self.send_command(command_id, press_without_release=True))

    def _release_all(self, _):
        self.ir_manager.stop_repeating()
        self.ble_keyboard.release_keys()
        self.ble_keyboard.release_media_keys()

    def handle_button_release(self, _):
        self.queue.enqueue_sync_task(self._release_all, self)

    async def update_device_status(self, device_id: int, new_power_state: bool | None = None, new_input: int | None = None, toggle_power: bool | None = None):

        self.status.devices.set_state(device_id, new_power_state=new_power_state, new_input=new_input, toggle_power=toggle_power)

        if self.status_callback is not None:
            await self.status_callback(self.status)

    async def _update_current_scene_status(self, new_scene_state: SceneStatus | None):
        self.status.scene_status = new_scene_state

        if self.status_callback is not None:
            await self.status_callback(self.status)

    async def _update_current_scene(self, new_scene: Scene | None, new_scene_state: SceneStatus | None):
        self.status.current_scene = new_scene
        self.status.scene_status = new_scene_state

        if self.status_callback is not None:
            await self.status_callback(self.status)

    async def start_ble_advertisement(self):
        await self.ble_keyboard.advertise()

    async def start_ble_pairing(self):
        await self.ble_keyboard.initiate_pairing()

    async def get_ble_devices(self) -> [BleDevice]:
        devices = await self.ble_keyboard.devices

        ble_devices: list[BleDevice] = []

        for device in devices:
            ble_device = BleDevice(
                name = device.get("alias"),
                address = device.get("address"),
                connected = True if device.get("connected") else False,
                paired = True if device.get("paired") else False
            )
            ble_devices.append(ble_device)

        return ble_devices

    async def ble_connect(self, address: str):
        await self.ble_keyboard.connect(address)

    async def ble_disconnect(self):
        await self.ble_keyboard.disconnect()