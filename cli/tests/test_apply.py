"""`freepod apply` and `deploy --no-build` (cli-apply), and link's no-op round trip."""

from __future__ import annotations

import copy
import json

import httpx
import pytest

from freepod import EXIT_OK
from freepod.auth import store_refresh_token
from freepod.cli import main
from freepod.project import PROJECT_FILE

from conftest import json_response

IMAGE = "7@sha256:" + "a" * 64


def stored_deployment(**overrides):
    record = {
        "id": "d-ark",
        "name": "arkanoid",
        "description": "Bricks",
        "hostname": "arkanoid-erik.dev.freepod.app",
        "status": "ready",
        "generation": 3,
        "pending": False,
        "managed_fields": [],
        "user_values_json": {
            "hostname": "arkanoid",
            "image": IMAGE,
            "auth": {"enabled": True, "access": "listed"},
        },
        "applied_release": {"build_id": "b-1", "values_json": {"image": IMAGE}},
    }
    record.update(overrides)
    return record


class Platform:
    """One deployment that answers reads and updates as the server's release
    rule does: chart values or a named build release, anything else does not."""

    def __init__(self, record):
        self.record = record
        self.updates = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if path == "/api/me":
            return json_response(200, {"id": 7, "email": "erik@example.com"})
        if path == "/api/users/7/deployments" and method == "GET":
            return json_response(200, [self.record])
        if path == "/api/users/7/deployments/d-ark" and method == "GET":
            return json_response(200, self.record)
        if path == "/api/users/7/deployments/d-ark" and method == "PUT":
            body = json.loads(request.content)
            self.updates.append(body)
            releases = (
                body.get("user_values_json", self.record["user_values_json"])
                != self.record["user_values_json"]
                or "build_id" in body
            )
            updated = copy.deepcopy(self.record)
            updated["user_values_json"] = body.get("user_values_json", updated["user_values_json"])
            for key in ("name", "description"):
                if key in body:
                    updated[key] = body[key]
            if "managed_fields" in body:
                updated["managed_fields"] = body["managed_fields"]
            if releases:
                updated["generation"] += 1
                updated["pending"] = False
            self.record = updated
            return json_response(200, updated)
        return json_response(404, {"detail": "Not Found"})


@pytest.fixture
def platform(monkeypatch, tmp_path):
    from freepod import auth

    store_refresh_token("dev", "freepod-cli-dev", "dev-refresh")
    monkeypatch.setattr(auth, "post_form", lambda url, fields, timeout=30: {"access_token": "at"})
    monkeypatch.chdir(tmp_path)

    def install(record=None):
        scripted = Platform(record or stored_deployment())

        from freepod.api import ApiClient
        from freepod.cli import Context

        def client(self, session):
            return ApiClient(
                self.env,
                session,
                client=httpx.Client(transport=httpx.MockTransport(scripted)),
                backoff_base=0,
            )

        monkeypatch.setattr(Context, "client", client)
        return scripted

    return install


def write(tmp_path, **fields):
    document = {"version": 2, "env": "dev", "deployment": "d-ark", **fields}
    (tmp_path / PROJECT_FILE).write_text(json.dumps(document))


def apply(*args):
    return main(["--env", "dev", "apply", *args])


def test_a_rename_is_one_update_with_no_release(platform, tmp_path, capsys):
    scripted = platform()
    write(tmp_path, name="Arkanoid")

    assert apply() == EXIT_OK

    [body] = scripted.updates
    assert body["name"] == "Arkanoid"
    assert body["managed_fields"] == ["name"]
    assert body["user_values_json"] == stored_deployment()["user_values_json"]
    assert "build_id" not in body and "desired_template_id" not in body
    assert scripted.record["generation"] == 3
    assert 'name: "arkanoid" → "Arkanoid"' in capsys.readouterr().err


def test_a_nested_object_is_replaced_whole(platform, tmp_path, capsys):
    scripted = platform()
    write(tmp_path, auth={"enabled": True})

    assert apply() == EXIT_OK

    assert scripted.updates[0]["user_values_json"]["auth"] == {"enabled": True}
    assert scripted.updates[0]["user_values_json"]["image"] == IMAGE
    assert scripted.record["generation"] == 4


