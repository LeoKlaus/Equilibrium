from enum import StrEnum

from hub.event_bus import Event


class SceneEvent(StrEnum):
    """Event types published on the bus as a scene moves through its lifecycle."""

    STARTING = "scene.starting"
    STARTED = "scene.started"
    STOPPING = "scene.stopping"
    STOPPED = "scene.stopped"


def scene_event(event_type: SceneEvent, scene_id: int | None, scene_name: str | None) -> Event:
    return Event(str(event_type), {"scene_id": scene_id, "scene_name": scene_name})
