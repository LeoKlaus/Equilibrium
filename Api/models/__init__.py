# Warning: Don't touch these, it will cause pydantic to break!
# I don't know exactly why, but this seems to be the exact minimum
# of imports and rebuilds needed for the API to function. Removing any
# of these will cause very weird and hard to diagnose errors to pop up

from .Command import Command, CommandWithRelationships
from .Device import Device, DeviceWithRelationships
from .Macro import Macro, MacroWithRelationships
from .Scene import SceneWithRelationships, ScenePost, Scene, SceneWithRelationshipsAndFullDevices

Command.model_rebuild()
CommandWithRelationships.model_rebuild()
DeviceWithRelationships.model_rebuild()
SceneWithRelationships.model_rebuild()
MacroWithRelationships.model_rebuild()
ScenePost.model_rebuild()
Scene.model_rebuild()
SceneWithRelationshipsAndFullDevices.model_rebuild()