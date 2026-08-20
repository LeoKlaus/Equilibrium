from abc import ABC, abstractmethod
from typing import ClassVar, Protocol, runtime_checkable

from fastapi import APIRouter

from Api.models.Command import Command
from hub.event_bus import Directive, EventBus


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


@runtime_checkable
class BleKeyboardProtocol(Protocol):
    """The subset of BleKeyboard's surface that Hub-internal orchestration
    (SceneManager, InputRouter) depends on. Structural, not the concrete
    class, so those consumers stay decoupled the way Hub itself is
    decoupled from concrete modules - and so tests can keep substituting
    duck-typed fakes for it.
    """

    async def connect(self, address: str) -> None: ...
    async def disconnect(self, address: str | None = None) -> None: ...
    async def register_services(self) -> None: ...
    async def unregister_services(self) -> None: ...
    def release_keys(self) -> None: ...
    def release_media_keys(self) -> None: ...


@runtime_checkable
class IrManagerProtocol(Protocol):
    """The subset of IrManager's surface that InputRouter depends on."""

    def stop_repeating(self) -> None: ...
