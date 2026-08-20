import json

import pytest
from sqlmodel import Session

from Api.models.Command import Command
from Api.models.CommandGroupType import CommandGroupType
from Api.models.CommandType import CommandType
from Api.models.Device import Device
from Api.models.DeviceType import DeviceType
from Api.models.RemoteButton import RemoteButton
from Api.models.Scene import Scene
from hub.keymap_resolver import KeymapResolver, SendDirective, StartScene, StopScene


@pytest.fixture
def keymap_dir(tmp_path):
    (tmp_path / "keymap_scenes.json").write_text(json.dumps({"Scene1": 10}))
    (tmp_path / "keymap_default.json").write_text(json.dumps({"Play": 1}))
    (tmp_path / "remote_keymap.json").write_text(json.dumps({"Play": {"button": "play"}}))
    return str(tmp_path)


@pytest.fixture
def resolver(db_engine, keymap_dir, monkeypatch):
    monkeypatch.setattr("hub.keymap_resolver.engine", db_engine)

    with Session(db_engine) as session:
        session.add(Command(
            name="Play",
            button=RemoteButton.PLAY,
            type=CommandType.IR,
            command_group=CommandGroupType.TRANSPORT,
            ir_action="deadbeef",
        ))
        session.commit()

    resolver = KeymapResolver(config_dir=keymap_dir)
    resolver.load_key_map()
    return resolver


def test_resolve_stop_button(resolver):
    assert resolver.resolve("Off") == StopScene()


def test_resolve_scene_button(resolver):
    assert resolver.resolve("Scene1") == StartScene(10)


def test_resolve_command_button(resolver):
    result = resolver.resolve("Play")

    assert isinstance(result, SendDirective)
    assert result.directive.command_id == 1
    assert result.directive.press_without_release is True


def test_resolve_unmapped_button_returns_none(resolver):
    assert resolver.resolve("Unmapped") is None


def test_get_command_caches_across_calls(resolver):
    first = resolver.get_command(1)
    second = resolver.get_command(1)

    assert first is second
    assert first.name == "Play"


def test_get_command_missing_returns_none(resolver):
    assert resolver.get_command(999) is None


def test_suggest_keymap_matches_player_commands(db_engine, keymap_dir, monkeypatch):
    monkeypatch.setattr("hub.keymap_resolver.engine", db_engine)

    with Session(db_engine) as session:
        device = Device(name="Player", type=DeviceType.PLAYER)
        session.add(device)
        session.commit()
        session.refresh(device)

        session.add(Command(
            name="Play",
            button=RemoteButton.PLAY,
            type=CommandType.IR,
            command_group=CommandGroupType.TRANSPORT,
            ir_action="deadbeef",
            device_id=device.id,
        ))
        session.commit()

        scene = Scene(name="Movie Night", devices=[device])
        session.add(scene)
        session.commit()
        session.refresh(scene)
        scene_id = scene.id

    resolver = KeymapResolver(config_dir=keymap_dir)

    with Session(db_engine) as session:
        scene = session.get(Scene, scene_id)
        suggestion = resolver.suggest_keymap(scene)

    assert suggestion["Play"] is not None


def test_suggest_keymap_missing_remote_keymap_file_returns_empty(db_engine, tmp_path, monkeypatch):
    monkeypatch.setattr("hub.keymap_resolver.engine", db_engine)

    resolver = KeymapResolver(config_dir=str(tmp_path))
    scene = Scene(name="Empty Scene", devices=[])

    assert resolver.suggest_keymap(scene) == {}
