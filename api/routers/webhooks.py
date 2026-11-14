import json
import re
from collections.abc import Sequence
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from sqlmodel import Session, select

from api.models.scene import Scene
from api.models.webhook import Webhook, WebhookBase, WebhookRead, WebhookUpdate
from api.models.webhook_body_format import WebhookBodyFormat
from db_manager.db_manager import SessionDep
from hub.event_bus import Event
from hub.scene_events import SceneEvent
from webhooks.template import PLACEHOLDERS, build_values, render, template_problems

router = APIRouter(
    prefix="/webhooks",
    tags=["Webhooks"],
    responses={404: {"description": "Not found"}}
)

_NULLABLE_FIELDS = {"headers", "body_template"}

_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")

_SAMPLE_VALUES = build_values(Event(SceneEvent.STARTED, {"scene_id": 1, "scene_name": "Example scene"}), "Example hub")


def _problems(webhook: WebhookBase, session: Session) -> list[str]:
    problems = []

    if not webhook.name.strip():
        problems.append("The name can't be empty")

    url = urlparse(webhook.url)
    if url.scheme not in ("http", "https") or not url.hostname:
        problems.append("The url must be an http or https url with a host")

    for name, value in (webhook.headers or {}).items():
        if not _HEADER_NAME.match(name):
            problems.append(f"{name!r} isn't a valid header name")
        problems += [f"Header {name}: {problem}" for problem in template_problems(value)]

    if webhook.body_template:
        body_problems = template_problems(webhook.body_template)
        problems += [f"Body: {problem}" for problem in body_problems]

        if not webhook.method.has_body:
            problems.append(f"A {webhook.method.value} request can't have a body")
        elif not body_problems and webhook.body_format is WebhookBodyFormat.JSON:
            try:
                json.loads(render(webhook.body_template, _SAMPLE_VALUES, webhook.body_format))
            except ValueError as error:
                problems.append(f"The body isn't valid JSON once the placeholders are filled in: {error}")

    for scene_id in webhook.scene_ids:
        if session.get(Scene, scene_id) is None:
            problems.append(f"There is no scene with id {scene_id}")

    return problems


def _validated(webhook: WebhookBase, session: Session) -> WebhookBase:
    """The webhook with duplicate events and scenes removed. Raises a 400
    describing everything that's wrong with it otherwise."""
    problems = _problems(webhook, session)
    if problems:
        raise HTTPException(status_code=400, detail="; ".join(problems))
    return webhook.model_copy(update={
        "events": list(dict.fromkeys(webhook.events)),
        "scene_ids": list(dict.fromkeys(webhook.scene_ids)),
    })


@router.get("/placeholders")
def list_placeholders() -> list[dict[str, str]]:
    """What a body or a header value can contain as {{ NAME }}."""
    return [{"name": name, "description": description} for name, description in PLACEHOLDERS.items()]


@router.get("/events")
def list_events() -> list[SceneEvent]:
    """The events a webhook can be sent for."""
    return list(SceneEvent)


@router.post("/", response_model=WebhookRead)
def create_webhook(webhook: WebhookBase, session: SessionDep) -> Webhook:
    db_webhook = Webhook.model_validate(_validated(webhook, session))
    session.add(db_webhook)
    session.commit()
    session.refresh(db_webhook)
    return db_webhook


@router.get("/", response_model=list[WebhookRead])
def list_webhooks(session: SessionDep) -> Sequence[Webhook]:
    return session.exec(select(Webhook)).all()


@router.get("/{webhook_id}", response_model=WebhookRead)
def show_webhook(webhook_id: int, session: SessionDep) -> Webhook:
    webhook = session.get(Webhook, webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return webhook


@router.patch("/{webhook_id}", response_model=WebhookRead)
def update_webhook(webhook_id: int, update: WebhookUpdate, session: SessionDep) -> Webhook:
    db_webhook = session.get(Webhook, webhook_id)
    if not db_webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    changes = update.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is None and field not in _NULLABLE_FIELDS:
            raise HTTPException(status_code=400, detail=f"{field} can't be null")

    current = WebhookBase.model_validate(db_webhook, from_attributes=True)
    merged = _validated(current.model_copy(update=changes), session)

    for field in WebhookBase.model_fields:
        setattr(db_webhook, field, getattr(merged, field))
    session.add(db_webhook)
    session.commit()
    session.refresh(db_webhook)
    return db_webhook


@router.delete("/{webhook_id}")
def delete_webhook(webhook_id: int, session: SessionDep):
    webhook = session.get(Webhook, webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    session.delete(webhook)
    session.commit()
    return {"ok": True}
