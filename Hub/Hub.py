import asyncio
import logging

from BleKeyboard.BleKeyboard import BleKeyboard
from HaManager.HaManager import HaManager
from Hub.CommandDispatcher import CommandDispatcher
from Hub.EventBus import EventBus
from Hub.InputRouter import InputRouter
from Hub.interfaces import ActionExecutor, InputSource
from Hub.KeymapResolver import KeymapResolver
from Hub.SceneManager import SceneManager
from Hub.StatusStore import StatusStore
from IrManager.IrManager import IrManager
from NetworkExecutor.NetworkExecutor import NetworkExecutor
from RfManager.RfManager import RfInput
from ScriptExecutor.ScriptExecutor import ScriptExecutor


class Hub:
    """Composition root. Owns the EventBus and the registries of
    InputSources/ActionExecutors, and their start/stop lifecycle.

    Registration is explicit (register_source/register_executor) - Hub
    only ever depends on the InputSource/ActionExecutor interfaces, never
    on concrete hardware modules.
    """

    logger = logging.getLogger(__package__)

    def __init__(self, config_dir: str = "config") -> None:
        self._config_dir = config_dir

        self.bus = EventBus()
        self._sources: list[InputSource] = []
        self._executors: dict[str, ActionExecutor] = {}
        self._source_tasks: list[asyncio.Task] = []
        self._bus_task: asyncio.Task | None = None
        self._assembled = False

        self.status_store: StatusStore | None = None
        self.keymap_resolver: KeymapResolver | None = None
        self.command_dispatcher: CommandDispatcher | None = None
        self.scene_manager: SceneManager | None = None
        self.input_router: InputRouter | None = None

    @property
    def sources(self) -> list[InputSource]:
        return self._sources

    @property
    def executors(self) -> dict[str, ActionExecutor]:
        return self._executors

    def register_source(self, source: InputSource) -> None:
        self._sources.append(source)

    def register_executor(self, executor: ActionExecutor) -> None:
        self._executors[executor.name] = executor

    def assemble(self) -> None:
        """Build StatusStore/KeymapResolver/CommandDispatcher/SceneManager/
        InputRouter from whatever's been registered so far, and subscribe
        InputRouter to the bus. Idempotent - only the first call does
        anything. Must run after all sources/executors are registered;
        start() calls this itself so callers can't get the order wrong.
        """
        if self._assembled:
            return

        self.status_store = StatusStore()
        self.keymap_resolver = KeymapResolver(config_dir=self._config_dir)
        self.command_dispatcher = CommandDispatcher(self.status_store, self.keymap_resolver, self._executors)

        ble_keyboard = self._executors.get("bluetooth")
        ir_manager = self._executors.get("ir")

        self.scene_manager = SceneManager(
            self.status_store, self.keymap_resolver, self.command_dispatcher, ble_keyboard
        )
        self.input_router = InputRouter(
            self.keymap_resolver, self.scene_manager, self.command_dispatcher, ble_keyboard, ir_manager
        )
        self.input_router.subscribe(self.bus)

        self._assembled = True

    @classmethod
    async def create(
        cls,
        rf_addresses: list[bytes] | None = None,
        ha_url: str | None = None,
        ha_token: str | None = None,
        scripts_dir: str | None = None,
        dev: bool = False,
        config_dir: str = "config",
    ) -> "Hub":
        """Build a Hub with the real hardware/protocol modules registered.

        dev=True skips everything that touches actual hardware (RF, BLE,
        IR)

        scripts_dir is the explicit opt-in for ScriptExecutor: leave it
        None to keep script commands disabled. Since Commands (including
        script_path) are created through the HTTP API, enabling this
        lets anything with API access run arbitrary executables from
        that directory - only set it if you trust every API client.
        """
        hub = cls(config_dir=config_dir)

        if not dev:
            hub.register_source(RfInput(addresses=rf_addresses or [], config_dir=config_dir))
            hub.register_executor(await BleKeyboard.create())
            hub.register_executor(IrManager())

        if ha_url is not None and ha_token is not None:
            hub.register_executor(HaManager(ha_url, ha_token))

        hub.register_executor(NetworkExecutor())

        if scripts_dir is not None:
            hub.logger.warning(
                f"Script execution is ENABLED (scripts_dir={scripts_dir}). Commands with a "
                f"script_path will run executables from that directory - only enable this if "
                f"you trust everything with access to the HTTP API."
            )
            hub.register_executor(ScriptExecutor(scripts_dir=scripts_dir))

        hub.assemble()

        try:
            hub.keymap_resolver.load_key_map()
        except FileNotFoundError:
            hub.logger.warning("Couldn't find \"keymap_default.json\", no keymap will be active.")

        return hub

    async def start(self) -> None:
        self.assemble()
        self._bus_task = asyncio.create_task(self.bus.run())
        self._source_tasks = [asyncio.create_task(source.start(self.bus)) for source in self._sources]

    async def shutdown(self) -> None:
        for source in self._sources:
            stop = getattr(source, "stop", None)
            if stop is not None:
                stop()

        tasks = [*self._source_tasks]
        if self._bus_task is not None:
            tasks.append(self._bus_task)

        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