def test_a_key_removed_from_the_file_is_given_up(platform, tmp_path, capsys):
    scripted = platform(stored_deployment(managed_fields=["auth", "name"], name="Arkanoid"))
    write(tmp_path, name="Arkanoid")

    assert apply() == EXIT_OK

    assert scripted.updates[0]["managed_fields"] == ["name"]
    assert "No longer managed by .freepod.json: auth" in capsys.readouterr().err


def test_nothing_changed_is_said(platform, tmp_path, capsys):
    platform(stored_deployment(managed_fields=["name"]))
    write(tmp_path, name="arkanoid")

    assert apply() == EXIT_OK

    assert "Nothing changed." in capsys.readouterr().err


def test_a_multiline_value_is_reported_as_changed_only(platform, tmp_path, capsys):
    platform()
    write(tmp_path, description="Bricks\nand a paddle")

    apply()

    assert "description: changed" in capsys.readouterr().err


def test_the_icon_is_sent_as_base64_and_not_reported(platform, tmp_path, capsys):
    scripted = platform()
    (tmp_path / "icon.png").write_bytes(b"\x89PNG fake")
    write(tmp_path, icon="icon.png")

    assert apply() == EXIT_OK

    assert scripted.updates[0]["icon"] == "iVBORyBmYWtl"
    assert scripted.updates[0]["managed_fields"] == ["icon"]
    assert "icon" not in capsys.readouterr().err


def test_a_null_icon_clears_it(platform, tmp_path):
    scripted = platform()
    write(tmp_path, icon=None)

    apply()

    assert scripted.updates[0]["icon"] is None


def test_a_missing_icon_fails_before_anything_is_sent(platform, tmp_path, capsys):
    scripted = platform()
    write(tmp_path, icon="missing.png")

    assert apply() != EXIT_OK

    assert "missing.png" in capsys.readouterr().err
    assert scripted.updates == []


def test_an_oversized_icon_fails_naming_the_limit(platform, tmp_path, capsys):
    scripted = platform()
    (tmp_path / "big.png").write_bytes(b"x" * (2 * 1024 * 1024))
    write(tmp_path, icon="big.png")

    assert apply() != EXIT_OK

    assert "256 KiB" in capsys.readouterr().err
    assert scripted.updates == []


def test_an_image_in_the_file_is_refused_and_nothing_sent(platform, tmp_path, capsys):
    scripted = platform()
    write(tmp_path, image=IMAGE)

    assert apply() != EXIT_OK

    assert "'image' is a build output" in capsys.readouterr().err
    assert scripted.updates == []


def test_an_unlinked_project_names_init_and_link(platform, tmp_path, capsys):
    platform()
    (tmp_path / PROJECT_FILE).write_text(json.dumps({"version": 2, "env": "dev", "name": "A"}))

    assert apply() != EXIT_OK

    err = capsys.readouterr().err
    assert "freepod init" in err and "freepod link" in err


def test_staged_vars_are_rolled_out_by_naming_the_running_build(platform, tmp_path, capsys):
    scripted = platform(stored_deployment(pending=True))
    write(tmp_path)

    assert apply() == EXIT_OK

    assert scripted.updates[0]["build_id"] == "b-1"
    assert scripted.record["generation"] == 4


def test_staged_vars_without_a_build_wait_for_the_next_deploy(platform, tmp_path, capsys):
    scripted = platform(stored_deployment(pending=True, applied_release=None))
    write(tmp_path)

    assert apply() == EXIT_OK

    assert "build_id" not in scripted.updates[0]
    assert "next `freepod deploy`" in capsys.readouterr().err


def test_deploy_no_build_is_apply(platform, tmp_path):
    scripted = platform()
    write(tmp_path, name="Arkanoid")

    assert main(["--env", "dev", "deploy", "--no-build"]) == EXIT_OK

    assert scripted.updates[0]["name"] == "Arkanoid"


def test_a_recovered_file_applies_as_a_no_op(platform, tmp_path, capsys):
    """Link writes the deployment's managed fields back, so the next apply claims
    them again and changes nothing (cli-link)."""
    scripted = platform(stored_deployment(managed_fields=["name", "auth"], name="Arkanoid"))

    assert main(["--env", "dev", "link", "arkanoid"]) == EXIT_OK
    capsys.readouterr()
    assert apply() == EXIT_OK

    [body] = scripted.updates
    assert body["managed_fields"] == ["auth", "name"]
    assert scripted.record["generation"] == 3
    assert "Nothing changed." in capsys.readouterr().err
