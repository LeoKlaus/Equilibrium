import asyncio
import logging

from Api.models.Command import Command
from Api.models.CommandGroupType import CommandGroupType
from Api.models.Macro import Macro
from Api.models.RemoteButton import RemoteButton
from hub.event_bus import Directive
from hub.interfaces import ActionExecutor
from hub.keymap_resolver import KeymapResolver
from hub.status_store import StatusStore


class CommandDispatcher:
    """Resolves a Directive to a stored Command and hands it to the
    registered ActionExecutor for that command's type.

    `executors` is keyed by CommandType.value, e.g. {"ir": ..., "bluetooth":
    ...}. Injected rather than looked up on a Hub so this can be tested
    with fake executors before real modules are ported.
    """

    logger = logging.getLogger(__package__)

    def __init__(
        self,
        status_store: StatusStore,
        keymap_resolver: KeymapResolver,
        executors: dict[str, ActionExecutor],
    ) -> None:
        self._status_store = status_store
        self._keymap_resolver = keymap_resolver
        self._executors = executors

    async def dispatch(
        self,
        directive: Directive,
        from_start: bool = False,
        from_stop: bool = False,
    ) -> None:
        command = self._keymap_resolver.get_command(directive.command_id)
        if command is None:
            self.logger.error(
                f"Tried to dispatch command {directive.command_id}, which doesn't exist in the database."
            )
            return

        if self._should_skip(command, from_start=from_start, from_stop=from_stop):
            return

        executor = self._executors.get(command.type.value)
        if executor is None:
            self.logger.error(f"No executor registered for command type '{command.type.value}'.")
            return

        await executor.execute(directive, command)

        # Deliberately not tracking state on plain sends, only on scene
        # start/stop: tracking every manual send broke scenes when a user
        # corrected a device by hand (e.g. turning on a TV that missed its
        # initial command) - the manual correction got treated as the
        # canonical state instead of a one-off fix.
        if from_start or from_stop:
            await self.update_state_for_command(command)

    def _should_skip(self, command: Command, from_start: bool, from_stop: bool) -> bool:
        if command.device_id is None:
            return False

        if from_start:
            state = self._status_store.status.devices.state(for_device_id=command.device_id)
            if command.button in (RemoteButton.POWER_ON, RemoteButton.POWER_TOGGLE) and state.powered:
                return True
            if command.command_group == CommandGroupType.INPUT and state.input == command.id:
                return True

        if from_stop:
            state = self._status_store.status.devices.state(for_device_id=command.device_id)
            if command.button in (RemoteButton.POWER_OFF, RemoteButton.POWER_TOGGLE) and not state.powered:
                return True

        return False

    async def update_state_for_command(self, command: Command) -> None:
        if command.device_id is None:
            return

        if command.command_group == CommandGroupType.INPUT:
            await self._status_store.set_device_state(command.device_id, new_power_state=True, new_input=command.id)

        if command.button == RemoteButton.POWER_ON:
            await self._status_store.set_device_state(command.device_id, new_power_state=True)
        elif command.button == RemoteButton.POWER_OFF:
            await self._status_store.set_device_state(command.device_id, new_power_state=False)
        elif command.button == RemoteButton.POWER_TOGGLE:
            await self._status_store.set_device_state(command.device_id, toggle_power=True)

    async def update_states_for_commands(self, commands: list[Command]) -> None:
        for command in commands:
            await self.update_state_for_command(command)

    async def execute_macro(self, macro: Macro, from_start: bool = False, from_stop: bool = False) -> None:
        for index, command_id in enumerate(macro.command_ids):
            await self.dispatch(
                Directive(command_id=command_id),
                from_start=from_start,
                from_stop=from_stop,
            )
            if index < len(macro.delays):
                await asyncio.sleep(macro.delays[index] / 1000)
