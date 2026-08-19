# Equilibrium Architecture

Target architecture for the rewrite of the input/action/dispatch core and the
API surface around it. This document describes where things are going, not
migration steps.

## Goals

- Modular, plugin-based design: input sources and action executors can be
  added without touching core dispatch code.
- Split the `RemoteController` god-object into components with clear,
  single-purpose ownership of state.
- Let a module (BLE, IR, future modules) expose extra API surface like pairing,
  recording, configuration without hardcoding it into the main app.
- Let client apps discover what capabilities are actually available on a
  given hub without hardcoding routes.

## Core concepts

### `Event`, `Directive`, `EventBus`

```python
@dataclass
class Event:
    type: str                          # e.g. "key_pressed", "key_released"
    payload: dict[str, Any] = field(default_factory=dict)

@dataclass
class Directive:
    command_id: int                    # references Api.models.Command
    press_without_release: bool = False
```

`EventBus` is unchanged from the skeleton: an `asyncio.Queue`-based pub/sub
bus. Producers and consumers never call each other directly. Each handler
runs as its own `asyncio.Task`, so a slow subscriber can't block dispatch of
the next event. This is the mechanism that replaces `AsyncQueueManager`.

### `InputSource` / `ActionExecutor`

Kept minimal on purpose, see "Module-owned API surface" below for why:

```python
class InputSource(ABC):
    name: str
    router: APIRouter | None = None
    capabilities: list[str] = []

    @abstractmethod
    async def start(self, bus: EventBus) -> None: ...

class ActionExecutor(ABC):
    name: str                          # matches CommandType value
    router: APIRouter | None = None
    capabilities: list[str] = []

    @abstractmethod
    async def execute(self, directive: Directive, command: "Api.models.Command") -> None: ...
```

### `Hub`

Composition root. Owns the `EventBus`, the registry of `InputSource`s and
`ActionExecutor`s (keyed by `name`, matching `CommandType`), and wires
everything at startup. Registration stays **explicit**
(`hub.register_source(...)`, `hub.register_executor(...)`). No
`entry_points`-based auto-discovery yet, since there are no third-party
pip-installable plugins. If stronger isolation between modules is ever
needed (conflicting native deps), the fallback is running modules as
separate processes over MQTT not pursued now, adds real operational
complexity for a single-device hobby project.

### Golden rule

Any call into a blocking C-backed library (`pyrf24`, `pigpio`'s socket API,
etc.) **must** go through `loop.run_in_executor(...)`. An `async def`
function that internally calls a blocking function still blocks the whole
event loop.

## `RfManager` → async `InputSource`

`RfManager` currently runs its own `threading.Thread` polling loop and
invokes its callback directly from that thread. It converts to the
skeleton's `NRF24Input` pattern, an `async def start(self, bus)` loop that
calls the blocking `pyrf24` read via `run_in_executor` each iteration and
publishes a `key_pressed`/`key_released` event onto the bus:

```python
class RfInput(InputSource):
    name = "rf"

    async def start(self, bus: EventBus) -> None:
        loop = asyncio.get_running_loop()
        while True:
            packet = await loop.run_in_executor(None, self._blocking_receive)
            if packet is not None:
                await bus.publish(Event("key_pressed", {"button": packet}))
```

## Executors implemented in place

Existing hardware/protocol classes implement `ActionExecutor` directly
(rather than being wrapped by separate adapter classes):

| Class | `name` (= `CommandType`) |
|---|---|
| `BleKeyboard` | `bluetooth` |
| `IrManager` | `ir` |
| `HaManager` | `integration` |
| `NetworkExecutor` *(new)* | `network` |
| `ScriptExecutor` *(new, stub)* | `script` |

`NetworkExecutor` and `ScriptExecutor` are new, small, stateless classes.
There's no existing hardware class for them to attach to. `ScriptExecutor`
carries over today's `NotImplementedError` until scripting is implemented.

## `RemoteController` decomposition

`RemoteController` is retired; its responsibilities split into focused
components living under a renamed `Hub/` package.

| Component | Owns                                                                                          | Depends on                                                                                                                                                                                                                                          |
|---|-----------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `Hub` | `EventBus`, executor/source registries                                                        | (composition root)                                                                                                                                                                                                                                  |
| `StatusStore` | `StatusReport` (current scene, scene status, per-device power/input state), `status_callback` | -                                                                                                                                                                                                                                                   |
| `KeymapResolver` | `keymap`, `keymap_scene`, `cached_commands`                                                   | DB (`Api.models.Command`)                                                                                                                                                                                                                           |
| `CommandDispatcher` | (stateless orchestrator)                                                                      | `StatusStore` (from_start/from_stop skip checks + post-send state update), `KeymapResolver` (command cache), `Hub`'s executor registry (looks up the right `ActionExecutor` by `CommandType` and calls `execute()`), handles macro delay sequencing |
| `SceneManager` | -                                                                                             | `StatusStore` (current scene), `KeymapResolver` (swap active keymap), `CommandDispatcher` (run start/stop macros), `BleKeyboard` (per-scene BT address connect/disconnect)                                                                          |
| `InputRouter` | -                                                                                             | subscribes to `key_pressed`/`key_released` on the bus; resolves the button via `KeymapResolver.resolve()`, then delegates to `SceneManager` or `CommandDispatcher`                                                                                  |

