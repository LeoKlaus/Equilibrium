from sqlmodel import SQLModel


class ServerInfo(SQLModel):
    version: str = "0.1.0"