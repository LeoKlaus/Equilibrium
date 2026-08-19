import logging

from Api.models.Command import Command
from Hub.EventBus import Directive
from Hub.interfaces import ActionExecutor


class ScriptExecutor(ActionExecutor):
    """Stub - script commands aren't implemented yet, carried over from
    RemoteController.send_script_command."""

    name = "script"

    logger = logging.getLogger(__package__)

    async def execute(self, directive: Directive, command: Command) -> None:
        self.logger.error(f"Command {command.name}: script commands are not implemented yet")
