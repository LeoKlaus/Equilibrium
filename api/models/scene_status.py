from enum import StrEnum


class SceneStatus(StrEnum):
    STARTING = "starting"
    ACTIVE = "active"
    STOPPING = "stopping"