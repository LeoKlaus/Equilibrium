from enum import Enum


class SceneStatus(str, Enum):
    STARTING = "starting"
    ACTIVE = "active"
    STOPPING = "stopping"