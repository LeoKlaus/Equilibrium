from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

from api.models.device_type import DeviceType
from api.models.macro import DeviceMacroLink, Macro
from api.models.scene import Scene, SceneDeviceLink
from api.models.user_image import UserImage

if TYPE_CHECKING:
    from api.models.command import Command

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
    commands: list["Command"] = []
    scenes: list[Scene] = []
    image: UserImage | None = None
    macros: list[Macro] = []