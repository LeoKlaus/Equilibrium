from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from Hub.CommandDispatcher import CommandDispatcher
from Hub.EventBus import Event, EventBus
from Hub.KeymapResolver import KeymapResolver, SendDirective, StartScene, StopScene
from Hub.SceneManager import SceneManager

if TYPE_CHECKING:
    from BleKeyboard.BleKeyboard import BleKeyboard
    from IrManager.IrManager import IrManager


class InputRouter:
    """Subscribes to key_pressed/key_released and turns a raw button into
    an action via KeymapResolver, delegating to SceneManager or
    CommandDispatcher.

    Release is unconditional rather than resolved through the keymap - it
    just clears whatever's currently held, matching what physically
    releasing the remote button should always do regardless of what that
    button was mapped to.

    Harmony Companion remote does not send a release signal between two rapid presses of
    the SAME button - it sends pressed, repeated, pressed again, repeated,
    then a single released at the end of the whole gesture. Dispatching a
    directive on every key_pressed without accounting for this relays a
    rapid double-tap as one hold instead of two distinct
    presses, since there's no release in between to produce a second
    key-down/key-up transition. _held_button tracks this so a repeated
    press of the same button forces a release first.
    """

    logger = logging.getLogger(__package__)

    def __init__(
        self,
        keymap_resolver: KeymapResolver,
        scene_manager: SceneManager,
        command_dispatcher: CommandDispatcher,
        ble_keyboard: BleKeyboard | None = None,
        ir_manager: IrManager | None = None,
    ) -> None:
        self._keymap_resolver = keymap_resolver
        self._scene_manager = scene_manager
        self._command_dispatcher = command_dispatcher
        self._ble_keyboard = ble_keyboard
        self._ir_manager = ir_manager
        self._held_button: str | None = None

    def subscribe(self, bus: EventBus) -> None:
        bus.subscribe("key_pressed", self._on_key_pressed)
        bus.subscribe("key_released", self._on_key_released)

    async def _on_key_pressed(self, event: Event) -> None:
        button = event.payload.get("button")
        if button is None:
            return

        if button == self._held_button:
            self._release_held()

        resolution = self._keymap_resolver.resolve(button)

        match resolution:
            case StopScene():
                await self._scene_manager.stop_current_scene()
            case StartScene(scene_id=scene_id):
                await self._scene_manager.start_scene(scene_id)
            case SendDirective(directive=directive):
                await self._command_dispatcher.dispatch(directive)
                self._held_button = button
            case None:
                self.logger.debug(f"No action mapped for button '{button}'")

    async def _on_key_released(self, _: Event) -> None:
        self._release_held()
        self._held_button = None

    def _release_held(self) -> None:
        if self._ir_manager is not None:
            self._ir_manager.stop_repeating()
        if self._ble_keyboard is not None:
            self._ble_keyboard.release_keys()
            self._ble_keyboard.release_media_keys()
