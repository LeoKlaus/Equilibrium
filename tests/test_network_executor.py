import httpx2
import pytest

from api.models.command import Command
from api.models.command_group_type import CommandGroupType
from api.models.command_type import CommandType
from api.models.network_request_type import NetworkRequestType
from api.models.remote_button import RemoteButton
from hub.event_bus import Directive
from network_executor.network_executor import NetworkExecutor


def _command(**overrides) -> Command:
    defaults = {
        "name": "cmd",
        "button": RemoteButton.SELECT,
        "type": CommandType.NETWORK,
        "command_group": CommandGroupType.OTHER,
        "host": "https://device.local/api",
        "method": NetworkRequestType.GET,
    }
    defaults.update(overrides)
    return Command(**defaults)


def _executor(handler) -> NetworkExecutor:
    return NetworkExecutor(transport=httpx2.MockTransport(handler))


async def test_execute_get_sends_request_with_headers():
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, content=b"ok")

    executor = _executor(handler)
    command = _command(headers={"X-Test": "1"})

    await executor.execute(Directive(command_id=1), command)

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == "https://device.local/api"
    assert requests[0].headers["x-test"] == "1"


@pytest.mark.parametrize("method", [
    NetworkRequestType.GET,
    NetworkRequestType.POST,
    NetworkRequestType.DELETE,
    NetworkRequestType.HEAD,
    NetworkRequestType.PATCH,
    NetworkRequestType.PUT,
])
async def test_execute_uses_the_correct_http_method(method):
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200)

    executor = _executor(handler)
    command = _command(method=method)

    await executor.execute(Directive(command_id=1), command)

    assert requests[0].method == method.value.upper()


async def test_execute_post_sends_the_body():
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200)

    executor = _executor(handler)
    command = _command(method=NetworkRequestType.POST, body="hello")

    await executor.execute(Directive(command_id=1), command)

    assert requests[0].content == b"hello"


async def test_execute_get_sends_no_body():
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200)

    executor = _executor(handler)
    command = _command(method=NetworkRequestType.GET)

    await executor.execute(Directive(command_id=1), command)

    assert requests[0].content == b""


async def test_execute_without_host_makes_no_request():
    calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(200)

    executor = _executor(handler)
    command = _command(host=None)

    await executor.execute(Directive(command_id=1), command)

    assert calls == []


async def test_execute_without_method_makes_no_request():
    calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(200)

    executor = _executor(handler)
    command = _command(method=None)

    await executor.execute(Directive(command_id=1), command)

    assert calls == []


async def test_execute_handles_read_timeout():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timed out", request=request)

    executor = _executor(handler)

    await executor.execute(Directive(command_id=1), _command())  # should not raise


async def test_execute_handles_connect_error():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    executor = _executor(handler)

    await executor.execute(Directive(command_id=1), _command())  # should not raise
