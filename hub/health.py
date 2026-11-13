import asyncio
from collections.abc import Awaitable, Callable

from api.models.health import ComponentHealth, ComponentStatus, HealthStatus

HealthCheck = Callable[[], Awaitable[ComponentHealth]]

CHECK_TIMEOUT_SECONDS = 2.0


async def run_check(name: str, check: HealthCheck, timeout: float = CHECK_TIMEOUT_SECONDS) -> ComponentHealth:
    """Runs a check, turning a timeout or any exception into a `down` result."""
    try:
        return await asyncio.wait_for(check(), timeout=timeout)
    except TimeoutError:
        return ComponentHealth(name=name, status=ComponentStatus.DOWN, detail=f"Health check timed out after {timeout:g}s")
    except Exception as error:
        return ComponentHealth(
            name=name, status=ComponentStatus.DOWN, detail=f"Health check failed: {type(error).__name__}: {error}"
        )


def aggregate(components: list[ComponentHealth], critical: frozenset[str] = frozenset()) -> HealthStatus:
    """`down` only if a critical component is down; otherwise `degraded` if
    anything is degraded or down; otherwise `ok`."""
    if any(c.name in critical and c.status == ComponentStatus.DOWN for c in components):
        return HealthStatus.DOWN
    if any(c.status in (ComponentStatus.DEGRADED, ComponentStatus.DOWN) for c in components):
        return HealthStatus.DEGRADED
    return HealthStatus.OK
