import asyncio

from Hub.EventBus import Directive, Event, EventBus


async def test_dispatch_calls_subscribed_handlers():
    bus = EventBus()
    received = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("key_pressed", handler)
    bus._dispatch(Event("key_pressed", {"button": "PLAY"}))
    await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0].payload["button"] == "PLAY"


async def test_dispatch_ignores_unrelated_event_types():
    bus = EventBus()
    received = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("key_pressed", handler)
    bus._dispatch(Event("key_released", {}))
    await asyncio.sleep(0)

    assert received == []


async def test_run_drains_published_events():
    bus = EventBus()
    received = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("key_pressed", handler)
    await bus.publish(Event("key_pressed", {"button": "PLAY"}))
    run_task = asyncio.create_task(bus.run())

    async def wait_for_dispatch():
        while not received:
            await asyncio.sleep(0)

    try:
        await asyncio.wait_for(wait_for_dispatch(), timeout=1)
        assert received[0].payload["button"] == "PLAY"
    finally:
        run_task.cancel()


async def test_slow_handler_does_not_block_a_second_handler():
    bus = EventBus()
    order = []

    async def slow_handler(_: Event) -> None:
        await asyncio.sleep(0.05)
        order.append("slow")

    async def fast_handler(_: Event) -> None:
        order.append("fast")

    bus.subscribe("key_pressed", slow_handler)
    bus.subscribe("key_pressed", fast_handler)
    bus._dispatch(Event("key_pressed", {}))
    await asyncio.sleep(0.1)

    assert order == ["fast", "slow"]


async def test_a_raising_handler_does_not_prevent_a_sibling_handler_from_running(caplog):
    bus = EventBus()
    order = []

    async def raising_handler(_: Event) -> None:
        order.append("raising")
        raise ValueError("boom")

    async def other_handler(_: Event) -> None:
        order.append("other")

    bus.subscribe("key_pressed", raising_handler)
    bus.subscribe("key_pressed", other_handler)
    bus._dispatch(Event("key_pressed", {}))
    await asyncio.sleep(0)

    assert set(order) == {"raising", "other"}
    assert "raised" in caplog.text


def test_directive_defaults():
    directive = Directive(command_id=5)
    assert directive.press_without_release is False
