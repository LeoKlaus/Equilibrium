import asyncio

from Hub.EventBus import Event
from Hub.Hub import Hub


class FakeInputSource:
    def __init__(self, name: str = "fake"):
        self.name = name
        self.started = False
        self.stopped = False
        self._stop_event = asyncio.Event()

    async def start(self, bus) -> None:
        self.started = True
        await self._stop_event.wait()

    def stop(self) -> None:
        self.stopped = True
        self._stop_event.set()


class FakeInputSourceWithoutStop:
    """No stop() - only asyncio cancellation can end its task."""

    def __init__(self, name: str = "fake-no-stop"):
        self.name = name
        self.started = False

    async def start(self, bus) -> None:
        self.started = True
        await asyncio.Event().wait()


class FakeExecutor:
    def __init__(self, name: str):
        self.name = name
        self.calls = []

    async def execute(self, directive, command) -> None:
        self.calls.append((directive, command))


def test_register_executor_is_keyed_by_name():
    hub = Hub()
    executor = FakeExecutor("ir")

    hub.register_executor(executor)

    assert hub.executors == {"ir": executor}


def test_register_source_appends():
    hub = Hub()
    source_a = FakeInputSource("a")
    source_b = FakeInputSource("b")

    hub.register_source(source_a)
    hub.register_source(source_b)

    assert hub.sources == [source_a, source_b]


async def test_start_runs_the_bus_and_every_registered_source():
    hub = Hub()
    source_a = FakeInputSource("a")
    source_b = FakeInputSource("b")
    hub.register_source(source_a)
    hub.register_source(source_b)

    await hub.start()
    await asyncio.sleep(0)

    assert source_a.started is True
    assert source_b.started is True

    received = []

    async def handler(event: Event) -> None:
        received.append(event)

    hub.bus.subscribe("key_pressed", handler)
    await hub.bus.publish(Event("key_pressed", {}))
    await asyncio.sleep(0.01)
    assert len(received) == 1

    await hub.shutdown()


async def test_shutdown_calls_stop_on_sources_that_have_it():
    hub = Hub()
    source = FakeInputSource()
    hub.register_source(source)
    await hub.start()
    await asyncio.sleep(0)

    await hub.shutdown()

    assert source.stopped is True


async def test_shutdown_ends_sources_without_a_stop_method():
    hub = Hub()
    source = FakeInputSourceWithoutStop()
    hub.register_source(source)
    await hub.start()
    await asyncio.sleep(0)
    assert source.started is True

    await asyncio.wait_for(hub.shutdown(), timeout=1)


async def test_shutdown_leaves_no_tasks_running():
    hub = Hub()
    hub.register_source(FakeInputSource("a"))
    hub.register_source(FakeInputSourceWithoutStop("b"))
    await hub.start()
    await asyncio.sleep(0)

    await hub.shutdown()

    assert all(task.done() for task in hub._source_tasks)
    assert hub._bus_task.done()


async def test_shutdown_without_start_does_not_raise():
    hub = Hub()
    hub.register_source(FakeInputSource())

    await hub.shutdown()
