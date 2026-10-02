"""The command surface: login, logout, whoami, and the flags every command wires up."""

from __future__ import annotations

import pytest

from freepod import EXIT_NOT_AUTHENTICATED, EXIT_OK, EXIT_USAGE
from freepod.auth import load_refresh_token, store_refresh_token
from freepod.cli import main

from conftest import json_response, sequence, text_response


ME = {"id": 7, "email": "erik@example.com", "is_admin": False}


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def test_help_exits_zero(capsys):
    assert main(["--help"]) == EXIT_OK
    assert "login" in capsys.readouterr().out


@pytest.mark.parametrize(
    "command", ["login", "logout", "whoami", "init", "deploy", "delete", "builds"]
)
def test_every_command_has_help(command, capsys):
    assert main([command, "--help"]) == EXIT_OK
    capsys.readouterr()


def test_an_unknown_environment_is_a_usage_error(capsys):
    assert main(["--env", "staging", "logout"]) == EXIT_USAGE
    assert "staging" in capsys.readouterr().err


def test_an_unknown_command_is_a_usage_error(capsys):
    assert main(["frobnicate"]) == EXIT_USAGE
    capsys.readouterr()


# --------------------------------------------------------------------------
# Negative flags
#
# `--no-gitignore` and `--no-wait` name the *departure* from the default, so
# the default they depart from has to survive a click upgrade. It did not:
# `flag_value=False, default=True` yields True on click 8.1 and False on 8.3,
# which silently inverts both. These pin the resolved value rather than the
# spelling, so either declaration passes only if it behaves.
# --------------------------------------------------------------------------


@pytest.fixture
def capture_deploy(monkeypatch, cached_credential):
    """Run `deploy` far enough to see the arguments it assembled."""
    seen = {}

    def fake_deploy(_api, _env_name, **kwargs):
        seen.update(kwargs)
        return "https://myapp.freepod.eu"

    monkeypatch.setattr("freepod.cli.deploy_module.deploy", fake_deploy)
    return seen


@pytest.fixture
def capture_delete(monkeypatch, cached_credential):
    """Run `delete` far enough to see the arguments it assembled."""
    seen = {}

    def fake_delete(_api, _env_name, **kwargs):
        seen.update(kwargs)
        return True

    monkeypatch.setattr("freepod.cli.delete_module.delete", fake_delete)
    return seen


def test_deploy_honors_gitignore_unless_told_not_to(capture_deploy, capsys):
    assert main(["deploy"]) == EXIT_OK
    assert capture_deploy["honor_gitignore"] is True
    capsys.readouterr()


def test_no_gitignore_turns_it_off(capture_deploy, capsys):
    assert main(["deploy", "--no-gitignore"]) == EXIT_OK
    assert capture_deploy["honor_gitignore"] is False
    capsys.readouterr()


def test_delete_follows_the_teardown_unless_told_not_to(capture_delete, capsys):
    assert main(["delete"]) == EXIT_OK
    assert capture_delete["wait"] is True
    capsys.readouterr()


def test_no_wait_returns_once_the_teardown_is_scheduled(capture_delete, capsys):
    assert main(["delete", "--no-wait"]) == EXIT_OK
    assert capture_delete["wait"] is False
    capsys.readouterr()


def test_delete_confirms_unless_yes_is_given(capture_delete, capsys):
    assert main(["delete"]) == EXIT_OK
    assert capture_delete["assume_yes"] is False

    assert main(["delete", "--yes"]) == EXIT_OK
    assert capture_delete["assume_yes"] is True
    capsys.readouterr()


# --------------------------------------------------------------------------
# logout
# --------------------------------------------------------------------------


def test_logout_discards_the_cached_credential(capsys):
    store_refresh_token("prod", "freepod-cli-prod", "prod-refresh")

    assert main(["logout"]) == EXIT_OK

    assert load_refresh_token("prod") is None
    assert "Removed the stored credential from" in capsys.readouterr().err


def test_logout_with_nothing_cached_says_so(capsys):
    assert main(["logout"]) == EXIT_OK
    assert "No stored credential in" in capsys.readouterr().err


def test_logout_states_that_it_revokes_nothing(capsys):
    main(["logout"])
    stderr = capsys.readouterr().err
    assert "stays valid until you revoke it" in stderr
    assert "https://keycloak.freepod.eu/realms/freepod/account" in stderr


