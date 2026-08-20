from collections.abc import Awaitable, Callable

from api.models.scene import SceneWithRelationships
from api.models.scene_status import SceneStatus
from api.models.status import StatusReport

StatusCallback = Callable[[StatusReport], Awaitable[None]]


class StatusStore:
    """Owns the live StatusReport and notifies a subscriber on every change.

    Mutators broadcast as part of the write itself, so callers can't forget
    to notify after changing state.
    """

    def __init__(self) -> None:
        self._status = StatusReport()
        self._callback: StatusCallback | None = None

    @property
    def status(self) -> StatusReport:
        return self._status

    def set_callback(self, callback: StatusCallback | None) -> None:
        """Register the subscriber notified on every state change."""
        self._callback = callback

    async def set_device_state(
        self,
        device_id: int,
        new_power_state: bool | None = None,
        new_input: int | None = None,
        toggle_power: bool | None = None,
    ) -> None:
        self._status.devices.set_state(
            device_id,
            new_power_state=new_power_state,
            new_input=new_input,
            toggle_power=toggle_power,
        )
        await self._notify()

    async def set_scene(
        self,
        scene: SceneWithRelationships | None,
        status: SceneStatus | None,
    ) -> None:
        """Replace the active scene and its status in a single update."""
        self._status.current_scene = scene
        self._status.scene_status = status
        await self._notify()

    async def set_scene_status(self, status: SceneStatus | None) -> None:
        self._status.scene_status = status
        await self._notify()

    async def _notify(self) -> None:
        if self._callback is not None:
            await self._callback(self._status)