`StatusStore` broadcasts on every mutation itself (mirrors what
`_update_current_scene`/`update_device_status` do today) so callers can't
forget to notify. They call `set_device_state(...)` and the broadcast is a
side effect of the write.

IR command recording (today's `record_ir_command`, with its
websocket-streaming/cancellation flow) is **not** a separate top-level
class - it moves into `IrManager`, exposed via `IrManager`'s own router (see
below), since it's IR-specific and doesn't fit the generic dispatch path.

## Module-owned API surface

`InputSource`/`ActionExecutor` stay minimal (`start`/`execute` only) so the
generic dispatch path never needs to know a module's extra capabilities
exist. Any module that needs extra surface. BLE pairing/device-listing, IR
command recording, a future module's configuration screen brings its own
`APIRouter` via the optional `router` attribute, and the app composition
root mounts it if present:

```python
for module in [*hub.sources, *hub.executors.values()]:
    if module.router:
        app.include_router(module.router)
```

`BleKeyboard` defines pairing/device-list endpoints on its own router;
`IrManager` defines the command-recording endpoint (websocket) on its own
router. Neither lives in `Api/routers/` anymore as a generic
controller-forwarding function. They live next to the code that implements
them.

## Client API discovery

`GET /system/modules` A manifest built by `Hub` from its registered
modules, so a client app can discover and render capabilities without
hardcoding routes:

```json
{
  "modules": [
    {
      "name": "ble",
      "capabilities": ["pairing", "device_list"],
      "endpoints": {
        "pair": "/modules/ble/pair",
        "devices": "/modules/ble/devices"
      }
    },
    {
      "name": "ir",
      "capabilities": ["command_recording"],
      "endpoints": { "record": "/modules/ir/record" }
    }
  ]
}
```

Each module contributes `name` + `capabilities` (a class attribute) +
`endpoints` (derived from its own router). New capability
*types* still require client-side UI support; what this buys is that adding
or removing a module doesn't require an app update to know whether to show
the corresponding UI, and route paths can change server-side without
breaking the client.

## API layer: direct dependency injection

Routers depend on the specific component(s) they need instead of a single
facade object, so a reader can tell what a router touches from its imports
alone:

- `Api/routers/system.py` → `StatusStore`
- `Api/routers/scenes.py` → `SceneManager` (+ `KeymapResolver` for
  `suggest_keymap`)
- `Api/routers/commands.py`, `Api/routers/macros.py` → `CommandDispatcher`
- `Api/routers/bluetooth.py` and the `/ws/bt_pairing` websocket → `BleKeyboard`
  directly (its pairing methods were pure passthroughs; no wrapper needed)
- `/ws/commands` (IR recording) → moves into `IrManager`'s own router,
  removed from `Api/routers/websockets.py`
- `/ws/status` → `StatusStore` (registers `manager.broadcast_json` as its
  callback)

`Api/lifespan.py` builds `StatusStore`, `KeymapResolver`, `CommandDispatcher`,
`SceneManager`, and `Hub` (which owns `RfInput`, `BleKeyboard`, `IrManager`,
`HaManager`, `NetworkExecutor`, `ScriptExecutor`), and hands the relevant
pieces off via app/websocket state replacing the single `controller`
object used today.

## Proposed file layout

```
Hub/                          # renamed from RemoteController/
  Hub.py                      # composition root, module registries
  EventBus.py                 # Event, Directive, EventBus
  StatusStore.py
  KeymapResolver.py
  CommandDispatcher.py
  SceneManager.py
  InputRouter.py
BleKeyboard/
  BleKeyboard.py              # implements ActionExecutor; owns pairing router
IrManager/
  IrManager.py                # implements ActionExecutor; owns recording router
HaManager/
  HaManager.py                # implements ActionExecutor
RfManager/
  RfManager.py                # implements InputSource (async, run_in_executor)
NetworkExecutor/
  NetworkExecutor.py          # implements ActionExecutor
ScriptExecutor/
  ScriptExecutor.py           # implements ActionExecutor (stub)
```

## Explicitly deferred (unchanged from prior direction)

- `entry_points`-based plugin auto-discovery: reasonable next step if
  third-party pip-installable modules ever show up, not needed yet.
- MQTT-based process isolation between modules: fallback only if a native
  dependency conflict forces it.
