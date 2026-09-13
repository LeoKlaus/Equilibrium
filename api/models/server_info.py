import os
import subprocess

from sqlmodel import Field, SQLModel


def _resolve_version() -> str:
    """The version /info reports, in order of preference:

    1. APP_VERSION env var
    2. `git describe` for bare-metal
    3. "dev" otherwise

    Evaluated fresh per call (via Field's default_factory below) rather
    than once at import time, so tests can exercise all three paths."""
    version = os.environ.get("APP_VERSION", "").strip()
    if version:
        return version
    try:
        return subprocess.check_output(
            ["git", "describe", "--tags", "--always", "--dirty"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except (subprocess.CalledProcessError, OSError):
        return "dev"


class ServerInfo(SQLModel):
    version: str = Field(default_factory=_resolve_version)
