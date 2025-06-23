from pydantic import BaseModel


class ServerInfo(BaseModel):
    version: str = "0.1.0"