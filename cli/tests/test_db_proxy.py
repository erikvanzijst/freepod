"""`freepod db proxy`: the forward it assembles, the port it binds, the URL it
prints, and the failures it explains first.

The tunnel itself cannot be exercised here — it holds a real port and a real
connection — so `ssh.run` is stubbed to capture the argv, and the forward is
asserted on its arguments. The port selection and the URL composition are pure
and are tested directly. Everything up to the ssh call, including the pre-flight
refusals, is real.
"""

from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
import pytest

from freepod import EXIT_ERROR, EXIT_OK, EXIT_USAGE, FreepodError
from freepod import keys as keys_module
from freepod.cli import (
    CONVENTIONAL_DB_PORT,
    _connection_url,
    _free_local_port,
    _port_available,
    choose_local_port,
    main,
)

from conftest import json_response

USER = {"id": 7, "email": "dev@example.com", "is_admin": False}
DEPLOYMENT_ID = "7214d804-7f9b-46d2-b1f4-1b911b8a339e"
DEPLOYMENT_NAME = "custom-user-app-2rakm1"
EDGE = {
    "host": "ssh.dev.freepod.eu",
    "port": 2222,
    "host_key": {"ssh-ed25519": "AAAAedgekey"},
}
# The pooler's in-cluster address, exactly as the database endpoint reports it
# and exactly as the chart renders into the forward allowlist.
DATABASE = {
    "host": "caelus-pooler.tenant-db.svc",
    "port": 6432,
    "database": "app",
    "role": "app",
    "password": "hexpassword123",
    "quota_state": "ok",
}


def project_at(tmp_path: Path, *, env="prod") -> Path:
    document = {
        "version": 1,
        "env": env,
        "deployment": {"id": DEPLOYMENT_ID, "name": DEPLOYMENT_NAME},
        "user_values": {"hostname": "dbprobe.dev.freepod.eu"},
    }
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
    """The reads `db proxy` performs: me, deployment, database, edge, keys."""

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
def capture_run(monkeypatch):
    """Record the argv `ssh.run` is handed and report a clean exit."""
    captured: dict = {}

    def run(args, **kwargs):
        captured.update(args=args, kwargs=kwargs)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("freepod.ssh.run", run)
    return captured


def _stub_platform(stub_api, *, database=DATABASE):
    stub_api(
        Platform(
            deployment={"id": DEPLOYMENT_ID, "name": DEPLOYMENT_NAME, "status": "ready"},
            database=database,
            keys=[key_entry()],
        )
    )


# --- 4.1 the forwarded address is the platform's, spelled the platform's way ---


def test_db_proxy_forwards_to_the_reported_destination_verbatim(
    stub_api, cached_credential, no_ssh, capture_run, tmp_path, monkeypatch
):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    _stub_platform(stub_api)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(["db", "proxy", "--port", "5432"])
    assert exc.value.code == EXIT_OK

    args = capture_run["args"]
    # A forward runs no session: -N, and the -L is the whole point.
    assert "-N" in args
    assert "-L" in args
    assert "-tt" not in args
    local_forward = args[args.index("-L") + 1]
    local_port, destination = local_forward.split(":", 1)
    assert local_port == "5432"
    # The destination is the reported host:port, byte for byte. That is the same
    # string the chart renders into PermitOpen, so the two readers agree.
    assert destination == f"{DATABASE['host']}:{DATABASE['port']}"
    # The edge, and the one key, as with every other connection.
    assert f"{DEPLOYMENT_ID}@{EDGE['host']}" in args
    assert args.count("-i") == 1


# --- 4.2 a local port is chosen when one is not given ---


def test_choose_local_port_uses_the_requested_port():
    port = _free_local_port()
    assert choose_local_port(port) == port


def test_choose_local_port_releases_the_port_it_checks():
    # The availability check binds the port only to test it; it is free after.
    port = _free_local_port()
    assert choose_local_port(port) == port
    assert _port_available(port)


def test_choose_local_port_refuses_an_unavailable_requested_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", CONVENTIONAL_DB_PORT))
        with pytest.raises(FreepodError) as exc:
            choose_local_port(CONVENTIONAL_DB_PORT)
    # Named specifically, not folded into a generic failure.
    assert str(CONVENTIONAL_DB_PORT) in str(exc.value)
    assert "--port" in str(exc.value)


def test_choose_local_port_prefers_the_conventional_port():
    if _port_available(CONVENTIONAL_DB_PORT):
        assert choose_local_port(None) == CONVENTIONAL_DB_PORT


def test_choose_local_port_falls_back_when_the_conventional_is_occupied():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", CONVENTIONAL_DB_PORT))
        chosen = choose_local_port(None)
    # An occupied default never fails the command; a free, different port is used.
    assert chosen != CONVENTIONAL_DB_PORT
    assert _port_available(chosen)


