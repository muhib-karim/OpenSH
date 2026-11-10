"""Shared fixtures. `opsh` is importable because pyproject.toml puts the repo root on the path."""
import pathlib

import pytest

import opsh

LINUX = {"name": "Linux", "shell": "bash", "home": pathlib.Path.home(), "path_sep": "/"}
WINDOWS = {"name": "Windows", "shell": "PowerShell", "home": pathlib.Path.home(), "path_sep": "\\"}
MACOS = {"name": "macOS", "shell": "zsh", "home": pathlib.Path.home(), "path_sep": "/"}

_ENV_VARS = ("GROQ_API_KEY", "GEMINI_API_KEY", "OPSH_MODEL", "OPSH_HOME", "OPSH_TIMEOUT",
             "OPSH_NO_UPDATE_CHECK", "NO_COLOR")


def _no_network(*args, **kwargs):
    raise AssertionError("tests must not touch the network; stub opsh.urllib.request.urlopen")


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """Keep every test away from the network and the real config, .env, history, environment and home folder."""
    monkeypatch.setattr(opsh.urllib.request, "urlopen", _no_network)
    monkeypatch.setattr(opsh, "config_path", tmp_path / "config.json")
    monkeypatch.setattr(opsh, "env_path", tmp_path / ".env")
    monkeypatch.setattr(opsh, "command_history", [])
    monkeypatch.setattr(opsh, "_previous_dir", None)
    monkeypatch.setattr(opsh, "_color_enabled", True)
    monkeypatch.setattr(opsh.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setattr(opsh, "PLATFORM", LINUX)
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
