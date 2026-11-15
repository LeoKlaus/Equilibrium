import asyncio
import logging

import httpx2
from sqlmodel import Session, select

from api.models.webhook import Webhook, WebhookRead
from api.models.webhook_body_format import WebhookBodyFormat
from db_manager.db_manager import engine
from hub.event_bus import Event, EventBus
from hub.scene_events import SceneEvent
from webhooks.template import build_values, render, render_header


class _HideRequestUrls(logging.Filter):
    """httpx2 logs every request it makes at INFO, url included - for a
    webhook that can be a secret in the path or query, and the log is shown
    over /ws/logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.getMessage().startswith("HTTP Request:")


class WebhookDispatcher:
    """Sends the webhooks that match a scene event, fire and forget: the
    event that triggered them never waits for the receiver, a failed
    delivery is logged and not retried.

    A receiver that doesn't answer holds a task and a connection until the
    timeout, so only MAX_IN_FLIGHT deliveries run at once.
    """

    name = "webhooks"

    logger = logging.getLogger(__package__)

    MAX_IN_FLIGHT = 10
    TIMEOUT = 10.0

    def __init__(self, instance_name: str, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        # transport is a testing hook - None means httpx2's real network transport.
        self._instance_name = instance_name
        self._transport = transport
        self._client: httpx2.AsyncClient | None = None
        self._tasks: set[asyncio.Task[None]] = set()

        httpx_logger = logging.getLogger("httpx2")
        if not any(isinstance(log_filter, _HideRequestUrls) for log_filter in httpx_logger.filters):
            httpx_logger.addFilter(_HideRequestUrls())

    def subscribe(self, bus: EventBus) -> None:
        for event_type in SceneEvent:
            bus.subscribe(str(event_type), self._on_event)

    async def stop(self) -> None:
        """Gives up on deliveries still waiting for an answer."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _on_event(self, event: Event) -> None:
        for webhook in self._matching(event):
            if len(self._tasks) >= self.MAX_IN_FLIGHT:
                self.logger.warning(
                    f"Not sending webhook {webhook.name} for {event.type}: "
                    f"{self.MAX_IN_FLIGHT} deliveries are still waiting for an answer"
                )
                continue
            task = asyncio.create_task(self._deliver(webhook, event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    @staticmethod
    def _matching(event: Event) -> list[WebhookRead]:
        scene_id = event.payload.get("scene_id")
        with Session(engine) as session:
            webhooks = session.exec(select(Webhook).where(Webhook.enabled == True)).all()  # noqa: E712 - SQL, not Python
            return [
                WebhookRead.model_validate(webhook, from_attributes=True)
                for webhook in webhooks
                if (not webhook.events or event.type in webhook.events)
                and (not webhook.scene_ids or scene_id in webhook.scene_ids)
            ]

    def _get_client(self) -> httpx2.AsyncClient:
        if self._client is None:
            self._client = httpx2.AsyncClient(timeout=self.TIMEOUT, transport=self._transport)
        return self._client

    async def _deliver(self, webhook: WebhookRead, event: Event) -> None:
        try:
            values = build_values(event, self._instance_name)
            headers = {name: render_header(value, values) for name, value in (webhook.headers or {}).items()}

            content = None
            if webhook.body_template:
                content = render(webhook.body_template, values, webhook.body_format).encode()
                if not any(name.lower() == "content-type" for name in headers):
                    headers["Content-Type"] = (
                        "application/json" if webhook.body_format is WebhookBodyFormat.JSON
                        else "text/plain; charset=utf-8"
                    )

            response = await self._get_client().request(
                webhook.method.value.upper(), webhook.url, headers=headers, content=content
            )
        except httpx2.TimeoutException:
            self.logger.warning(f"Webhook {webhook.name} timed out after {self.TIMEOUT:g}s")
        except httpx2.HTTPError as error:
            self.logger.warning(f"Webhook {webhook.name} couldn't be sent: {type(error).__name__}")
        except Exception:
            self.logger.exception(f"Webhook {webhook.name} couldn't be sent")
        else:
            if response.is_success:
                self.logger.debug(f"Sent webhook {webhook.name} for {event.type}: {response.status_code}")
            else:
                self.logger.warning(f"Webhook {webhook.name} was answered with {response.status_code}")
