import stat

from Api.models.Command import Command
from Api.models.CommandGroupType import CommandGroupType
from Api.models.CommandType import CommandType
from Api.models.RemoteButton import RemoteButton
from Hub.EventBus import Directive
from Hub.interfaces import ActionExecutor
from ScriptExecutor.ScriptExecutor import ScriptExecutor


def _command(**overrides) -> Command:
    defaults = dict(
        name="cmd",
        button=RemoteButton.SELECT,
        type=CommandType.SCRIPT,
        command_group=CommandGroupType.OTHER,
    )
    defaults.update(overrides)
    return Command(**defaults)


def _write_script(tmp_path, name: str, body: str, executable: bool = True):
    script = tmp_path / name
    script.write_text(f"#!/bin/sh\n{body}\n")
    if executable:
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


def test_is_an_action_executor():
    assert issubclass(ScriptExecutor, ActionExecutor)
    assert ScriptExecutor.name == "script"


async def test_execute_runs_the_script(tmp_path):
    marker = tmp_path / "ran"
    _write_script(tmp_path, "touch_marker.sh", f"touch {marker}")
    executor = ScriptExecutor(scripts_dir=str(tmp_path))

    await executor.execute(Directive(command_id=1), _command(script_path="touch_marker.sh"))

    assert marker.exists()


async def test_execute_without_script_path_runs_nothing(tmp_path):
    executor = ScriptExecutor(scripts_dir=str(tmp_path))

    await executor.execute(Directive(command_id=1), _command(script_path=None))

    assert list(tmp_path.iterdir()) == []


async def test_execute_rejects_path_traversal_outside_scripts_dir(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    marker = tmp_path / "escaped"
    _write_script(tmp_path, "evil.sh", f"touch {marker}")
    executor = ScriptExecutor(scripts_dir=str(scripts_dir))

    await executor.execute(Directive(command_id=1), _command(script_path="../evil.sh"))

    assert not marker.exists()


async def test_execute_rejects_missing_script(tmp_path):
    executor = ScriptExecutor(scripts_dir=str(tmp_path))

    await executor.execute(Directive(command_id=1), _command(script_path="does_not_exist.sh"))  # should not raise


async def test_execute_rejects_non_executable_script(tmp_path):
    marker = tmp_path / "ran"
    _write_script(tmp_path, "not_executable.sh", f"touch {marker}", executable=False)
    executor = ScriptExecutor(scripts_dir=str(tmp_path))

    await executor.execute(Directive(command_id=1), _command(script_path="not_executable.sh"))

    assert not marker.exists()


async def test_execute_kills_the_process_on_timeout(tmp_path):
    marker = tmp_path / "finished"
    _write_script(tmp_path, "slow.sh", f"sleep 5 && touch {marker}")
    executor = ScriptExecutor(scripts_dir=str(tmp_path), timeout_seconds=0.2)

    await executor.execute(Directive(command_id=1), _command(script_path="slow.sh"))

    assert not marker.exists()  # killed before the sleep completed
