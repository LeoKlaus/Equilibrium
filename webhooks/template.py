import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime

from api.models.webhook_body_format import WebhookBodyFormat
from hub.event_bus import Event
from hub.scene_events import SceneEvent

# What a template can refer to as {{ NAME }}, and what each one means
PLACEHOLDERS: Mapping[str, str] = {
    "EVENT": "The event type, e.g. scene.started",
    "TIMESTAMP": "When the event happened, ISO 8601 in UTC",
    "INSTANCE_NAME": "The name of this hub",
    "SCENE_ID": "The id of the scene",
    "SCENE_NAME": "The name of the scene",
    "SCENE_STATUS": "starting, active, stopping or stopped",
}

_SCENE_STATUS_BY_EVENT: dict[str, str] = {
    SceneEvent.STARTING: "starting",
    SceneEvent.STARTED: "active",
    SceneEvent.STOPPING: "stopping",
    SceneEvent.STOPPED: "stopped",
}

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def build_values(event: Event, instance_name: str, now: datetime | None = None) -> dict[str, str]:
    """The value of every placeholder for an event."""
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    scene_id = event.payload.get("scene_id")
    scene_name = event.payload.get("scene_name")
    status = _SCENE_STATUS_BY_EVENT.get(event.type)

    return {
        "EVENT": event.type,
        "TIMESTAMP": timestamp,
        "INSTANCE_NAME": instance_name,
        "SCENE_ID": "" if scene_id is None else str(scene_id),
        "SCENE_NAME": scene_name or "",
        "SCENE_STATUS": status or "",
    }


def _escape(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)[1:-1]


def render(template: str, values: Mapping[str, str], body_format: WebhookBodyFormat) -> str:
    """Replaces every {{ NAME }} with its value, escaped for a JSON body and
    kept as it is for a text body."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            return match.group(0)
        if body_format is WebhookBodyFormat.JSON:
            return _escape(values[name])
        return values[name]

    return _PLACEHOLDER.sub(replace, template)


def render_header(template: str, values: Mapping[str, str]) -> str:
    """Like render() for text, but line breaks and other control characters in
    a value become spaces, so it can't end the header and start another."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            return match.group(0)
        return _CONTROL_CHARACTERS.sub(" ", values[name])

    return _PLACEHOLDER.sub(replace, template)


def template_problems(template: str) -> list[str]:
    """What's wrong with a template: placeholders that don't exist, and "{{"
    that doesn't start a placeholder. Empty if it's fine."""
    problems = []

    for name in dict.fromkeys(_PLACEHOLDER.findall(template)):
        if name not in PLACEHOLDERS:
            problems.append(f"Unknown placeholder {name}")

    if "{{" in _PLACEHOLDER.sub("", template):
        problems.append('"{{" doesn\'t start a valid placeholder')

    return problems
