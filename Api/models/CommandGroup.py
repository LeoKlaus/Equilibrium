from typing import TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship

from Api.models.CommandGroupType import CommandGroupType
from Api.models.Device import Device

if TYPE_CHECKING:
    from Api.models.Command import Command, CommandPublic

class CommandGroupBase(SQLModel):
    name: str
    type: CommandGroupType

class CommandGroup(CommandGroupBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    device_id: int | None = Field(default=None, foreign_key="device.id")
    device: Device = Relationship(back_populates="command_groups")
    commands: list["Command"] = Relationship(back_populates="command_group")

class CommandGroupWithCommands(CommandGroupBase):
    id: int | None
    commands: list["CommandPublic"] = []