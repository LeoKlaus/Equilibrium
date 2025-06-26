# Warning: Don't touch these, it will cause pydantic to break!
# I don't know exactly why, but this seems to be the exact minimum
# of imports and rebuilds needed for the API to function. Removing any
# of these will cause very weird and hard to diagnose errors to pop up

from .Command import Command
from .Device import Device, DeviceWithRelationships
from .Macro import Macro, MacroWithRelationships
from .Scene import SceneUpdate, SceneWithRelationships, ScenePost, Scene

Command.model_rebuild()
DeviceWithRelationships.model_rebuild()
SceneUpdate.model_rebuild()
SceneWithRelationships.model_rebuild()
MacroWithRelationships.model_rebuild()
ScenePost.model_rebuild()
Scene.model_rebuild()