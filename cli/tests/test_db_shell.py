"""`freepod db shell`: the psql argv it assembles, and its refusals first.

The session runs server-side (the sidecar's own client), so nothing local is
required — here `run_interactive` is stubbed to capture the argv, and the
connection is asserted on its arguments. Everything up to that call, including
the database and pre-flight refusals, is real.
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
DATABASE = {"database": "app", "role": "app", "quota_state": "ok"}


def project_at(tmp_path: Path, *, env="prod") -> Path:
    document = {"version": 2, "env": env, "deployment": DEPLOYMENT_ID, "hostname": "dbprobe"}
    (tmp_path / ".freepod.json").write_text(json.dumps(document), encoding="utf-8")
    return tmp_path


def key_entry() -> dict:
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
    """The reads `db shell` performs: me, deployment, database, edge, keys."""

    def __init__(self, *, deployment=None, database=None, keys=None):
        self.deployment = deployment
        self.database = database
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
        if path == f"/api/users/7/deployments/{DEPLOYMENT_ID}/database":
            if self.database is None:
                return json_response(
                    404, {"detail": "no database", "code": "relational_storage_unavailable"}
                )
            return json_response(200, self.database)
        if path == "/api/users/7/ssh-keys":
            return json_response(200, self.keys)
        if path == "/api/ssh":
            return json_response(200, EDGE)
        return json_response(404, {"detail": f"no route for {path}"})


@pytest.fixture
def no_ssh(monkeypatch):
    monkeypatch.setattr("freepod.ssh.require_ssh", lambda: "/usr/bin/ssh")


@pytest.fixture
def capture_interactive(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        "freepod.ssh.run_interactive", lambda args: captured.update(args=args) or 0
    )
    return captured


def test_db_shell_assembles_psql_and_a_tty(
    stub_api, cached_credential, no_ssh, capture_interactive, tmp_path, monkeypatch
):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    stub_api(
        Platform(
            deployment={"id": DEPLOYMENT_ID, "name": DEPLOYMENT_NAME, "status": "ready"},
            database=DATABASE,
            keys=[key_entry()],
        )
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(["db", "shell"])
    assert exc.value.code == EXIT_OK

    args = capture_interactive["args"]
    # psql runs server-side, appended as the session's command, under a forced tty.
    assert "-tt" in args
    assert args[-1] == "psql"
    assert f"{DEPLOYMENT_ID}@{EDGE['host']}" in args
    # Exactly one identity, the private half of the key this machine holds.
    assert args.count("-i") == 1
    assert args[args.index("-i") + 1] == str(keys_module.generated_key_path())
    # The edge, pinned to the published key.
    assert args[args.index("-p") + 1] == str(EDGE["port"])
    assert any(a.startswith("UserKnownHostsFile=") for a in args)
    assert "StrictHostKeyChecking=yes" in args


def test_db_shell_refuses_a_deployment_without_a_database(
    stub_api, cached_credential, no_ssh, capture_interactive, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path)
    stub_api(
        Platform(
            deployment={"id": DEPLOYMENT_ID, "name": DEPLOYMENT_NAME, "status": "ready"},
            database=None,
            keys=[],
        )
    )
    monkeypatch.chdir(tmp_path)

    assert main(["db", "shell"]) == EXIT_ERROR
    assert not capture_interactive  # no connection was attempted
    assert "no database" in capsys.readouterr().err


def test_db_shell_refuses_a_deployment_that_is_not_settled(
    stub_api, cached_credential, no_ssh, capture_interactive, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path)
    stub_api(
        Platform(
            deployment={"id": DEPLOYMENT_ID, "name": DEPLOYMENT_NAME, "status": "provisioning"},
            database=DATABASE,
            keys=[],
        )
    )
    monkeypatch.chdir(tmp_path)

    assert main(["db", "shell"]) == EXIT_ERROR
    assert not capture_interactive
    assert "provisioning" in capsys.readouterr().err


def test_db_shell_refuses_when_no_key_is_registered(
    stub_api, cached_credential, no_ssh, capture_interactive, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path)
    stub_api(
        Platform(
            deployment={"id": DEPLOYMENT_ID, "name": DEPLOYMENT_NAME, "status": "ready"},
            database=DATABASE,
            keys=[],
        )
    )
    monkeypatch.chdir(tmp_path)

    assert main(["db", "shell"]) == EXIT_ERROR
    assert not capture_interactive
    assert "freepod key add" in capsys.readouterr().err


def test_db_shell_outside_a_project_says_so(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["db", "shell"]) == EXIT_USAGE
