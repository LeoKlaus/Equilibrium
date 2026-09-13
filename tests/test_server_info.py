import subprocess
from unittest.mock import patch

from api.models.server_info import ServerInfo, _resolve_version


def test_uses_app_version_env_var_when_set(monkeypatch):
    # The production path: baked into the Docker image at build time
    # from the git tag build-container.yml builds/pushes with (see the
    # Dockerfile's VERSION build arg) - always preferred over git
    # itself, since a container has no .git directory to inspect.
    monkeypatch.setenv("APP_VERSION", "1.4.2")
    assert _resolve_version() == "1.4.2"


def test_falls_back_to_git_describe_when_env_var_is_unset(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    with patch("subprocess.check_output", return_value="v1.4.2-3-gabc1234\n") as mock_git:
        version = _resolve_version()

    mock_git.assert_called_once_with(
        ["git", "describe", "--tags", "--always", "--dirty"],
        stderr=subprocess.DEVNULL, text=True,
    )
    assert version == "v1.4.2-3-gabc1234"


def test_falls_back_to_git_describe_when_env_var_is_blank(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "   ")
    with patch("subprocess.check_output", return_value="v1.4.2\n"):
        assert _resolve_version() == "v1.4.2"


def test_falls_back_to_dev_when_not_a_git_checkout(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(128, "git")):
        assert _resolve_version() == "dev"


def test_falls_back_to_dev_when_git_is_not_installed(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    with patch("subprocess.check_output", side_effect=FileNotFoundError()):
        assert _resolve_version() == "dev"


def test_server_info_reports_the_resolved_version(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "2.0.0")
    assert ServerInfo().version == "2.0.0"


def test_server_info_resolves_fresh_per_instance(monkeypatch):
    # Confirms this is a default_factory, not a value computed once at
    # import time - each ServerInfo() must reflect the env var at the
    # moment it's constructed, matching what a real /info request does.
    monkeypatch.setenv("APP_VERSION", "1.0.0")
    assert ServerInfo().version == "1.0.0"

    monkeypatch.setenv("APP_VERSION", "1.0.1")
    assert ServerInfo().version == "1.0.1"
