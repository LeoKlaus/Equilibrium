from sqlmodel import SQLModel, Field


class UserImage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    filename: str = Field(index=True)
    path: str