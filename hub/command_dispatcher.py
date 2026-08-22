import asyncio
import contextlib
import logging

from api.models.command import Command
from api.models.command_group_type import CommandGroupType
from api.models.command_type import CommandType
from api.models.macro import Macro
from api.models.remote_button import RemoteButton
from hub.event_bus import Directive
from hub.interfaces import ActionExecutor
from hub.keymap_resolver import KeymapResolver
from hub.status_store import StatusStore

# Commands that may be executed in the background without being awaited
_BACKGROUND_ELIGIBLE_TYPES = frozenset({CommandType.NETWORK, CommandType.INTEGRATION, CommandType.SCRIPT})


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
        self._background_tasks: set[asyncio.Task] = set()

    def _resolve(
        self,
        directive: Directive,
        from_start: bool,
        from_stop: bool,
    ) -> tuple[Command, ActionExecutor] | None:
        """Resolves a directive to its Command and registered ActionExecutor,
        applying the skip-if-already-in-that-state check. Returns None
        (having already logged why) if the command doesn't exist, should be
        skipped, or has no registered executor for its type."""
        command = self._keymap_resolver.get_command(directive.command_id)
        if command is None:
            self.logger.error(
                f"Tried to dispatch command {directive.command_id}, which doesn't exist in the database."
            )
            return None

        if self._should_skip(command, from_start=from_start, from_stop=from_stop):
            return None

        executor = self._executors.get(command.type.value)
        if executor is None:
            self.logger.error(f"No executor registered for command type '{command.type.value}'.")
            return None

        return command, executor

    async def dispatch(
        self,
        directive: Directive,
        from_start: bool = False,
        from_stop: bool = False,
    ) -> None:
        resolved = self._resolve(directive, from_start=from_start, from_stop=from_stop)
        if resolved is None:
            return
        command, executor = resolved

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
            directive = Directive(command_id=command_id)
            is_last = index == len(macro.command_ids) - 1
            next_delay = macro.delays[index] if index < len(macro.delays) else 0

            command = self._keymap_resolver.get_command(command_id)
            run_in_background = (
                command is not None
                and command.type in _BACKGROUND_ELIGIBLE_TYPES
                and (is_last or next_delay == 0)
            )

            if run_in_background:
                resolved = self._resolve(directive, from_start=from_start, from_stop=from_stop)
                if resolved is not None:
                    command, executor = resolved
                    if from_start or from_stop:
                        await self.update_state_for_command(command)
                    self._run_in_background(executor, directive, command)
            else:
                await self.dispatch(directive, from_start=from_start, from_stop=from_stop)

            if index < len(macro.delays):
                await asyncio.sleep(macro.delays[index] / 1000)

    def _run_in_background(self, executor: ActionExecutor, directive: Directive, command: Command) -> None:
        """Fires executor.execute() without waiting for it. Exceptions are
        only logged, not propagated - by the time one could occur,
        execute_macro() has already moved on and there's nothing left to
        report it to."""
        task = asyncio.create_task(self._execute_and_log(executor, directive, command))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _execute_and_log(self, executor: ActionExecutor, directive: Directive, command: Command) -> None:
        try:
            await executor.execute(directive, command)
        except Exception:
            self.logger.exception(f"Background execution of command {command.name} failed")

    async def shutdown(self) -> None:
        """Cancels any command executions still running in the background
        (see execute_macro()) so the app doesn't exit with tasks orphaned
        mid-flight."""
        tasks = list(self._background_tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
