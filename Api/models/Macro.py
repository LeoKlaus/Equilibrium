from typing import TYPE_CHECKING

from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from Api.models.Device import Device
    from Api.models.Scene import Scene
    from Api.models.Command import Command

class CommandMacroLink(SQLModel, table=True):
    command_id: int | None = Field(default=None, foreign_key="macro.id", primary_key=True)
    macro_id: int | None = Field(default=None, foreign_key="command.id", primary_key=True)

class SceneMacroLink(SQLModel, table=True):
    scene_id: int | None = Field(default=None, foreign_key="macro.id", primary_key=True)
    macro_id: int | None = Field(default=None, foreign_key="scene.id", primary_key=True)

class DeviceMacroLink(SQLModel, table=True):
    device_id: int | None = Field(default=None, foreign_key="macro.id", primary_key=True)
    macro_id: int | None = Field(default=None, foreign_key="device.id", primary_key=True)

class MacroBase(SQLModel):
    name: str | None = Field(default=None)

class MacroPost(MacroBase):
    command_ids: list[int] = Field(default=[])
    delays: list[int] = Field(default=[])
    scene_ids: list[int] = Field(default=[])

class Macro(MacroBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    commands: list["Command"] = Relationship(back_populates="macros", link_model=CommandMacroLink)
    command_ids: list[int] = Field(default=[], sa_column=Column(JSON))
    delays: list[int] = Field(default=[], sa_column=Column(JSON))
    scenes_start: list["Scene"] = Relationship(
        back_populates="start_macro",
        sa_relationship_kwargs={"foreign_keys": "Scene.start_macro_id"}
    )
    scenes_stop: list["Scene"] = Relationship(
        back_populates="stop_macro",
        sa_relationship_kwargs={"foreign_keys": "Scene.stop_macro_id"}
    )
    scenes: list["Scene"] = Relationship(back_populates="macros", link_model=SceneMacroLink)
    devices: list["Device"] = Relationship(back_populates="macros", link_model=DeviceMacroLink)

    # Needed for Column(JSON)
    class Config:
        arbitrary_types_allowed = True

class MacroWithCommands(MacroBase):
    id: int | None
    commands: list["Command"] = []
    command_ids: list[int] = []
    delays: list[int] = []

class MacroWithRelationships(MacroBase):
    id: int | None
    commands: list["Command"] = []
    command_ids: list[int] = []
    delays: list[int] = []
    scenes: list["Scene"] = []
    devices: list["Device"] = []