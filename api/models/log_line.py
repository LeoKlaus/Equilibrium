from sqlmodel import SQLModel


class LogLine(SQLModel):
    timestamp: str
    level: str
    logger: str
    message: str
    formatted: str


class LogsResponse(SQLModel):
    lines: list[LogLine]
