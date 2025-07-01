from typing import TYPE_CHECKING

from sqlmodel import SQLModel, Field, Relationship

from Api.models.Macro import Macro
from Api.models.DeviceType import DeviceType
from Api.models.Macro import DeviceMacroLink
from Api.models.Scene import SceneDeviceLink, Scene
from Api.models.UserImage import UserImage

if TYPE_CHECKING:
    from Api.models.Command import Command

class DeviceBase(SQLModel):
    name: str = Field(index=True)
    manufacturer: str | None = Field(default=None)
    model: str | None = Field(default=None)
    type: DeviceType = Field(default=DeviceType.OTHER)
    bluetooth_address: str | None = Field(default=None)

class DevicePost(DeviceBase):
    image_id: int | None = Field(default=None)

class Device(DeviceBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    commands: list["Command"] = Relationship(back_populates="device", cascade_delete=True)
    scenes: list["Scene"] = Relationship(back_populates="devices", link_model=SceneDeviceLink)
    image_id: int | None = Field(default=None, foreign_key="userimage.id", ondelete="SET NULL")
    image: "UserImage" = Relationship(back_populates="devices")
    macros: list[Macro] = Relationship(back_populates="devices", link_model=DeviceMacroLink)

class DeviceWithRelationships(DeviceBase):
    id: int | None
    commands: list["Command"]
    scenes: list[Scene] = []
    image: UserImage | None = None
    macros: list[Macro] = []