def test_logout_targets_only_the_selected_environment(capsys):
    store_refresh_token("prod", "freepod-cli-prod", "prod-refresh")
    store_refresh_token("dev", "freepod-cli-dev", "dev-refresh")

    assert main(["--env", "dev", "logout"]) == EXIT_OK

    assert load_refresh_token("dev") is None
    assert load_refresh_token("prod") == "prod-refresh"
    capsys.readouterr()


# --------------------------------------------------------------------------
# Environment inference from the project file
# --------------------------------------------------------------------------


def test_the_project_file_selects_the_environment(capsys, tmp_path, monkeypatch):
    """The reported friction: a project on dev must not need `--env dev`."""
    from freepod.project import Project

    store_refresh_token("prod", "freepod-cli-prod", "prod-refresh")
    store_refresh_token("dev", "freepod-cli-dev", "dev-refresh")
    Project(root=tmp_path, env="dev", user_values={"hostname": "a.dev.freepod.eu"}).save()
    monkeypatch.chdir(tmp_path)

    assert main(["logout"]) == EXIT_OK

    assert load_refresh_token("dev") is None
    assert load_refresh_token("prod") == "prod-refresh"
    capsys.readouterr()


def test_an_explicit_env_overrides_the_project_file(capsys, tmp_path, monkeypatch):
    from freepod.project import Project

    store_refresh_token("prod", "freepod-cli-prod", "prod-refresh")
    store_refresh_token("dev", "freepod-cli-dev", "dev-refresh")
    Project(root=tmp_path, env="dev", user_values={"hostname": "a.dev.freepod.eu"}).save()
    monkeypatch.chdir(tmp_path)

    assert main(["--env", "prod", "logout"]) == EXIT_OK

    assert load_refresh_token("prod") is None
    assert load_refresh_token("dev") == "dev-refresh"
    capsys.readouterr()


def test_a_project_file_without_an_environment_stays_on_prod(capsys, tmp_path, monkeypatch):
    """Absent means prod, so the variable cannot pull the project elsewhere."""
    from freepod.project import Project

    store_refresh_token("prod", "freepod-cli-prod", "prod-refresh")
    store_refresh_token("dev", "freepod-cli-dev", "dev-refresh")
    Project(root=tmp_path, user_values={"hostname": "a.freepod.eu"}).save()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FREEPOD_ENV", "dev")

    assert main(["logout"]) == EXIT_OK

    assert load_refresh_token("prod") is None
    assert load_refresh_token("dev") == "dev-refresh"
    capsys.readouterr()


