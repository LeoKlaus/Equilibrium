import asyncio
import json
import logging
from typing import Any

import httpx2
import pytest
from sqlmodel import Session

from api.models.network_request_type import NetworkRequestType
from api.models.scene import Scene
from api.models.webhook import Webhook
from api.models.webhook_body_format import WebhookBodyFormat
from hub.event_bus import Event, EventBus
from webhooks.dispatcher import WebhookDispatcher


class Receiver:
    """Stands in for the network: records requests, answers with `status`."""

    def __init__(self, status: int = 200):
        self.requests: list[httpx2.Request] = []
        self.status = status

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(self.status)


@pytest.fixture
def db(db_engine, monkeypatch):
    monkeypatch.setattr("webhooks.dispatcher.engine", db_engine)
    return db_engine


def _add(db_engine, **overrides) -> int:
    fields: dict[str, Any] = {"name": "Hook", "url": "http://hook.local/a", "method": NetworkRequestType.POST}
    fields.update(overrides)
    with Session(db_engine) as session:
        webhook = Webhook(**fields)
        session.add(webhook)
        session.commit()
        session.refresh(webhook)
        assert webhook.id is not None
        return webhook.id


def _event(event_type="scene.started", scene_id=3, scene_name="Movie Night") -> Event:
    return Event(event_type, {"scene_id": scene_id, "scene_name": scene_name})


def _dispatcher(handler, **kwargs) -> WebhookDispatcher:
    return WebhookDispatcher("Living Room", transport=httpx2.MockTransport(handler), **kwargs)


async def _send(dispatcher: WebhookDispatcher, event: Event) -> None:
    await dispatcher._on_event(event)
    await asyncio.gather(*dispatcher._tasks)


async def test_sends_the_rendered_body_and_headers(db):
    _add(
        db,
        url="https://hook.local/path?x=1",
        headers={"Authorization": "Bearer abc", "X-Scene": "{{ SCENE_NAME }}"},
        body_template='{"scene": {{ SCENE_ID }}, "name": "{{ SCENE_NAME }}", "event": "{{ EVENT }}", '
                      '"hub": "{{ INSTANCE_NAME }}", "status": "{{ SCENE_STATUS }}"}',
    )
    receiver = Receiver()

    await _send(_dispatcher(receiver), _event(scene_name='The "Best"'))

    [request] = receiver.requests
    assert request.method == "POST"
    assert str(request.url) == "https://hook.local/path?x=1"
    assert request.headers["authorization"] == "Bearer abc"
    assert request.headers["x-scene"] == 'The "Best"'
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {
        "scene": 3, "name": 'The "Best"', "event": "scene.started", "hub": "Living Room", "status": "active",
    }


async def test_a_text_body_is_sent_as_it_is(db):
    _add(db, body_format=WebhookBodyFormat.TEXT, body_template='{{ SCENE_NAME }} is "{{ SCENE_STATUS }}"')
    receiver = Receiver()

    await _send(_dispatcher(receiver), _event(scene_name='A\\B'))

    [request] = receiver.requests
    assert request.content == b'A\\B is "active"'
    assert request.headers["content-type"] == "text/plain; charset=utf-8"


async def test_a_content_type_header_set_by_the_user_wins(db):
    _add(db, headers={"content-type": "application/vnd.custom+json"}, body_template="{}")
    receiver = Receiver()

    await _send(_dispatcher(receiver), _event())

    assert receiver.requests[0].headers["content-type"] == "application/vnd.custom+json"


async def test_without_a_body_nothing_is_sent_and_no_content_type_is_added(db):
    _add(db, method=NetworkRequestType.GET)
    receiver = Receiver()

    await _send(_dispatcher(receiver), _event())

    [request] = receiver.requests
    assert request.method == "GET"
    assert request.content == b""
    assert "content-type" not in request.headers


async def test_header_values_cannot_inject_headers(db):
    _add(db, headers={"X-Scene": "{{ SCENE_NAME }}"})
    receiver = Receiver()

    await _send(_dispatcher(receiver), _event(scene_name="a\r\nX-Injected: yes"))

    [request] = receiver.requests
    assert "x-injected" not in request.headers
    assert request.headers["x-scene"] == "a  X-Injected: yes"


async def test_only_webhooks_for_the_event_are_sent(db):
    _add(db, name="All")
    _add(db, name="Started", events=["scene.started"])
    _add(db, name="Stopped", events=["scene.stopped"])
    _add(db, name="Both", events=["scene.stopped", "scene.started"])
    receiver = Receiver()

    await _send(_dispatcher(receiver), _event("scene.started"))

    assert len(receiver.requests) == 3


async def test_only_webhooks_for_the_scene_are_sent(db):
    _add(db, name="Any scene", url="http://any.local")
    _add(db, name="This scene", url="http://this.local", scene_ids=[3, 9])
    _add(db, name="Other scene", url="http://other.local", scene_ids=[4])
    receiver = Receiver()

    await _send(_dispatcher(receiver), _event(scene_id=3))

    assert sorted(request.url.host for request in receiver.requests) == ["any.local", "this.local"]


async def test_disabled_webhooks_are_not_sent(db):
    _add(db, enabled=False)
    receiver = Receiver()

    await _send(_dispatcher(receiver), _event())

    assert receiver.requests == []


