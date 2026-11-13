import asyncio
import os
import shutil
import time
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from api.models.health import ComponentHealth, ComponentStatus, HealthReport
from db_manager.db_manager import engine
from hub.health import aggregate, run_check
from zeroconf_manager.zeroconf_manager import get_lan_ip

if TYPE_CHECKING:
    from hub.hub import Hub
    from zeroconf_manager.zeroconf_manager import ZeroconfManager

_CRITICAL = frozenset({"database"})

_LOW_DISK_BYTES = 100 * 1024 * 1024
_CRITICAL_DISK_BYTES = 10 * 1024 * 1024


def _format_bytes(size: int) -> str:
    if size >= 1024 ** 3:
        return f"{size / 1024 ** 3:.1f} GB"
    return f"{size / 1024 ** 2:.0f} MB"


class HealthChecker:
    """Builds GET /system/health: the hub's modules (via Hub.check_health)
    plus the infrastructure the hub itself depends on - database, storage
    and the mDNS advertisement.
    """

    def __init__(self, hub: "Hub", zeroconf: "ZeroconfManager", started_at: float, config_dir: str = "config") -> None:
        self._hub = hub
        self._zeroconf = zeroconf
        self._started_at = started_at
        self._config_dir = config_dir

    async def report(self) -> HealthReport:
        hub_components, database, storage, zeroconf = await asyncio.gather(
            self._hub.check_health(),
            run_check("database", self._check_database),
            run_check("storage", self._check_storage),
            run_check("zeroconf", self._check_zeroconf),
        )
        components = [database, storage, zeroconf, *hub_components]
        return HealthReport(
            status=aggregate(components, critical=_CRITICAL),
            uptime_seconds=int(time.monotonic() - self._started_at),
            components=components,
        )

    async def _check_database(self) -> ComponentHealth:
        def query() -> None:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1 FROM sqlite_master LIMIT 1"))

        try:
            await asyncio.get_running_loop().run_in_executor(None, query)
        except SQLAlchemyError as error:
            return ComponentHealth(
                name="database",
                status=ComponentStatus.DOWN,
                detail=f"Query failed: {type(error).__name__}: {getattr(error, 'orig', error)}",
            )
        return ComponentHealth(name="database", status=ComponentStatus.OK)

    async def _check_storage(self) -> ComponentHealth:
        def inspect() -> tuple[int, bool]:
            return shutil.disk_usage(self._config_dir).free, os.access(self._config_dir, os.W_OK)

        free, writable = await asyncio.get_running_loop().run_in_executor(None, inspect)

        if not writable:
            return ComponentHealth(
                name="storage",
                status=ComponentStatus.DOWN,
                detail=f"{self._config_dir}/ is not writable (read-only filesystem?)",
            )
        if free < _CRITICAL_DISK_BYTES:
            return ComponentHealth(
                name="storage", status=ComponentStatus.DOWN, detail=f"Only {_format_bytes(free)} free"
            )
        if free < _LOW_DISK_BYTES:
            return ComponentHealth(
                name="storage", status=ComponentStatus.DEGRADED, detail=f"Only {_format_bytes(free)} free"
            )
        return ComponentHealth(name="storage", status=ComponentStatus.OK, detail=f"{_format_bytes(free)} free")

    async def _check_zeroconf(self) -> ComponentHealth:
        zeroconf = self._zeroconf
        if zeroconf.advertised_ip is None:
            return ComponentHealth(name="zeroconf", status=ComponentStatus.DOWN, detail="Service is not registered")

        try:
            current_ip = get_lan_ip()
        except OSError as error:
            return ComponentHealth(name="zeroconf", status=ComponentStatus.DOWN, detail=f"No network route: {error}")

        advertised = f"{zeroconf.advertised_name} at {zeroconf.advertised_ip}:{zeroconf.advertised_port}"

        if current_ip != zeroconf.advertised_ip:
            return ComponentHealth(
                name="zeroconf",
                status=ComponentStatus.DEGRADED,
                detail=f"Advertising {advertised}, but this host is now at {current_ip} - "
                       f"clients may not find the hub until it restarts",
            )
        return ComponentHealth(name="zeroconf", status=ComponentStatus.OK, detail=advertised)