def test_db_proxy_reports_the_port_it_chose(
    stub_api, cached_credential, no_ssh, capture_run, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    _stub_platform(stub_api)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(["db", "proxy", "--port", "5432"])
    assert exc.value.code == EXIT_OK
    # The chosen port is named on stderr, and it is the one the forward binds.
    assert "localhost:5432" in capsys.readouterr().err
    local_forward = capture_run["args"][capture_run["args"].index("-L") + 1]
    assert local_forward.startswith("5432:")


# --- 4.3 the URL is composed for the local end, percent-encoded ---


def test_connection_url_percent_encodes_the_credential():
    # A password with characters that have meaning in a URL: the current
    # generator emits only hexadecimal, so this is constructed, not sampled.
    password = "p@ss:w/ord#1?x=&y"
    url = _connection_url(
        {"database": "app", "role": "app", "password": password}, "localhost", 5432
    )
    parsed = urlparse(url)
    assert parsed.scheme == "postgresql"
    assert parsed.hostname == "localhost"
    assert parsed.port == 5432
    assert parsed.username == "app"
    # Parsing the printed URL yields exactly the credential the platform reported.
    assert unquote(parsed.password) == password
    assert parsed.path == "/app"


def test_connection_url_addresses_the_local_end_not_the_pooler():
    url = _connection_url(DATABASE, "localhost", 5432)
    # The local end, not the in-cluster pooler the forward actually reaches.
    assert f"@localhost:5432/" in url
    assert DATABASE["host"] not in url


# --- 4.4 the URL goes to stdout and everything else to stderr ---


def test_db_proxy_prints_the_url_on_stdout_alone(
    stub_api, cached_credential, no_ssh, capture_run, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    _stub_platform(stub_api)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(["db", "proxy", "--port", "5432"])
    assert exc.value.code == EXIT_OK

    out = capsys.readouterr()
    lines = out.out.strip().splitlines()
    # Capturing stdout yields the URL and none of the client's narration.
    assert len(lines) == 1
    url = lines[0]
    assert url.startswith("postgresql://")
    assert "localhost:5432" in url
    assert "Forwarding" in out.err


# --- 4.5 the tunnel is held in the foreground and closed on interrupt ---


def test_db_proxy_closes_on_interrupt(
    stub_api, cached_credential, no_ssh, tmp_path, monkeypatch
):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    _stub_platform(stub_api)
    monkeypatch.chdir(tmp_path)

    def interrupt(args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("freepod.ssh.run", interrupt)

    # Interrupting the tunnel is how it ends: a clean exit, not a failure.
    with pytest.raises(SystemExit) as exc:
        main(["db", "proxy", "--port", "5432"])
    assert exc.value.code == EXIT_OK


# --- 4.6 a refused forward is explained as a destination not permitted ---


def test_db_proxy_explains_a_refused_forward(
    stub_api, cached_credential, no_ssh, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    _stub_platform(stub_api)
    monkeypatch.chdir(tmp_path)

    refused = subprocess.CompletedProcess(
        ["ssh"],
        255,
        stdout=b"",
        stderr=b"channel 2: open failed: administratively prohibited: open failed\n",
    )
    monkeypatch.setattr("freepod.ssh.run", lambda args, **kwargs: refused)

    assert main(["db", "proxy", "--port", "5432"]) == EXIT_ERROR
    err = capsys.readouterr().err
    # Named as a destination refusal, and said not to be an authentication failure.
    assert "refused to forward" in err
    assert "not an authentication problem" in err


def test_db_proxy_does_not_misread_an_auth_failure_as_a_refused_forward(
    stub_api, cached_credential, no_ssh, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    _stub_platform(stub_api)
    monkeypatch.chdir(tmp_path)

    # A uniform authentication refusal: no "administratively prohibited" anywhere.
    denied = subprocess.CompletedProcess(
        ["ssh"], 255, stdout=b"", stderr=b"Permission denied (publickey).\n"
    )
    monkeypatch.setattr("freepod.ssh.run", lambda args, **kwargs: denied)

    with pytest.raises(SystemExit) as exc:
        main(["db", "proxy", "--port", "5432"])
    # ssh's own exit code propagates; the client does not claim a cause it cannot
    # support, so this is not dressed up as a destination refusal.
    assert exc.value.code == 255
    err = capsys.readouterr().err
    assert "Permission denied" in err
    assert "refused to forward" not in err


# --- pre-flight refusals, as with every other connecting command ---


def test_db_proxy_refuses_a_deployment_without_a_database(
    stub_api, cached_credential, no_ssh, capture_run, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    stub_api(
        Platform(
            deployment={"id": DEPLOYMENT_ID, "name": DEPLOYMENT_NAME, "status": "ready"},
            database=None,
            keys=[key_entry()],
        )
    )
    monkeypatch.chdir(tmp_path)

    assert main(["db", "proxy", "--port", "5432"]) == EXIT_ERROR
    assert not capture_run  # no connection was attempted
    assert "no database" in capsys.readouterr().err


def test_db_proxy_refuses_a_deployment_that_is_not_settled(
    stub_api, cached_credential, no_ssh, capture_run, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    stub_api(
        Platform(
            deployment={"id": DEPLOYMENT_ID, "name": DEPLOYMENT_NAME, "status": "provisioning"},
            database=DATABASE,
            keys=[key_entry()],
        )
    )
    monkeypatch.chdir(tmp_path)

    assert main(["db", "proxy", "--port", "5432"]) == EXIT_ERROR
    assert not capture_run
    assert "provisioning" in capsys.readouterr().err


def test_db_proxy_outside_a_project_says_so(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["db", "proxy"]) == EXIT_USAGE
