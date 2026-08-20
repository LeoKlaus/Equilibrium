# Warning: Don't touch these, it will cause pydantic to break!
# I don't know exactly why, but this seems to be the exact minimum
# of imports and rebuilds needed for the API to function. Removing any
# of these will cause very weird and hard to diagnose errors to pop up

from api.models.command import Command, CommandWithRelationships
from api.models.device import Device, DeviceWithRelationships
from api.models.macro import Macro, MacroWithRelationships
from api.models.scene import Scene, ScenePost, SceneWithRelationships, SceneWithRelationshipsAndFullDevices

__all__ = [
    "Command",
    "CommandWithRelationships",
    "Device",
    "DeviceWithRelationships",
    "Macro",
    "MacroWithRelationships",
    "Scene",
    "ScenePost",
    "SceneWithRelationships",
    "SceneWithRelationshipsAndFullDevices",
]

Command.model_rebuild()
CommandWithRelationships.model_rebuild()
DeviceWithRelationships.model_rebuild()
SceneWithRelationships.model_rebuild()
MacroWithRelationships.model_rebuild()
ScenePost.model_rebuild()
Scene.model_rebuild()
SceneWithRelationshipsAndFullDevices.model_rebuild()