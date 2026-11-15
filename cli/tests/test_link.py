"""`freepod link`: record an existing deployment (cli-link)."""

from __future__ import annotations

import json

import httpx
import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from freepod import EXIT_OK, EXIT_USAGE
from freepod.auth import store_refresh_token
from freepod.cli import main
from freepod.link import pick_deployment
from freepod.project import PROJECT_FILE

from conftest import json_response

DEV_SCHEMA = "https://dev.freepod.eu/api/products/custom/project-schema"


def deployment(id_, name, hostname, **extra):
    record = {
        "id": id_,
        "name": name,
        "hostname": hostname,
        "status": "ready",
        "description": None,
        "managed_fields": [],
        "user_values_json": {"hostname": hostname},
        "desired_template": {"product": {"name": "Custom user app"}},
    }
    record.update(extra)
    return record


ARKANOID = deployment(
    "d-ark",
    "Arkanoid",
    "arkanoid-erik.dev.freepod.app",
    description="Bricks",
    managed_fields=["name", "auth", "icon"],
    user_values_json={"hostname": "arkanoid", "auth": {"enabled": True}},
)
PONG = deployment("d-pong", "Pong", "pong-erik.dev.freepod.app")


@pytest.fixture
def platform(monkeypatch):
    def install(deployments=(ARKANOID, PONG)):
        records = {d["id"]: d for d in deployments}
        writes = []

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if request.method != "GET":
                writes.append((request.method, path))
                return json_response(405, {})
            if path == "/api/me":
                return json_response(200, {"id": 7, "email": "erik@example.com"})
            if path == "/api/users/7/deployments":
                return json_response(200, list(records.values()))
            if path.startswith("/api/users/7/deployments/"):
                record = records.get(path.rsplit("/", 1)[-1])
                return json_response(200, record) if record else json_response(404, {})
            return json_response(404, {"detail": "Not Found"})

        from freepod.api import ApiClient
        from freepod.cli import Context

        def client(self, session):
            return ApiClient(
                self.env,
                session,
                client=httpx.Client(transport=httpx.MockTransport(handler)),
                backoff_base=0,
            )

        monkeypatch.setattr(Context, "client", client)
        return writes

    return install


@pytest.fixture(autouse=True)
def credential(monkeypatch, tmp_path):
    from freepod import auth

    store_refresh_token("dev", "freepod-cli-dev", "dev-refresh")
    monkeypatch.setattr(auth, "post_form", lambda url, fields, timeout=30: {"access_token": "at"})
    monkeypatch.chdir(tmp_path)


def saved(root):
    return json.loads((root / PROJECT_FILE).read_text())


def link(*args):
    return main(["--env", "dev", "link", *args])


def test_linking_by_name_recreates_the_managed_fields_but_the_icon(platform, tmp_path, capsys):
    writes = platform()

    assert link("arkanoid") == EXIT_OK

    assert saved(tmp_path) == {
        "$schema": DEV_SCHEMA,
        "version": 2,
        "env": "dev",
        "deployment": "d-ark",
        "name": "Arkanoid",
        "auth": {"enabled": True},
    }
    assert "Add `icon` back" in capsys.readouterr().err
    assert writes == []


def test_linking_by_id(platform, tmp_path):
    platform()
    assert link("d-pong") == EXIT_OK
    assert saved(tmp_path)["deployment"] == "d-pong"


def test_no_such_deployment_writes_nothing_and_names_init(platform, tmp_path, capsys):
    platform()

    assert link("breakout") != EXIT_OK

    assert "freepod init" in capsys.readouterr().err
    assert not (tmp_path / PROJECT_FILE).exists()


def test_no_deployments_at_all_names_init(platform, capsys):
    platform(deployments=())
    assert link("arkanoid") != EXIT_OK
    assert "freepod init" in capsys.readouterr().err


def test_an_agent_without_a_terminal_must_name_the_deployment(platform, tmp_path, capsys):
    platform()

    assert link() == EXIT_USAGE

    assert "freepod link <name-or-id>" in capsys.readouterr().err
    assert not (tmp_path / PROJECT_FILE).exists()


def test_a_linked_project_is_not_silently_relinked(platform, tmp_path, capsys):
    platform()
    (tmp_path / PROJECT_FILE).write_text(
        json.dumps({"version": 2, "env": "dev", "deployment": "d-pong"})
    )

    assert link("arkanoid") == EXIT_USAGE

    assert "--force" in capsys.readouterr().err
    assert saved(tmp_path)["deployment"] == "d-pong"


def test_force_names_the_deployment_it_stops_pointing_at(platform, tmp_path, capsys):
    platform()
    (tmp_path / PROJECT_FILE).write_text(
        json.dumps({"version": 2, "env": "dev", "deployment": "d-pong"})
    )

    assert link("--force", "arkanoid") == EXIT_OK

    assert "No longer pointing at deployment 'Pong'" in capsys.readouterr().err
    assert saved(tmp_path)["deployment"] == "d-ark"


def test_an_existing_file_keeps_its_keys_and_reports_differences(platform, tmp_path, capsys):
    writes = platform()
    (tmp_path / PROJECT_FILE).write_text(
        json.dumps({"version": 2, "description": "Paddles", "name": "Arkanoid"})
    )

    assert link("arkanoid") == EXIT_OK

    document = saved(tmp_path)
    assert document["description"] == "Paddles"
    err = capsys.readouterr().err
    assert "differs from the deployment in: description" in err
    assert "freepod apply" in err
    assert "auth" in err and "gives" in err
    assert writes == []


# --------------------------------------------------------------------------
# The picker
# --------------------------------------------------------------------------


def pick(keys):
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        return pick_deployment([ARKANOID, PONG], input=pipe, output=DummyOutput())


def test_typing_narrows_and_enter_picks():
    assert pick("pon\r")["id"] == "d-pong"


def test_arrows_move_through_the_list():
    assert pick("\x1b[B\r")["id"] == "d-pong"
    assert pick("\x1b[B\x1b[A\r")["id"] == "d-ark"


def test_escape_gives_up():
    assert pick("\x1b") is None


def test_enter_with_no_match_picks_nothing_until_the_filter_matches():
    assert pick("zzz\r\x7f\x7f\x7fark\r")["id"] == "d-ark"
