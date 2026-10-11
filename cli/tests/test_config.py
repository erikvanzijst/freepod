"""Environment selection and the config directory."""

from __future__ import annotations

import os
import stat

import pytest

from freepod import UsageError
from freepod.config import (
    ENVIRONMENTS,
    config_dir,
    ensure_config_dir,
    resolve_environment,
    token_cache_path,
    wait_seconds,
)


def test_production_is_the_default_target():
    assert resolve_environment().name == "prod"
    assert resolve_environment(None).api_base == "https://freepod.eu"


def test_dev_carries_its_own_client_and_api_base():
    dev = resolve_environment("dev")
    assert dev.client_id == "freepod-cli-dev"
    assert dev.api_base == "https://dev.freepod.eu"


def test_both_environments_share_one_issuer():
    # D2's table says "same" for the dev issuer, and the token cache's
    # per-environment keying is what separates them, not the issuer.
    assert ENVIRONMENTS["dev"].issuer == ENVIRONMENTS["prod"].issuer


def test_the_environment_variable_selects_the_environment(monkeypatch):
    monkeypatch.setenv("FREEPOD_ENV", "dev")
    assert resolve_environment().name == "dev"


def test_the_project_file_selects_the_environment():
    """The reported friction: a project on dev must not need `--env dev`."""
    dev = resolve_environment(project_env="dev")
    assert dev.name == "dev"
    assert dev.api_base == "https://dev.freepod.eu"


def test_explicit_selection_wins_over_the_project_file():
    assert resolve_environment("prod", project_env="dev").name == "prod"


def test_the_project_file_wins_over_the_environment_variable(monkeypatch):
    """The file is the most specific signal of where this project lives, so a
    global default must not pull a command away from it."""
    monkeypatch.setenv("FREEPOD_ENV", "prod")
    assert resolve_environment(project_env="dev").name == "dev"


def test_explicit_selection_wins_over_the_environment_variable(monkeypatch):
    monkeypatch.setenv("FREEPOD_ENV", "dev")
    assert resolve_environment("prod").name == "prod"


def test_an_unknown_environment_is_a_usage_error():
    with pytest.raises(UsageError) as raised:
        resolve_environment("staging")
    message = str(raised.value)
    assert "staging" in message
    assert "dev" in message and "prod" in message


def test_an_unknown_environment_variable_is_also_a_usage_error(monkeypatch):
    monkeypatch.setenv("FREEPOD_ENV", "staging")
    with pytest.raises(UsageError) as raised:
        resolve_environment()
    assert "FREEPOD_ENV" in str(raised.value)


def test_an_unknown_environment_in_the_project_file_names_the_file():
    with pytest.raises(UsageError) as raised:
        resolve_environment(project_env="staging")
    message = str(raised.value)
    assert "staging" in message
    assert ".freepod.json" in message


def test_only_dev_gates_on_a_group():
    # The 401 message is only actionable if it names this, and only dev has it:
    # tf/app/main.tf sets allowed_groups to [] on the prod workspace.
    assert ENVIRONMENTS["dev"].requires_group == "freepod-dev"
    assert ENVIRONMENTS["prod"].requires_group is None


@pytest.mark.posix
def test_the_config_directory_is_owner_only():
    directory = ensure_config_dir()
    mode = stat.S_IMODE(os.stat(directory).st_mode)
    assert mode == 0o700, f"expected 0700, got {mode:o}"


@pytest.mark.posix
def test_an_existing_loose_directory_is_tightened():
    directory = ensure_config_dir()
    os.chmod(directory, 0o755)
    ensure_config_dir()
    assert stat.S_IMODE(os.stat(directory).st_mode) == 0o700


def test_resolving_the_cache_path_creates_nothing():
    # `logout` with no credential should not conjure a config directory.
    path = token_cache_path()
    assert not path.exists()
    assert not path.parent.exists()


def test_xdg_config_home_is_honored(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "elsewhere"))
    assert config_dir() == tmp_path / "elsewhere" / "freepod"


def test_the_config_directory_falls_back_to_dot_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert config_dir() == tmp_path / ".config" / "freepod"


def test_a_wait_falls_back_to_the_operation_default():
    assert wait_seconds(None, 300) == 300
    assert wait_seconds(60, 300) == 60


def test_a_nonpositive_timeout_is_a_usage_error():
    with pytest.raises(UsageError):
        wait_seconds(0, 300)
    with pytest.raises(UsageError):
        wait_seconds(-5, 300)
