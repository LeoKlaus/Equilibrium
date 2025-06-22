import json
import logging
from asyncio import CancelledError
from typing import Dict

import httpx
from fastapi import HTTPException
from sqlalchemy import Boolean
from sqlmodel import Session

from Api.models.Command import CommandBase, Command
from Api.models.CommandGroup import CommandGroup
from Api.models.CommandType import CommandType
from Api.models.NetworkRequestType import NetworkRequestType
from Api.models.Scene import Scene
from BleKeyboard.BleKeyboard import BleKeyboard
from DbManager.DbManager import DbManager
from IrManager.IrManager import IrManager, AsyncCallback
from RemoteController.AsyncQueueManager import AsyncQueueManager
from RfManager.RfManager import RfManager


class RemoteController:

    active_scene_id: int|None = None

    keymap: Dict[str, int] = []
    keymap_scene: Dict[str, int] = []

    logger: logging
    is_dev: Boolean
    ble_keyboard: BleKeyboard
    rf_manager: RfManager
    ir_manager: IrManager
    db_session: Session
    queue: AsyncQueueManager

    @classmethod
    async def create(cls, dev: bool = False):
        self = cls()

        self.logger = logging.getLogger(__package__)

        self.is_dev = dev

        if not dev:
            self.ble_keyboard = await BleKeyboard.create()

            self.rf_manager = RfManager()
            self.rf_manager.start_listener()

            self.ir_manager = IrManager()

        self.db_session = DbManager().get_session()

        self.queue = AsyncQueueManager()

        self.load_key_map()

        self.logger.debug("Remote controller ready")

        return self


    async def shutdown(self):
        if not self.is_dev:
            self.ir_manager.cancel_recording()
            self.rf_manager.stop_listener()
            await self.ble_keyboard.disconnect()


    async def record_ir_command(self, data, callback: AsyncCallback):
        new_command = CommandBase.model_validate(data)
        if new_command:
            db_command_group = self.db_session.get(CommandGroup, new_command.command_group_id)
            if db_command_group:
                db_command = Command.model_validate(data)
                db_command.command_group_id = new_command.command_group_id
                try:
                    code = await self.ir_manager.record_command(new_command.name, callback)

                    if code:
                        db_command.ir_action = code

                        self.db_session.add(db_command)
                        self.db_session.commit()
                        self.db_session.refresh(db_command)
                        await callback(f"Command {db_command.id} created")
                except CancelledError:
                    await callback("Recording cancelled, please try again.")

    async def send_db_command(self, command: Command, press_without_release = False):
        match command.type:
            case CommandType.IR:
                return await self.send_ir_command(command, press_without_release=press_without_release)
            case CommandType.BLUETOOTH:
                return await self.send_bt_command(command, press_without_release=press_without_release)
            case CommandType.NETWORK:
                return await self.send_network_command(command)
            case CommandType.SCRIPT:
                return await self.send_script_command(command)

        raise HTTPException(
            status_code=400,
            detail=f"Command {command.name} found, but type {command.type} is invalid."
        )

    async def send_command(self, command_id: int, press_without_release = False):
        command_db = self.db_session.get(Command, command_id)

        if not command_db:
            raise HTTPException(status_code=404, detail="Command not found")

        await self.send_db_command(command_db, press_without_release)



    async def send_ir_command(self, command: Command, press_without_release = False):
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
                        return {
                            "status": resp.status_code,
                            "response": resp.content
                        }
                case NetworkRequestType.POST:
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(command.host, content=command.body)
                        return {
                            "status": resp.status_code,
                            "response": resp.content
                        }
                case NetworkRequestType.DELETE:
                    async with httpx.AsyncClient() as client:
                        resp = await client.delete(command.host)
                        return {
                            "status": resp.status_code,
                            "response": resp.content
                        }
                case NetworkRequestType.HEAD:
                    async with httpx.AsyncClient() as client:
                        resp = await client.head(command.host)
                        return {
                            "status": resp.status_code,
                            "response": resp.content
                        }
                case NetworkRequestType.PATCH:
                    async with httpx.AsyncClient() as client:
                        resp = await client.patch(command.host, content=command.body)
                        return {
                            "status": resp.status_code,
                            "response": resp.content
                        }
                case NetworkRequestType.PUT:
                    async with httpx.AsyncClient() as client:
                        resp = await client.put(command.host, content=command.body)
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

    async def start_scene(self, scene_id: int):

        scene_db = self.db_session.get(Scene, scene_id)

        if not scene_db:
            raise HTTPException(status_code=404, detail="Scene not found")

        bt_address = scene_db.bluetooth_address
        if bt_address:
            await self.ble_keyboard.unregister_services()
            await self.ble_keyboard.connect(bt_address)
            await self.ble_keyboard.register_services()

        for command in scene_db.start_commands:
            await self.send_db_command(command)
            # TODO: Check whether using no delay causes issues here
            #await asyncio.sleep(0.5)

        self.active_scene_id = scene_db.id

        if scene_db.keymap:
            self.load_key_map(scene_db.keymap)

        self.logger.info(f"Scene {scene_db.name} started!")

    def get_current_scene(self):
        if not self.active_scene_id:
            raise HTTPException(status_code=404, detail="No scene active")

        scene_db = self.db_session.get(Scene, self.active_scene_id)

        if not scene_db:
            raise HTTPException(status_code=404, detail=f"Couldn't find scene with ID {self.active_scene_id}.")

        return scene_db

    # Updates active scene without executing start commands
    async def set_current_scene(self, scene_id: int):

        scene_db = self.db_session.get(Scene, scene_id)

        if not scene_db:
            raise HTTPException(status_code=404, detail="Scene not found")

        bt_address = scene_db.bluetooth_address
        if bt_address:
            await self.ble_keyboard.unregister_services()
            await self.ble_keyboard.connect(bt_address)
            await self.ble_keyboard.register_services()

        self.active_scene_id = scene_db.id

        if scene_db.keymap:
            self.load_key_map(scene_db.keymap)

        self.logger.info(f"Set {scene_db.name} as current scene.")


    async def stop_current_scene(self):
        if not self.active_scene_id:
            raise HTTPException(status_code=404, detail="No scene active")

        scene_db = self.db_session.get(Scene, self.active_scene_id)

        self.load_key_map("default")

        if not scene_db:
            raise HTTPException(status_code=404, detail=f"Couldn't find scene with ID {self.active_scene_id}.")

        bt_address = scene_db.bluetooth_address
        if bt_address:
            await self.ble_keyboard.disconnect(bt_address)

        for command in scene_db.stop_commands:
            await self.send_db_command(command)
            # TODO: Check whether using no delay causes issues here
            #await asyncio.sleep(0.5)

        self.active_scene_id = None

        self.logger.info(f"Scene {scene_db.name} stopped!")

    def load_key_map(self, keymap_name: str = "default"):

        with open("config/keymap_scenes.json", "r") as file:
            keymap_scene_data = file.read()
            self.keymap_scene = json.loads(keymap_scene_data)

        with open(f"config/keymap_{keymap_name}.json") as file:
            keymap_data = file.read()
            self.keymap = json.loads(keymap_data)

        if not self.is_dev:
            self.rf_manager.set_callback(self.handle_button_press)
            self.rf_manager.set_release_callback(self.handle_button_release)
        self.logger.debug(f"Loaded keymap {keymap_name}")

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

    def handle_button_release(self, _):
        self.ble_keyboard.release_keys()
        self.ble_keyboard.release_media_keys()
        self.ir_manager.stop_repeating()

