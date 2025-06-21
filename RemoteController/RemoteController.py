import logging
from asyncio import CancelledError

import httpx
from fastapi import HTTPException
from sqlalchemy import Boolean
from sqlalchemy.util import await_only
from sqlmodel import Session

from Api.models.Command import CommandBase, Command
from Api.models.CommandGroup import CommandGroup
from Api.models.CommandType import CommandType
from Api.models.NetworkRequestType import NetworkRequestType
from BleKeyboard.BleKeyboard import BleKeyboard
from DbManager.DbManager import DbManager
from IrManager.IrManager import IrManager, AsyncCallback
from RfManager.RfManager import RfManager


class RemoteController:

    logger: logging
    is_dev: Boolean
    ble_keyboard: BleKeyboard
    rf_manager: RfManager
    ir_manager: IrManager
    db_session: Session

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


    async def send_command(self, command_id: int, press_without_release = False):
        command_db = self.db_session.get(Command, command_id)

        if not command_db:
            raise HTTPException(status_code=404, detail="Command not found")

        match command_db.type:
            case CommandType.IR:
                return await self.send_ir_command(command_db, press_without_release=press_without_release)
            case CommandType.BLUETOOTH:
                return await self.send_bt_command(command_db, press_without_release=press_without_release)
            case CommandType.NETWORK:
                return await self.send_network_command(command_db)
            case CommandType.SCRIPT:
                return await self.send_script_command(command_db)
        raise HTTPException(status_code=400, detail=f"Command {command_db.name} found, but type {command_db.type} is invalid.")

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
