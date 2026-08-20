import json
import logging
from dataclasses import dataclass

from sqlmodel import Session

from api.models.command import Command
from api.models.device_type import DeviceType
from api.models.remote_button import RemoteButton
from api.models.scene import Scene
from db_manager.db_manager import engine
from hub.event_bus import Directive


@dataclass(frozen=True)
class StopScene:
    pass


@dataclass(frozen=True)
class StartScene:
    scene_id: int


@dataclass(frozen=True)
class SendDirective:
    directive: Directive


ButtonResolution = StopScene | StartScene | SendDirective


class KeymapResolver:
    """Owns the active keymap and resolves a raw button press into an action.

    Also owns the Command cache, since it's populated as a side effect of
    which keymap is active - CommandDispatcher reads it via get_command()
    rather than hitting the DB on every dispatch.
    """

    logger = logging.getLogger(__package__)

    _STOP_BUTTON = "Off"

    def __init__(self, config_dir: str = "config") -> None:
        self._config_dir = config_dir
        self._keymap: dict[str, int] = {}
        self._keymap_scene: dict[str, int] = {}
        self._cached_commands: dict[int, Command] = {}

    def load_key_map(self, keymap_name: str = "default") -> None:
        with open(f"{self._config_dir}/keymap_scenes.json") as file:
            self._keymap_scene = json.loads(file.read())

        with open(f"{self._config_dir}/keymap_{keymap_name}.json") as file:
            self._keymap = json.loads(file.read())

        self._cached_commands = {}
        for command_id in self._keymap.values():
            if command_id:
                self.get_command(command_id)

        self.logger.debug(f"Loaded keymap {keymap_name}")

    def get_command(self, command_id: int) -> Command | None:
        cached = self._cached_commands.get(command_id)
        if cached is not None:
            return cached

        with Session(engine) as session:
            command = session.get(Command, command_id)

        if command is not None:
            self._cached_commands[command_id] = command
        return command

    def resolve(self, button: str) -> ButtonResolution | None:
        if button == self._STOP_BUTTON:
            return StopScene()

        scene_id = self._keymap_scene.get(button)
        if scene_id is not None:
            return StartScene(scene_id)

        command_id = self._keymap.get(button)
        if command_id is not None:
            return SendDirective(Directive(command_id=command_id, press_without_release=True))

        return None

    def suggest_keymap(self, scene: Scene) -> dict[str, int | None]:
        try:
            with open(f"{self._config_dir}/remote_keymap.json") as file:
                keymap_json = json.loads(file.read())
        except FileNotFoundError:
            self.logger.warning(
                f"\"{self._config_dir}/remote_keymap.json\" could not be opened. Can't generate suggested keymap."
            )
            return {}

        available_buttons = {}
        keymap_suggestion: dict[str, int | None] = {}

        for key, value in keymap_json.items():
            available_buttons[value["button"]] = key
            keymap_suggestion[key] = None

        def assign_key_if_exists(device, button: RemoteButton) -> None:
            matching_remote_button = available_buttons.get(button)
            if matching_remote_button is not None:
                matching_command = next((x for x in device.commands if x.button == button), None)
                if matching_command is not None:
                    keymap_suggestion[matching_remote_button] = matching_command.id

        amplifier = next((x for x in scene.devices if x.type == DeviceType.AMPLIFIER), None)
        if amplifier is not None:
            assign_key_if_exists(amplifier, RemoteButton.VOLUME_UP)
            assign_key_if_exists(amplifier, RemoteButton.VOLUME_DOWN)
            assign_key_if_exists(amplifier, RemoteButton.MUTE)

        player = next((x for x in scene.devices if x.type == DeviceType.PLAYER), None)
        if player is None:
            player = next((x for x in scene.devices if x.type == DeviceType.DISPLAY), None)

        if player is not None:
            assign_key_if_exists(player, RemoteButton.RED)
            assign_key_if_exists(player, RemoteButton.GREEN)
            assign_key_if_exists(player, RemoteButton.YELLOW)
            assign_key_if_exists(player, RemoteButton.BLUE)

            assign_key_if_exists(player, RemoteButton.GUIDE)
            assign_key_if_exists(player, RemoteButton.INFO)

            assign_key_if_exists(player, RemoteButton.EXIT)
            assign_key_if_exists(player, RemoteButton.MENU)

            assign_key_if_exists(player, RemoteButton.DIRECTION_UP)
            assign_key_if_exists(player, RemoteButton.DIRECTION_DOWN)
            assign_key_if_exists(player, RemoteButton.DIRECTION_LEFT)
            assign_key_if_exists(player, RemoteButton.DIRECTION_RIGHT)
            assign_key_if_exists(player, RemoteButton.SELECT)
            assign_key_if_exists(player, RemoteButton.BACK)

            if keymap_suggestion.get(RemoteButton.VOLUME_UP) is None:
                assign_key_if_exists(player, RemoteButton.VOLUME_UP)
            if keymap_suggestion.get(RemoteButton.VOLUME_DOWN) is None:
                assign_key_if_exists(player, RemoteButton.VOLUME_DOWN)
            if keymap_suggestion.get(RemoteButton.MUTE) is None:
                assign_key_if_exists(player, RemoteButton.MUTE)

            assign_key_if_exists(player, RemoteButton.CHANNEL_UP)
            assign_key_if_exists(player, RemoteButton.CHANNEL_DOWN)

            assign_key_if_exists(player, RemoteButton.REWIND)
            assign_key_if_exists(player, RemoteButton.FAST_FORWARD)
            assign_key_if_exists(player, RemoteButton.PLAY)
            assign_key_if_exists(player, RemoteButton.PAUSE)
            assign_key_if_exists(player, RemoteButton.PLAYPAUSE)
            assign_key_if_exists(player, RemoteButton.STOP)
            assign_key_if_exists(player, RemoteButton.RECORD)

            assign_key_if_exists(player, RemoteButton.NUMBER_ONE)
            assign_key_if_exists(player, RemoteButton.NUMBER_TWO)
            assign_key_if_exists(player, RemoteButton.NUMBER_THREE)
            assign_key_if_exists(player, RemoteButton.NUMBER_FOUR)
            assign_key_if_exists(player, RemoteButton.NUMBER_FIVE)
            assign_key_if_exists(player, RemoteButton.NUMBER_SIX)
            assign_key_if_exists(player, RemoteButton.NUMBER_SEVEN)
            assign_key_if_exists(player, RemoteButton.NUMBER_EIGHT)
            assign_key_if_exists(player, RemoteButton.NUMBER_NINE)
            assign_key_if_exists(player, RemoteButton.NUMBER_ZERO)

        return keymap_suggestion
