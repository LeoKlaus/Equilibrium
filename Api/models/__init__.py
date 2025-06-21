# Warning: Don't touch these, it will cause pydantic to break!
# I don't know exactly why, but this seems to be the exact minimum
# of imports and rebuilds needed for the API to function. Removing any
# of these will cause very weird and hard to diagnose errors to pop up

from .Command import Command, CommandPublic
from .CommandGroup import CommandGroupWithCommands
from .Device import Device, DeviceWithCommandGroup
from .Scene import SceneUpdate, SceneWithRelationships

Command.model_rebuild()
DeviceWithCommandGroup.model_rebuild()
SceneUpdate.model_rebuild()
SceneWithRelationships.model_rebuild()