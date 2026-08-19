from Api.models.Command import Command
from Api.models.CommandGroupType import CommandGroupType
from Api.models.CommandType import CommandType
from Api.models.RemoteButton import RemoteButton
from Hub.EventBus import Directive
from Hub.interfaces import ActionExecutor
from ScriptExecutor.ScriptExecutor import ScriptExecutor


def test_is_an_action_executor():
    assert issubclass(ScriptExecutor, ActionExecutor)
    assert ScriptExecutor.name == "script"


async def test_execute_does_not_raise(caplog):
    executor = ScriptExecutor()
    command = Command(
        name="cmd",
        button=RemoteButton.SELECT,
        type=CommandType.SCRIPT,
        command_group=CommandGroupType.OTHER,
    )

    await executor.execute(Directive(command_id=1), command)

    assert "not implemented" in caplog.text
