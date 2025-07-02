from typing import TYPE_CHECKING, Optional

from sqlmodel import SQLModel, Field, Relationship

from Api.models.UserImage import UserImage

from Api.models.Macro import Macro, SceneMacroLink, MacroWithCommands

if TYPE_CHECKING:
    from Api.models import DeviceWithRelationships
    from Api.models.Device import Device

class SceneDeviceLink(SQLModel, table=True):
    scene_id: int | None = Field(default=None, foreign_key="device.id", primary_key=True)
    device_id: int | None = Field(default=None, foreign_key="scene.id", primary_key=True)

class SceneBase(SQLModel):
    name: str | None = Field(index=True)

class ScenePost(SceneBase):
    image_id: int | None = Field(default=None)
    start_macro_id: int | None = Field(default=None)
    stop_macro_id: int | None = Field(default=None)
    bluetooth_address: str | None = Field(default=None)
    device_ids: list[int] = Field(default=[])
    macro_ids: list[int] = Field(default=[])
    keymap: str | None = Field(default=None)


class Scene(SceneBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    devices: list["Device"] = Relationship(back_populates="scenes", link_model=SceneDeviceLink)
    image_id: int | None = Field(default=None, foreign_key="userimage.id", ondelete="SET NULL")
    image: "UserImage" = Relationship(back_populates="scenes")
    start_macro_id: int | None = Field(default=None, foreign_key="macro.id")
    start_macro: Optional[Macro] = Relationship(
        back_populates="scenes_start",
        sa_relationship_kwargs={"foreign_keys": "Scene.start_macro_id"}
    )
    stop_macro_id: int | None = Field(default=None, foreign_key="macro.id")
    stop_macro: Optional[Macro] = Relationship(
        back_populates="scenes_stop",
        sa_relationship_kwargs={"foreign_keys": "Scene.stop_macro_id"}
    )
    macros: list[Macro] = Relationship(back_populates="scenes", link_model=SceneMacroLink)
    bluetooth_address: str | None = Field(default=None)
    keymap: str | None = Field(default=None)


class SceneWithRelationships(SceneBase):
    id: int | None
    devices: list["Device"] = []
    image: UserImage | None = None
    start_macro: Optional[MacroWithCommands] = None
    stop_macro: Optional[MacroWithCommands] = None
    macros: list[MacroWithCommands] = []
    bluetooth_address: str | None = None
    keymap: str | None = None

class SceneWithRelationshipsAndFullDevices(SceneBase):
    id: int | None
    devices: list["DeviceWithRelationships"] = []
    image: UserImage | None = None
    start_macro: Optional[MacroWithCommands] = None
    stop_macro: Optional[MacroWithCommands] = None
    macros: list[MacroWithCommands] = []
    bluetooth_address: str | None = None
    keymap: str | None = None