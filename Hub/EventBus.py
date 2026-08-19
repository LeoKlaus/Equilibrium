import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, DefaultDict


@dataclass
class Event:
    """Something an InputSource observed, e.g. a remote button was pressed."""
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class Directive:
    """A resolved instruction to run a specific stored Command."""
    command_id: int
    press_without_release: bool = False


EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    """Async pub/sub bus decoupling InputSources from ActionExecutors.

    Each handler is dispatched as its own task, so one slow subscriber
    (e.g. a BLE send waiting on a D-Bus round trip) can never delay another
    subscriber, or the next event being pulled off the queue.
    """

    logger = logging.getLogger(__package__)

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers: DefaultDict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._subscribers[event_type].append(handler)

    async def publish(self, event: Event) -> None:
        await self._queue.put(event)

    async def run(self) -> None:
        """Drain the queue forever. Intended to run as its own task."""
        while True:
            event = await self._queue.get()
            self._dispatch(event)

    def _dispatch(self, event: Event) -> None:
        for handler in self._subscribers.get(event.type, []):
            asyncio.create_task(self._run_handler(handler, event))

    async def _run_handler(self, handler: EventHandler, event: Event) -> None:
        try:
            await handler(event)
        except Exception:
            self.logger.exception(f"Handler for event '{event.type}' raised")
