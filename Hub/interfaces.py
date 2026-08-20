from abc import ABC, abstractmethod
from typing import ClassVar

from fastapi import APIRouter

from Api.models.Command import Command
from Hub.EventBus import Directive, EventBus


class InputSource(ABC):
    """A plugin that observes something and publishes events onto the bus.

    Kept to a single method on purpose: any extra surface a module needs
    (pairing, recording, configuration) belongs on its own `router`, not on
    this interface - see architecture.md.
    """

    name: str
    router: APIRouter | None = None
    capabilities: ClassVar[list[str]] = []

    @abstractmethod
    async def start(self, bus: EventBus) -> None:
        """Run forever as its own task, publishing events onto `bus`."""


class ActionExecutor(ABC):
    """A plugin that performs an action for a resolved Directive."""

    name: str
    router: APIRouter | None = None
    capabilities: ClassVar[list[str]] = []

    @abstractmethod
    async def execute(self, directive: Directive, command: Command) -> None:
        ...
