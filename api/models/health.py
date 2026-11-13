from enum import StrEnum

from sqlmodel import SQLModel


class ComponentStatus(StrEnum):
    OK = "ok"
    # Running, but impaired (e.g. no keymap loaded, last operation failed).
    DEGRADED = "degraded"
    # Can't do its job at all.
    DOWN = "down"
    # Deliberately not set up (e.g. no RF remote paired)
    NOT_CONFIGURED = "not_configured"


class HealthStatus(StrEnum):
    """Overall status. Separate from ComponentStatus so clients don't have
    to handle a "not_configured" the overall status can never be."""

    OK = "ok"
    DEGRADED = "degraded"
    # Only when a critical component (the database) is down
    DOWN = "down"


class ComponentHealth(SQLModel):
    name: str
    status: ComponentStatus
    detail: str | None = None


class HealthReport(SQLModel):
    status: HealthStatus
    uptime_seconds: int
    components: list[ComponentHealth]
