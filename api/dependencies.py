from typing import Annotated

from fastapi import Depends, Request
from starlette.websockets import WebSocket

from api.log_broadcaster import LogBroadcaster
from hub.command_dispatcher import CommandDispatcher
from hub.keymap_resolver import KeymapResolver
from hub.scene_manager import SceneManager
from hub.status_store import StatusStore

# Mirrors DbManager.SessionDep's Annotated[..., Depends(...)] pattern. The
# underlying values still come from api.lifespan's yielded state - these are
# just typed accessors for it, one per HTTP/websocket connection type since
# FastAPI's Depends() distinguishes Request from WebSocket.


def get_status_store(request: Request) -> StatusStore:
    return request.state.status_store


def get_status_store_ws(websocket: WebSocket) -> StatusStore:
    return websocket.state.status_store


def get_keymap_resolver(request: Request) -> KeymapResolver:
    return request.state.keymap_resolver


def get_scene_manager(request: Request) -> SceneManager:
    return request.state.scene_manager


def get_command_dispatcher(request: Request) -> CommandDispatcher:
    return request.state.command_dispatcher


def get_modules_manifest(request: Request) -> list[dict]:
    return request.state.modules_manifest


def get_log_broadcaster(request: Request) -> LogBroadcaster:
    return request.state.log_broadcaster


def get_log_broadcaster_ws(websocket: WebSocket) -> LogBroadcaster:
    return websocket.state.log_broadcaster


StatusStoreDep = Annotated[StatusStore, Depends(get_status_store)]
StatusStoreWsDep = Annotated[StatusStore, Depends(get_status_store_ws)]
KeymapResolverDep = Annotated[KeymapResolver, Depends(get_keymap_resolver)]
SceneManagerDep = Annotated[SceneManager, Depends(get_scene_manager)]
CommandDispatcherDep = Annotated[CommandDispatcher, Depends(get_command_dispatcher)]
ModulesManifestDep = Annotated[list[dict], Depends(get_modules_manifest)]
LogBroadcasterDep = Annotated[LogBroadcaster, Depends(get_log_broadcaster)]
LogBroadcasterWsDep = Annotated[LogBroadcaster, Depends(get_log_broadcaster_ws)]
