import asyncio
import logging

from ble_keyboard.bluetooth_state import BluetoothState, DeviceChanged, StateChange, normalize_address
from hub.status_store import StatusStore


class BluetoothStatusForwarder:
    """Puts changes of the current scene's bluetooth device into the
    StatusStore, and with it onto the status socket.
    """

    logger = logging.getLogger(__package__)

    def __init__(self, state: BluetoothState, status_store: StatusStore) -> None:
        self._status_store = status_store
        self._tasks: set[asyncio.Task[None]] = set()
        state.add_listener(self._on_change)

    def _on_change(self, change: StateChange) -> None:
        if not isinstance(change, DeviceChanged):
            return

        scene = self._status_store.status.current_scene
        address = scene.bluetooth_address if scene is not None else None
        if not address or normalize_address(address) != change.address:
            return

        task = asyncio.create_task(self._refresh())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _refresh(self) -> None:
        try:
            await self._status_store.refresh_bluetooth_device()
        except Exception:
            self.logger.exception("Couldn't forward a Bluetooth device change to the status")