def test_a_broken_project_file_does_not_break_a_command_without_one(capsys, tmp_path, monkeypatch):
    """Inference is best-effort: `logout` has no business in the project, so a
    broken file falls back to the ordinary default rather than failing."""
    (tmp_path / ".freepod.json").write_text("{not json", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main(["logout"]) == EXIT_OK
    assert "No stored credential in" in capsys.readouterr().err


def test_an_unknown_environment_in_the_file_does_not_break_other_commands(
    capsys, tmp_path, monkeypatch
):
    """A name this client does not know must not brick the directory: `init
    --force` is the only way to repair the file, and it runs through the same
    group callback as everything else."""
    from freepod.project import Project

    Project(root=tmp_path, env="staging", user_values={}).save()
    monkeypatch.chdir(tmp_path)

    assert main(["logout"]) == EXIT_OK
    assert "No stored credential in" in capsys.readouterr().err


def test_an_empty_env_is_a_usage_error(capsys, tmp_path, monkeypatch):
    """An unset shell variable expands to this. Falling through to prod would
    deploy on the strength of a variable the script believed it had set."""
    from freepod import EXIT_USAGE

    monkeypatch.chdir(tmp_path)

    assert main(["--env", "", "whoami"]) == EXIT_USAGE
    assert "--env was given an empty value" in capsys.readouterr().err


# --------------------------------------------------------------------------
# whoami
# --------------------------------------------------------------------------


def test_whoami_reports_the_identity(stub_api, cached_credential, capsys):
    stub_api(sequence(json_response(200, ME)))

    assert main(["whoami"]) == EXIT_OK

    stdout = capsys.readouterr().out
    assert "erik@example.com" in stdout
    assert "user id: 7" in stdout


def test_whoami_without_a_credential_exits_three(capsys):
    assert main(["whoami"]) == EXIT_NOT_AUTHENTICATED
    assert "not authenticated" in capsys.readouterr().err


def test_whoami_never_opens_a_browser(monkeypatch, capsys):
    from freepod.auth import Session

    monkeypatch.setattr(
        Session, "login", lambda self: pytest.fail("whoami must not start a login")
    )
    assert main(["whoami"]) == EXIT_NOT_AUTHENTICATED
    capsys.readouterr()


def test_whoami_keeps_diagnostics_off_stdout(stub_api, cached_credential, capsys):
    """A redirected stdout carries only the result."""
    stub_api(sequence(json_response(200, ME)))

    main(["whoami"])

    captured = capsys.readouterr()
    assert captured.out == "erik@example.com\nuser id: 7\n"


def test_whoami_does_not_name_the_environment(stub_api, cached_credential, capsys):
    stub_api(sequence(json_response(200, ME)))

    main(["whoami"])

    captured = capsys.readouterr()
    assert "prod" not in captured.out + captured.err


def test_the_env_option_is_hidden_but_still_accepted(capsys):
    main(["--help"])
    out = capsys.readouterr().out
    assert "--env" not in out
    assert "FREEPOD_ENV" not in out
    assert "dev" not in out

    assert main(["--env", "dev", "logout"]) == EXIT_OK
    assert "for 'dev'" in capsys.readouterr().err


def test_whoami_surfaces_a_401_as_not_authenticated(stub_api, cached_credential, capsys):
    stub_api(sequence(text_response(401)))

    assert main(["whoami"]) == EXIT_NOT_AUTHENTICATED
    assert "401" in capsys.readouterr().err


# --------------------------------------------------------------------------
# login
# --------------------------------------------------------------------------


def test_login_reuses_a_valid_cached_credential(stub_api, cached_credential, monkeypatch, capsys):
    from freepod.auth import Session

    monkeypatch.setattr(
        Session, "login", lambda self: pytest.fail("a valid credential must not prompt a login")
    )
    stub_api(sequence(json_response(200, ME)))

    assert main(["login"]) == EXIT_OK

    stderr = capsys.readouterr().err
    assert "Signed in as erik@example.com" in stderr
    assert "cached refresh token" in stderr


def test_login_force_ignores_the_cache(stub_api, cached_credential, monkeypatch, capsys):
    from freepod.auth import Session

    logins = []

    def fake_login(self):
        logins.append(True)
        self.access_token = "fresh-at"
        self.flow_used = "device"

    monkeypatch.setattr(Session, "login", fake_login)
    stub_api(sequence(json_response(200, ME)))

    assert main(["login", "--force"]) == EXIT_OK

    assert logins == [True]
    capsys.readouterr()


def test_login_reports_which_flow_it_used(stub_api, cached_credential, monkeypatch, capsys):
    from freepod.auth import Session

    def fake_login(self):
        self.access_token = "fresh-at"
        self.flow_used = "device"

    monkeypatch.setattr(Session, "login", fake_login)
    stub_api(sequence(json_response(200, ME)))

    main(["login", "--force"])

    assert "flow       : device" in capsys.readouterr().err


def test_login_passes_the_forced_flow_through(monkeypatch, stub_api, capsys):
    from freepod.auth import Session

    seen = {}

    def fake_login(self):
        seen["flow"] = self.choose_flow()[0]
        self.access_token = "fresh-at"

    monkeypatch.setattr(Session, "login", fake_login)
    monkeypatch.setattr(
        "freepod.auth.detect_browser",
        lambda: pytest.fail("detection must not run when the flow is forced"),
    )
    stub_api(sequence(json_response(200, ME)))

    main(["login", "--device"])

    assert seen["flow"] == "device"
    capsys.readouterr()


def test_login_writes_no_token_to_either_stream(stub_api, cached_credential, capsys):
    stub_api(sequence(json_response(200, ME)))

    main(["--verbose", "login"])

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "fresh-at" not in combined
    assert "prod-refresh" not in combined


def test_the_timeout_flag_reaches_the_login_wait(monkeypatch, stub_api, capsys):
    from freepod.auth import Session

    seen = {}

    def fake_login(self):
        seen["timeout"] = self.timeout
        self.access_token = "fresh-at"

    monkeypatch.setattr(Session, "login", fake_login)
    stub_api(sequence(json_response(200, ME)))

    main(["--timeout", "42", "login"])

    assert seen["timeout"] == 42
    capsys.readouterr()


def test_the_login_wait_defaults_to_its_own_value(monkeypatch, stub_api, capsys):
    from freepod.auth import Session
    from freepod.config import LOGIN_WAIT_SECONDS

    seen = {}

    def fake_login(self):
        seen["timeout"] = self.timeout
        self.access_token = "fresh-at"

    monkeypatch.setattr(Session, "login", fake_login)
    stub_api(sequence(json_response(200, ME)))

    main(["login"])

    assert seen["timeout"] == LOGIN_WAIT_SECONDS
    capsys.readouterr()
