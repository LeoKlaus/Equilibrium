from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from sqlmodel import Session

from Api.models.Command import Command
from Api.models.RemoteButton import RemoteButton
from Api.models.Scene import Scene
from Api.models.SceneStatus import SceneStatus
from DbManager.DbManager import engine
from Hub.CommandDispatcher import CommandDispatcher
from Hub.EventBus import Directive
from Hub.KeymapResolver import KeymapResolver
from Hub.StatusStore import StatusStore

if TYPE_CHECKING:
    from BleKeyboard.BleKeyboard import BleKeyboard


class SceneNotFoundError(Exception):
    pass


class NoActiveSceneError(Exception):
    pass


class SceneManager:
    """Owns scene start/stop/switch orchestration. Holds no state itself -
    reads/writes StatusStore, swaps the active keymap via KeymapResolver,
    runs macros via CommandDispatcher, and connects/disconnects BLE for
    scenes with a bluetooth_address.

    ble_keyboard is optional: pass None to run without BLE (e.g. dev mode)
    and scene-level BLE connect/disconnect becomes a no-op, rather than
    threading an is_dev flag through this class's logic.
    """

    logger = logging.getLogger(__package__)

    def __init__(
        self,
        status_store: StatusStore,
        keymap_resolver: KeymapResolver,
        command_dispatcher: CommandDispatcher,
        ble_keyboard: BleKeyboard | None = None,
    ) -> None:
        self._status_store = status_store
        self._keymap_resolver = keymap_resolver
        self._command_dispatcher = command_dispatcher
        self._ble_keyboard = ble_keyboard

    async def start_scene(self, scene_id: int) -> None:
        with Session(engine) as session:
            scene = session.get(Scene, scene_id)
            if scene is None:
                raise SceneNotFoundError(f"No scene with id {scene_id}")

            previous_scene = self._status_store.status.current_scene
            if previous_scene is not None and scene.start_macro is not None:
                skip_power_down_for = {
                    command.device_id
                    for command in scene.start_macro.commands
                    if command.device_id is not None
                    and command.button in (RemoteButton.POWER_TOGGLE, RemoteButton.POWER_ON)
                }
                await self.stop_current_scene(skip_power_down_for=skip_power_down_for)

            await self._status_store.set_scene(scene, SceneStatus.STARTING)

            await self._connect_ble_for_scene(scene)

            if scene.start_macro is not None:
                await self._command_dispatcher.execute_macro(scene.start_macro, from_start=True)

            if scene.keymap:
                self._keymap_resolver.load_key_map(scene.keymap)

            await self._status_store.set_scene(scene, SceneStatus.ACTIVE)

            self.logger.info(f"Scene {scene.name} started!")

    async def set_current_scene(self, scene_id: int) -> None:
        """Switch the tracked scene without running its start commands."""
        with Session(engine) as session:
            scene = session.get(Scene, scene_id)
            if scene is None:
                raise SceneNotFoundError(f"No scene with id {scene_id}")

            await self._connect_ble_for_scene(scene)

            previous_scene = self._status_store.status.current_scene
            if previous_scene is not None and previous_scene.stop_macro is not None:
                if previous_scene.stop_macro.commands:
                    await self._command_dispatcher.update_states_for_commands(previous_scene.stop_macro.commands)

            if scene.start_macro is not None and scene.start_macro.commands:
                await self._command_dispatcher.update_states_for_commands(scene.start_macro.commands)

            await self._status_store.set_scene(scene, SceneStatus.ACTIVE)

            if scene.keymap:
                self._keymap_resolver.load_key_map(scene.keymap)

            self.logger.info(f"Set {scene.name} as current scene.")

    async def stop_current_scene(self, skip_power_down_for: set[int] | None = None) -> None:
        skip_power_down_for = skip_power_down_for or set()

        current_scene = self._status_store.status.current_scene
        if current_scene is None or current_scene.id is None:
            raise NoActiveSceneError("No scene active")

        with Session(engine) as session:
            scene = session.get(Scene, current_scene.id)
            if scene is None:
                raise SceneNotFoundError(f"No scene with id {current_scene.id}")

            self._keymap_resolver.load_key_map("default")

            await self._status_store.set_scene_status(SceneStatus.STOPPING)

            if scene.bluetooth_address and self._ble_keyboard is not None:
                await self._ble_keyboard.disconnect(scene.bluetooth_address)

            if scene.stop_macro is not None:
                for index, command_id in enumerate(scene.stop_macro.command_ids):
                    command = session.get(Command, command_id)
                    if command is None:
                        continue
                    if command.device_id is not None and command.device_id in skip_power_down_for:
                        continue
                    if command.button not in (RemoteButton.POWER_TOGGLE, RemoteButton.POWER_OFF):
                        continue

                    await self._command_dispatcher.dispatch(Directive(command_id=command_id), from_stop=True)
                    if index < len(scene.stop_macro.delays):
                        await asyncio.sleep(scene.stop_macro.delays[index] / 1000)

            await self._status_store.set_scene(None, None)

            self.logger.info(f"Scene {scene.name} stopped!")

    async def _connect_ble_for_scene(self, scene: Scene) -> None:
        if not scene.bluetooth_address or self._ble_keyboard is None:
            return
        await self._ble_keyboard.unregister_services()
        await self._ble_keyboard.connect(scene.bluetooth_address)
        await self._ble_keyboard.register_services()
