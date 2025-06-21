import logging

from sqlalchemy import Boolean
from sqlmodel import Session

from BleKeyboard.BleKeyboard import BleKeyboard
from DbManager.DbManager import DbManager
from IrManager.IrManager import IrManager
from RfManager.RfManager import RfManager


from sqlmodel import select

from Api.models.UserImage import UserImage


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




