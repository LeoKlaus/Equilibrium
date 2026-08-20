# Warning: don't touch these, it will break pydantic model resolution.
#
# Command/Device/Macro/Scene reference each other, so each file can only
# import the others under TYPE_CHECKING plus a string annotation (e.g.
# Command.device: Optional["Device"]) to avoid a real circular-import
# error. At runtime those names are never bound in the defining file's
# own namespace, so pydantic can't resolve the forward ref there.
#
# model_rebuild() resolves forward refs using the defining module's
# globals *and* the calling frame's namespace (pydantic's
# _parent_namespace_depth, 2 frames up by default). This file is the one
# place all four models get imported for real into one shared namespace,
# so calling .model_rebuild() from here - not from inside the model's
# own file - is what lets each "WithRelationships" class's cross-model
# fields actually resolve. Dropping one of the four imports above, or
# moving a rebuild call elsewhere, breaks resolution for whatever wasn't
# bound at the call site, surfacing only as "X is not fully defined."
#
# table=True models (Command, Scene) don't strictly need this - their
# Relationship() fields resolve via SQLAlchemy's own separate string-
# based class registry, not pydantic's forward-ref system. Their
# rebuild() calls below are harmless no-ops, kept for consistency.

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