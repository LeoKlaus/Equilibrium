from abc import ABC, abstractmethod
from typing import ClassVar, Protocol, runtime_checkable

from fastapi import APIRouter

from api.models.command import Command
from api.models.health import ComponentHealth
from api.models.websocket_responses import BleDevice
from ble_keyboard.bluetooth_state import BluetoothState
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
class HealthReporting(Protocol):
    """Optional: a module that can say whether it's actually working.

    Deliberately not part of InputSource/ActionExecutor (which stay minimal
    - see architecture.md); Hub checks for it structurally, the same way
    shutdown() checks for an optional stop().

    Implementations should report cached state or the outcome of their last
    real operation rather than probing hardware or the network on every
    call, so health polling can't disturb normal operation.
    """

    async def health(self) -> ComponentHealth: ...


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
class BluetoothStatusSource(Protocol):
    """What the status needs from the bluetooth module to follow a scene's
    bluetooth device: its state, and how to describe a device by address."""

    state: BluetoothState

    def bluetooth_device(self, address: str) -> BleDevice: ...


@runtime_checkable
class IrManagerProtocol(Protocol):
    """The subset of IrManager's surface that InputRouter depends on."""

    def stop_repeating(self) -> None: ...
