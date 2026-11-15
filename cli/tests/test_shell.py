"""`freepod shell`: the argv it assembles, and the refusals it makes first.

The interactive session itself cannot be exercised here — it owns a real
terminal — so `run_interactive` is stubbed to capture the argv and the
connection is asserted on its arguments. Everything up to that call, including
the pre-flight refusals, is real.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from freepod import EXIT_ERROR, EXIT_OK, EXIT_USAGE
from freepod import keys as keys_module
from freepod.cli import main

from conftest import json_response

USER = {"id": 7, "email": "dev@example.com", "is_admin": False}
DEPLOYMENT_ID = "7214d804-7f9b-46d2-b1f4-1b911b8a339e"
DEPLOYMENT_NAME = "custom-user-app-2rakm1"
EDGE = {
    "host": "ssh.dev.freepod.eu",
    "port": 2222,
    "host_key": {"ssh-ed25519": "AAAAedgekey"},
}


def project_at(tmp_path: Path, *, env="prod") -> Path:
    document = {"version": 2, "env": env, "deployment": DEPLOYMENT_ID, "hostname": "dbprobe"}
    (tmp_path / ".freepod.json").write_text(json.dumps(document), encoding="utf-8")
    return tmp_path


def key_entry() -> dict:
    """A registered key for the keypair this machine is made to hold."""
    line = keys_module.generated_key_path().with_suffix(".pub").read_text().strip()
    return {
        "fingerprint": keys_module.fingerprint_for_line(line),
        "key_type": line.split()[0],
        "bits": 256,
        "label": "me@here",
        "public_key": " ".join(line.split()[:2]),
        "created_at": "2026-08-27T10:00:00",
    }


class Platform:
    """The reads `shell` performs: me, the deployment, the edge, the keys."""

    def __init__(self, *, deployment=None, keys=None):
        self.deployment = deployment
        self.keys = list(keys or [])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        path = request.url.path
        if path == "/api/me":
            return json_response(200, USER)
        if path == f"/api/users/7/deployments/{DEPLOYMENT_ID}":
            if self.deployment is None:
                return json_response(404, {"detail": "not found"})
            return json_response(200, self.deployment)
        if path == "/api/users/7/ssh-keys":
            return json_response(200, self.keys)
        if path == "/api/ssh":
            return json_response(200, EDGE)
        return json_response(404, {"detail": f"no route for {path}"})


@pytest.fixture
def no_ssh(monkeypatch):
    """Neither prerequisite nor execution touches the outside world."""
    monkeypatch.setattr("freepod.ssh.require_ssh", lambda: "/usr/bin/ssh")


@pytest.fixture
def capture_interactive(monkeypatch):
    """Record the argv `run_interactive` is handed and report a clean exit."""
    captured: dict = {}
    monkeypatch.setattr(
        "freepod.ssh.run_interactive", lambda args: captured.update(args=args) or 0
    )
    return captured


def test_shell_assembles_one_key_and_a_tty(
    stub_api, cached_credential, no_ssh, capture_interactive, tmp_path, monkeypatch
):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    stub_api(
        Platform(
            deployment={
                "id": DEPLOYMENT_ID,
                "name": DEPLOYMENT_NAME,
                "status": "ready",
            },
            keys=[key_entry()],
        )
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(["shell"])
    assert exc.value.code == EXIT_OK

    args = capture_interactive["args"]
    # A forced tty, and the deployment's namespace as the user.
    assert "-tt" in args
    assert f"{DEPLOYMENT_ID}@{EDGE['host']}" in args
    # Exactly one identity, the private half of the key this machine holds.
    assert args.count("-i") == 1
    assert args[args.index("-i") + 1] == str(keys_module.generated_key_path())
    # The edge, pinned to the published key.
    assert args[args.index("-p") + 1] == str(EDGE["port"])
    assert any(a.startswith("UserKnownHostsFile=") for a in args)
    assert "StrictHostKeyChecking=yes" in args
    # A shell carries no remote command and no forward.
    assert "-N" not in args and "-L" not in args


def test_shell_runs_a_remote_command_without_a_terminal(
    stub_api, cached_credential, no_ssh, capture_interactive, tmp_path, monkeypatch
):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    stub_api(
        Platform(
            deployment={
                "id": DEPLOYMENT_ID,
                "name": DEPLOYMENT_NAME,
                "status": "ready",
            },
            keys=[key_entry()],
        )
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(["shell", "ls", "-la", "/app"])
    assert exc.value.code == EXIT_OK

    args = capture_interactive["args"]
    # The command's own words, in order, after the destination -- ssh joins
    # them itself, so the remote shell sees what a plain `ssh host ls -la` would.
    assert args[args.index(f"{DEPLOYMENT_ID}@{EDGE['host']}") + 1 :] == ["ls", "-la", "/app"]
    # No pty: it would translate line endings and fold stderr into stdout,
    # which is corruption for a command whose output is redirected.
    assert "-tt" not in args


def test_shell_forces_a_terminal_when_asked(
    stub_api, cached_credential, no_ssh, capture_interactive, tmp_path, monkeypatch
):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    stub_api(
        Platform(
            deployment={
                "id": DEPLOYMENT_ID,
                "name": DEPLOYMENT_NAME,
                "status": "ready",
            },
            keys=[key_entry()],
        )
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(["shell", "--tty", "top"])
    assert exc.value.code == EXIT_OK

    args = capture_interactive["args"]
    assert "-tt" in args
    assert args[-1] == "top"


def test_shell_does_not_parse_the_commands_own_options(
    stub_api, cached_credential, no_ssh, capture_interactive, tmp_path, monkeypatch
):
    """`-t` after the command is the command's, not this client's."""
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    stub_api(
        Platform(
            deployment={
                "id": DEPLOYMENT_ID,
                "name": DEPLOYMENT_NAME,
                "status": "ready",
            },
            keys=[key_entry()],
        )
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(["shell", "sort", "-t", ":", "/etc/passwd"])
    assert exc.value.code == EXIT_OK

    args = capture_interactive["args"]
    assert args[-4:] == ["sort", "-t", ":", "/etc/passwd"]
    # The command asked for `-t`; the session did not.
    assert "-tt" not in args


def test_shell_propagates_the_remote_exit_status(
    stub_api, cached_credential, no_ssh, tmp_path, monkeypatch
):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    stub_api(
        Platform(
            deployment={
                "id": DEPLOYMENT_ID,
                "name": DEPLOYMENT_NAME,
                "status": "ready",
            },
            keys=[key_entry()],
        )
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("freepod.ssh.run_interactive", lambda args: 7)

    with pytest.raises(SystemExit) as exc:
        main(["shell", "false"])
    assert exc.value.code == 7


def test_shell_refuses_a_deployment_that_is_not_settled(
    stub_api, cached_credential, no_ssh, capture_interactive, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    stub_api(
        Platform(deployment={"id": DEPLOYMENT_ID, "name": DEPLOYMENT_NAME, "status": "provisioning"}, keys=[key_entry()])
    )
    monkeypatch.chdir(tmp_path)

    assert main(["shell"]) == EXIT_ERROR
    assert not capture_interactive  # no connection was attempted
    assert "provisioning" in capsys.readouterr().err


def test_shell_refuses_a_deployment_that_is_gone(
    stub_api, cached_credential, no_ssh, capture_interactive, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    stub_api(Platform(deployment=None, keys=[key_entry()]))
    monkeypatch.chdir(tmp_path)

    assert main(["shell"]) == EXIT_ERROR
    assert not capture_interactive
    assert "no longer exists" in capsys.readouterr().err


def test_shell_refuses_when_no_key_is_registered(
    stub_api, cached_credential, no_ssh, capture_interactive, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path)
    stub_api(
        Platform(
            deployment={
                "id": DEPLOYMENT_ID,
                "name": DEPLOYMENT_NAME,
                "status": "ready",
            },
            keys=[],
        )
    )
    monkeypatch.chdir(tmp_path)

    assert main(["shell"]) == EXIT_ERROR
    assert not capture_interactive
    assert "freepod key add" in capsys.readouterr().err


def test_shell_outside_a_project_says_so(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["shell"]) == EXIT_USAGE
