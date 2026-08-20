import logging

import httpx2

from api.models.command import Command
from api.models.network_request_type import NetworkRequestType
from hub.event_bus import Directive
from hub.interfaces import ActionExecutor

_METHODS_WITH_BODY = {NetworkRequestType.POST, NetworkRequestType.PATCH, NetworkRequestType.PUT}


class NetworkExecutor(ActionExecutor):

    name = "network"

    logger = logging.getLogger(__package__)

    def __init__(self, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        # transport is a testing hook - None means httpx2's real network transport.
        self._transport = transport

    async def execute(self, directive: Directive, command: Command) -> None:
        if not command.host or command.method is None:
            self.logger.error(f"Command {command.name} doesn't include a host and method")
            return

        try:
            async with httpx2.AsyncClient(headers=command.headers, transport=self._transport) as client:
                request = getattr(client, command.method.value)
                if command.method in _METHODS_WITH_BODY:
                    response = await request(command.host, content=command.body)
                else:
                    response = await request(command.host)
        except httpx2.ReadTimeout:
            self.logger.error(f"Network command {command.name} timed out")
            return
        except httpx2.ConnectError:
            self.logger.error(f"Network command {command.name}: all connection attempts failed")
            return

        self.logger.debug(f"Sent network command {command.name} and received {response.status_code}: {response.content}")
