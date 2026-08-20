from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from api.models.device import Device
    from api.models.scene import Scene

class UserImage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    filename: str = Field(index=True)
    path: str
    devices: list["Device"] = Relationship(back_populates="image")
    scenes: list["Scene"] = Relationship(back_populates="image")