async def test_nothing_happens_without_webhooks(db):
    receiver = Receiver()

    await _send(_dispatcher(receiver), _event())

    assert receiver.requests == []


async def test_a_failing_webhook_does_not_stop_the_others(db, caplog):
    _add(db, name="Broken", url="http://broken.local")
    _add(db, name="Fine", url="http://fine.local")
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request.url.host)
        if request.url.host == "broken.local":
            raise httpx2.ConnectError("refused")
        return httpx2.Response(200)

    with caplog.at_level(logging.WARNING):
        await _send(_dispatcher(handler), _event())

    assert sorted(requests) == ["broken.local", "fine.local"]
    assert "Webhook Broken couldn't be sent: ConnectError" in caplog.text


async def test_a_timeout_is_logged_without_a_traceback(db, caplog):
    _add(db, name="Slow")

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("too slow")

    with caplog.at_level(logging.WARNING):
        await _send(_dispatcher(handler), _event())

    assert "Webhook Slow timed out" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_an_error_status_is_logged(db, caplog):
    _add(db, name="Picky")

    with caplog.at_level(logging.WARNING):
        await _send(_dispatcher(Receiver(status=500)), _event())

    assert "Webhook Picky was answered with 500" in caplog.text


async def test_the_url_is_never_logged(db, caplog):
    _add(db, name="Secret", url="http://hook.local/token-abc123?key=hunter2")

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    with caplog.at_level(logging.DEBUG):
        await _send(_dispatcher(handler), _event())
        await _send(_dispatcher(Receiver(status=404)), _event())

    assert "abc123" not in caplog.text
    assert "hunter2" not in caplog.text


async def test_a_template_that_cannot_be_sent_is_logged_and_does_not_raise(db, caplog):
    # Header values httpx2 won't accept, e.g. from a scene name with a character that can't be encoded
    _add(db, name="Odd", headers={"X-Scene": "{{ SCENE_NAME }}"})
    receiver = Receiver()

    with caplog.at_level(logging.WARNING):
        await _send(_dispatcher(receiver), _event(scene_name="\ud800"))

    assert "Webhook Odd couldn't be sent" in caplog.text


async def test_deliveries_beyond_the_limit_are_dropped(db, caplog):
    for index in range(12):
        _add(db, name=f"Hook {index}", url=f"http://hook{index}.local")
    release = asyncio.Event()
    started = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        started.append(request.url.host)
        await release.wait()
        return httpx2.Response(200)

    dispatcher = _dispatcher(handler)
    with caplog.at_level(logging.WARNING):
        await dispatcher._on_event(_event())
        await asyncio.sleep(0.05)

        assert len(dispatcher._tasks) == WebhookDispatcher.MAX_IN_FLIGHT
        assert len(started) == WebhookDispatcher.MAX_IN_FLIGHT
        assert caplog.text.count("Not sending webhook") == 2

        release.set()
        await asyncio.gather(*dispatcher._tasks)

    await dispatcher._on_event(_event())
    await asyncio.gather(*dispatcher._tasks)
    assert len(started) == WebhookDispatcher.MAX_IN_FLIGHT + WebhookDispatcher.MAX_IN_FLIGHT


async def test_the_event_does_not_wait_for_the_receiver(db):
    _add(db)
    release = asyncio.Event()

    async def handler(request: httpx2.Request) -> httpx2.Response:
        await release.wait()
        return httpx2.Response(200)

    dispatcher = _dispatcher(handler)

    await asyncio.wait_for(dispatcher._on_event(_event()), timeout=1)

    assert len(dispatcher._tasks) == 1
    release.set()
    await asyncio.gather(*dispatcher._tasks)


async def test_stop_cancels_pending_deliveries(db):
    _add(db)
    started = asyncio.Event()

    async def handler(request: httpx2.Request) -> httpx2.Response:
        started.set()
        await asyncio.Event().wait()
        return httpx2.Response(200)

    dispatcher = _dispatcher(handler)
    await dispatcher._on_event(_event())
    await started.wait()

    await asyncio.wait_for(dispatcher.stop(), timeout=1)

    assert dispatcher._tasks == set()


async def test_subscribed_to_the_bus_it_sends_for_every_scene_event(db):
    _add(db)
    receiver = Receiver()
    dispatcher = _dispatcher(receiver)
    bus = EventBus()
    dispatcher.subscribe(bus)
    bus_task = asyncio.create_task(bus.run())

    try:
        for event_type in ("scene.starting", "scene.started", "scene.stopping", "scene.stopped"):
            await bus.publish(_event(event_type))
        async with asyncio.timeout(2):
            while len(receiver.requests) < 4:
                await asyncio.sleep(0.01)
    finally:
        bus_task.cancel()

    assert len(receiver.requests) == 4


async def test_events_that_are_not_scene_events_are_ignored(db):
    _add(db)
    receiver = Receiver()
    bus = EventBus()
    _dispatcher(receiver).subscribe(bus)
    bus_task = asyncio.create_task(bus.run())

    try:
        await bus.publish(Event("key_pressed", {"button": "x"}))
        await asyncio.sleep(0.1)
    finally:
        bus_task.cancel()

    assert receiver.requests == []


def test_scene_ids_of_deleted_scenes_simply_never_match(db):
    with Session(db) as session:
        session.add(Scene(name="x"))
        session.commit()
    _add(db, scene_ids=[99])

    assert WebhookDispatcher._matching(_event(scene_id=1)) == []
