from typing import List, TYPE_CHECKING

from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field, Relationship

from Api.models.CommandGroup import CommandGroup
from Api.models.CommandType import CommandType
from Api.models.NetworkRequestType import NetworkRequestType
from Api.models.RemoteButton import RemoteButton
from Api.models.Scene import SceneStartCommandLink, SceneStopCommandLink, Scene

if TYPE_CHECKING:
    from Api.models.Scene import Scene

class CommandBase(SQLModel):
    name: str
    button: RemoteButton
    type: CommandType
    command_group_id: int | None = Field(default=None)
    host: str | None = Field(default=None)
    method: NetworkRequestType | None = Field(default=None)
    body: str | None = Field(default=None)
    bt_action: str | None = Field(default=None)
    bt_media_action: str | None = Field(default=None)

class Command(CommandBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    command_group_id: int | None = Field(default=None, foreign_key="commandgroup.id")
    command_group: CommandGroup = Relationship(back_populates="commands")
    ir_action: List[int] = Field(default=[], sa_column=Column(JSON))
    bt_action: str | None = Field(default=None)
    bt_media_action: str | None = Field(default=None)
    host: str | None = Field(default=None)
    method: NetworkRequestType | None = Field(default=None)
    body: str | None = Field(default=None)
    scenes_start: List["Scene"] = Relationship(back_populates="start_commands", link_model=SceneStartCommandLink)
    scenes_stop: List["Scene"] = Relationship(back_populates="stop_commands", link_model=SceneStopCommandLink)

    # Needed for Column(JSON)
    class Config:
        arbitrary_types_allowed = True

class CommandPublic(CommandBase):
    id: int | None