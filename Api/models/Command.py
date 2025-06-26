from typing import List, TYPE_CHECKING

from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field, Relationship

from Api.models import Device
from Api.models.CommandGroupType import CommandGroupType
from Api.models.CommandType import CommandType
from Api.models.Macro import CommandMacroLink
from Api.models.NetworkRequestType import NetworkRequestType
from Api.models.RemoteButton import RemoteButton

if TYPE_CHECKING:
    from Api.models.Macro import Macro

class CommandBase(SQLModel):
    name: str
    button: RemoteButton
    type: CommandType
    command_group: CommandGroupType
    device_id: int | None = Field(default=None)
    host: str | None = Field(default=None)
    method: NetworkRequestType | None = Field(default=None)
    body: str | None = Field(default=None)
    bt_action: str | None = Field(default=None)
    bt_media_action: str | None = Field(default=None)

class Command(CommandBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    device_id: int | None = Field(default=None, foreign_key="device.id")
    device: "Device" = Relationship(back_populates="commands")
    ir_action: List[int] = Field(default=[], sa_column=Column(JSON))
    bt_action: str | None = Field(default=None)
    bt_media_action: str | None = Field(default=None)
    host: str | None = Field(default=None)
    method: NetworkRequestType | None = Field(default=None)
    body: str | None = Field(default=None)
    macros: list["Macro"] = Relationship(back_populates="commands", link_model=CommandMacroLink)

    # Needed for Column(JSON)
    class Config:
        arbitrary_types_allowed = True