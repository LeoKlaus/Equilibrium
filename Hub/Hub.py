import asyncio
import logging

from Hub.EventBus import EventBus
from Hub.interfaces import ActionExecutor, InputSource


class Hub:
    """Composition root. Owns the EventBus and the registries of
    InputSources/ActionExecutors, and their start/stop lifecycle.

    Registration is explicit (register_source/register_executor) - Hub
    only ever depends on the InputSource/ActionExecutor interfaces, never
    on concrete hardware modules.
    """

    logger = logging.getLogger(__package__)

    def __init__(self) -> None:
        self.bus = EventBus()
        self._sources: list[InputSource] = []
        self._executors: dict[str, ActionExecutor] = {}
        self._source_tasks: list[asyncio.Task] = []
        self._bus_task: asyncio.Task | None = None

    @property
    def sources(self) -> list[InputSource]:
        return self._sources

    @property
    def executors(self) -> dict[str, ActionExecutor]:
        return self._executors

    def register_source(self, source: InputSource) -> None:
        self._sources.append(source)

    def register_executor(self, executor: ActionExecutor) -> None:
        self._executors[executor.name] = executor

    async def start(self) -> None:
        self._bus_task = asyncio.create_task(self.bus.run())
        self._source_tasks = [asyncio.create_task(source.start(self.bus)) for source in self._sources]

    async def shutdown(self) -> None:
        for source in self._sources:
            stop = getattr(source, "stop", None)
            if stop is not None:
                stop()

        tasks = [*self._source_tasks]
        if self._bus_task is not None:
            tasks.append(self._bus_task)

        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
