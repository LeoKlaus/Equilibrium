from typing import List, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship

from Api.models.SceneStatus import SceneStatus
from Api.models.UserImage import UserImage

if TYPE_CHECKING:
    from Api.models.Device import Device
    from Api.models.Command import Command

class SceneDeviceLink(SQLModel, table=True):
    scene_id: int | None = Field(default=None, foreign_key="device.id", primary_key=True)
    device_id: int | None = Field(default=None, foreign_key="scene.id", primary_key=True)

class SceneStartCommandLink(SQLModel, table=True):
    scene_id: int | None = Field(default=None, foreign_key="command.id", primary_key=True)
    command_id: int | None = Field(default=None, foreign_key="scene.id", primary_key=True)

class SceneStopCommandLink(SQLModel, table=True):
    scene_id: int | None = Field(default=None, foreign_key="command.id", primary_key=True)
    command_id: int | None = Field(default=None, foreign_key="scene.id", primary_key=True)

class SceneBase(SQLModel):
    name: str | None = Field(index=True)

class ScenePost(SceneBase):
    device_ids: List[int] = Field(default=[])
    image_id: int | None = Field(default=None)
    start_command_ids: List[int] = Field(default=[])
    stop_command_ids: List[int] = Field(default=[])
    bluetooth_address: str | None = Field(default=None)
    keymap: str | None = Field(default=None)

class Scene(SceneBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    devices: list["Device"] = Relationship(back_populates="scenes", link_model=SceneDeviceLink)
    image_id: int | None = Field(default=None, foreign_key="userimage.id", ondelete="SET NULL")
    image: "UserImage" = Relationship(back_populates="scenes")
    start_commands: list["Command"] = Relationship(back_populates="scenes_start", link_model=SceneStartCommandLink)
    stop_commands: list["Command"] = Relationship(back_populates="scenes_stop", link_model=SceneStopCommandLink)
    bluetooth_address: str | None = Field(default=None)
    keymap: str | None = Field(default=None)


class SceneUpdate(SceneBase):
    devices: list["Device"] = Field(default=[])
    image_id: int | None = Field(default=None)
    start_command_ids: List[int] = Field(default=[])
    stop_commands_ids: List[int] = Field(default=[])
    bluetooth_address: str | None = Field(default=None)
    keymap: str | None = Field(default=None)


class SceneWithRelationships(SceneBase):
    id: int | None
    devices: list["Device"] = []
    image: UserImage | None = None
    start_commands: List["Command"] = []
    stop_commands: List["Command"] = []
    bluetooth_address: str | None = None
    keymap: str | None = None

class SceneStatusReport(SQLModel):
    id: int | None
    status: SceneStatus | None