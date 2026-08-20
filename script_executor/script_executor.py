import asyncio
import logging
import os
from pathlib import Path

from api.models.command import Command
from hub.event_bus import Directive
from hub.interfaces import ActionExecutor

_DEFAULT_TIMEOUT_SECONDS = 30


class ScriptExecutor(ActionExecutor):
    """Runs a shell script from a fixed, confined directory.

    TODO(rewrite): Commands (including script_path) are created through the
    HTTP API, so without the confinement below this would be arbitrary
    remote code execution. When Hub wiring is built, this executor must be
    disabled by default and require an explicit opt-in flag, with a clear
    warning about the security implications surfaced at startup - do not
    register it unconditionally alongside the other executors.
    """

    name = "script"

    logger = logging.getLogger(__package__)

    def __init__(self, scripts_dir: str = "config/scripts", timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS) -> None:
        self._scripts_dir = Path(scripts_dir).resolve()
        self._timeout_seconds = timeout_seconds

    async def execute(self, directive: Directive, command: Command) -> None:
        if not command.script_path:
            self.logger.error(f"Command {command.name} doesn't include a script_path")
            return

        script = self._resolve(command.script_path)
        if script is None:
            self.logger.error(
                f"Command {command.name}: script_path '{command.script_path}' resolves outside "
                f"the scripts directory, refusing to run it"
            )
            return

        if not script.is_file():
            self.logger.error(f"Command {command.name}: script '{script}' does not exist")
            return

        if not os.access(script, os.X_OK):
            self.logger.error(f"Command {command.name}: script '{script}' is not executable")
            return

        process = await asyncio.create_subprocess_exec(
            str(script),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self._timeout_seconds)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            self.logger.error(f"Command {command.name}: script '{script}' timed out after {self._timeout_seconds}s")
            return

        self.logger.debug(
            f"Ran script '{script}' for command {command.name}, exit code {process.returncode}: "
            f"stdout={stdout.decode(errors='replace')!r} stderr={stderr.decode(errors='replace')!r}"
        )

    def _resolve(self, script_path: str) -> Path | None:
        candidate = (self._scripts_dir / script_path).resolve()
        if not candidate.is_relative_to(self._scripts_dir):
            return None
        return candidate
