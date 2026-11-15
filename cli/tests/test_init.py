"""`freepod init`: name, hostname, create, record the pointer (cli-init)."""

from __future__ import annotations

import json

import click
import httpx
import pytest

from freepod import EXIT_OK, EXIT_USAGE
from freepod.auth import store_refresh_token
from freepod.cli import main
from freepod.project import PROJECT_FILE

from conftest import json_response

ME = {"id": 7, "email": "erik@example.com", "is_admin": False}
DEV_SCHEMA = "https://dev.freepod.eu/api/products/custom/project-schema"

TEMPLATE = {
    "id": 49,
    "values_schema_json": {
        "type": "object",
        "properties": {
            "hostname": {
                "type": "string",
                "title": "hostname",
                "minLength": 1,
                "maxLength": 253,
                "description": "The fully qualified hostname for the app.",
            },
            "image": {"type": "string", "pattern": "^$|^[0-9]+@sha256:[a-f0-9]{64}$"},
            "auth": {"type": "object"},
        },
        "required": ["hostname"],
        "additionalProperties": False,
    },
}

CUSTOM_PRODUCT = {"id": 12, "slug": "custom", "name": "Custom user app", "template": TEMPLATE}
OTHER_PRODUCTS = [
    {"id": 2, "slug": "nextcloud", "name": "Nextcloud"},
    {"id": 1, "slug": None, "name": "Hello World"},
]
FREE_PLAN = {"id": 3, "name": "Free", "template": {"id": 30, "price_cents": 0}}


class Platform:
    """A scripted dev platform: products, plans, terms, handle, hostnames,
    deployments, and the creates it receives."""

    def __init__(self, *, products=None, verdicts=None, deployments=None, creates=None, tos=True):
        self.products = OTHER_PRODUCTS + [CUSTOM_PRODUCT] if products is None else products
        self.verdicts = dict(verdicts or {})
        self.deployments = list(deployments or [])
        # Answers to successive creates: a dict is a refusal, None a success.
        self.create_answers = list(creates or [])
        self.tos = tos
        self.created = []
        self.checked = []
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        if path == "/api/me":
            return json_response(200, ME)
        if path == "/api/products":
            return json_response(200, self.products)
        if path == "/api/products/12/plans":
            return json_response(200, [FREE_PLAN])
        if path == "/api/me/tos-acceptance":
            return json_response(
                200,
                {
                    "version": "2026-07-01" if self.tos else None,
                    "accepted_at": "2026-07-02T00:00:00Z" if self.tos else None,
                    "current_version": "2026-07-01",
                },
            )
        if path == "/api/me/handle":
            return json_response(
                200,
                {"handle": "erik", "suffix": "-erik.dev.freepod.app", "domain": "dev.freepod.app"},
            )
        if path.startswith("/api/hostnames/"):
            label = path.rsplit("/", 1)[-1]
            self.checked.append(label)
            reason = self.verdicts.get(label)
            return json_response(200, {"fqdn": label, "usable": reason is None, "reason": reason})
        if path == "/api/users/7/deployments" and method == "GET":
            return json_response(200, self.deployments)
        if path == "/api/users/7/deployments" and method == "POST":
            body = json.loads(request.content)
            self.created.append(body)
            refusal = self.create_answers.pop(0) if self.create_answers else None
            if refusal is not None:
                return json_response(409, refusal)
            host = body["user_values_json"]["hostname"]
            record = {
                "id": f"new-{len(self.created)}",
                "name": body["name"],
                "hostname": host if "." in host else f"{host}-erik.dev.freepod.app",
                "status": "provisioning",
            }
            return json_response(201, {"deployment": record})
        return json_response(404, {"detail": "Not Found"})


@pytest.fixture
def platform(monkeypatch):
    def install(**kwargs):
        scripted = Platform(**kwargs)

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


@pytest.fixture
def credential(monkeypatch):
    from freepod import auth

    store_refresh_token("dev", "freepod-cli-dev", "dev-refresh")
    monkeypatch.setattr(auth, "post_form", lambda url, fields, timeout=30: {"access_token": "at"})


@pytest.fixture
def answers(monkeypatch):
    """Script the answers; `None` accepts whatever the prompt offered.

    Returns `(label, offered)` for each prompt, in order. Running out of
    answers ends input, as a closed stdin would.
    """

    def install(*responses):
        queue = list(responses)
        offered = []

        def fake_prompt(text, default=None):
            if not queue:
                raise click.Abort()
            offered.append((text.strip(), default))
            answer = queue.pop(0)
            return default if answer is None else answer

        monkeypatch.setattr("freepod.values.prompt", fake_prompt)
        return offered

    return install


@pytest.fixture(autouse=True)
def in_tmp_dir(tmp_path, monkeypatch):
    project = tmp_path / "arkanoid"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


def saved(root):
    return json.loads((root / PROJECT_FILE).read_text())


def init(*args):
    return main(["--env", "dev", "init", *args])


# --------------------------------------------------------------------------
# Creating and recording
# --------------------------------------------------------------------------


def test_init_creates_the_deployment_and_records_only_the_pointer(
    platform, credential, answers, in_tmp_dir, capsys
):
    scripted = platform()
    answers(None, None)

    assert init() == EXIT_OK

    [body] = scripted.created
    assert body["name"] == "arkanoid"
    assert body["user_values_json"] == {"hostname": "arkanoid"}
    assert body["plan_template_id"] == 30
    assert "managed_fields" not in body and "image" not in body["user_values_json"]
    assert saved(in_tmp_dir) == {
        "$schema": DEV_SCHEMA,
        "version": 2,
        "env": "dev",
        "deployment": "new-1",
    }
    out, err = capsys.readouterr()
    assert out.strip() == str(in_tmp_dir / PROJECT_FILE)
    assert "https://arkanoid-erik.dev.freepod.app" in err
    assert "provisioned in the background" in err


def test_init_does_not_wait_for_provisioning(platform, credential, answers):
    scripted = platform()
    answers(None, None)

    assert init() == EXIT_OK

    reads_after_create = scripted.calls[
        scripted.calls.index(("POST", "/api/users/7/deployments")) + 1 :
    ]
    assert reads_after_create == []


def test_a_project_on_the_default_environment_names_none(platform, credential, answers, in_tmp_dir):
    store_refresh_token("prod", "freepod-cli-prod", "prod-refresh")
    platform()
    answers(None, None)

    assert main(["init"]) == EXIT_OK

    document = saved(in_tmp_dir)
    assert "env" not in document
    assert document["$schema"] == "https://freepod.eu/api/products/custom/project-schema"


def test_an_agent_initializes_without_any_prompt(platform, credential, answers, in_tmp_dir):
    scripted = platform()
    offered = answers()

    assert init("--name", "Arkanoid", "--hostname", "arkanoid") == EXIT_OK

    assert offered == []
    assert scripted.created[0]["name"] == "Arkanoid"
    assert scripted.created[0]["user_values_json"]["hostname"] == "arkanoid"


def test_a_missing_name_without_a_terminal_names_the_option(platform, credential, answers, capsys):
    scripted = platform()
    answers()

    assert init("--hostname", "arkanoid") == EXIT_USAGE

    assert "--name" in capsys.readouterr().err
    assert scripted.created == []


def test_terms_not_accepted_fail_before_anything_is_created(platform, credential, answers, capsys):
    scripted = platform(tos=False)
    answers(None, None)

    assert init() != EXIT_OK

    assert "terms" in capsys.readouterr().err
    assert scripted.created == []


def test_a_file_that_cannot_be_written_names_freepod_link(
    platform, credential, answers, monkeypatch, capsys
):
    platform()
    answers(None, None)

    def refuse(self):
        raise OSError("read-only file system")

    monkeypatch.setattr("freepod.project.Project.save", refuse)

    assert init() != EXIT_OK
    assert "freepod link arkanoid" in capsys.readouterr().err


# --------------------------------------------------------------------------
# The name
# --------------------------------------------------------------------------


def test_the_directory_name_is_offered_first(platform, credential, answers):
    platform()
    offered = answers(None, None)

    init()

    assert offered[0] == ("name", "arkanoid")


def test_a_taken_directory_name_is_made_unique(platform, credential, answers):
    scripted = platform(deployments=[{"id": "d1", "name": "Arkanoid", "status": "ready"}])
    offered = answers(None, None)

    init()

    assert offered[0] == ("name", "arkanoid 2")
    assert scripted.created[0]["name"] == "arkanoid 2"


def test_a_name_in_use_is_asked_again_before_the_hostname(platform, credential, answers, capsys):
    platform(
        deployments=[
            {"id": "d1", "name": "Pong", "hostname": "pong-erik.dev.freepod.app", "status": "ready"}
        ]
    )
    offered = answers("pong", "Breakout", None)

    assert init() == EXIT_OK

    assert [label for label, _ in offered] == ["name", "name", "hostname"]
    assert "already uses that name" in capsys.readouterr().err


def test_a_deleted_deployment_does_not_hold_its_name(platform, credential, answers):
    scripted = platform(deployments=[{"id": "d1", "name": "arkanoid", "status": "deleted"}])
    answers(None, None)

    init()

    assert scripted.created[0]["name"] == "arkanoid"


def test_a_taken_name_in_the_file_fails_before_anything_is_created(
    platform, credential, answers, in_tmp_dir, capsys
):
    (in_tmp_dir / PROJECT_FILE).write_text(json.dumps({"version": 2, "name": "Pong"}))
    scripted = platform(
        deployments=[
            {"id": "d1", "name": "pong", "hostname": "pong-erik.dev.freepod.app", "status": "ready"}
        ]
    )
    answers()

    assert init() != EXIT_OK

    err = capsys.readouterr().err
    assert "pong-erik.dev.freepod.app" in err
    assert scripted.created == []


def test_a_name_taken_in_between_is_asked_again(platform, credential, answers):
    scripted = platform(
        creates=[
            {"detail": "You already have a deployment named 'arkanoid'", "code": "name_in_use"}
        ]
    )
    offered = answers(None, None, "Arkanoid II")

    assert init() == EXIT_OK

    assert [label for label, _ in offered] == ["name", "hostname", "name"]
    assert [body["name"] for body in scripted.created] == ["arkanoid", "Arkanoid II"]


# --------------------------------------------------------------------------
# The hostname
# --------------------------------------------------------------------------


def test_the_name_is_offered_as_a_label(platform, credential, answers, tmp_path, monkeypatch):
    other = tmp_path / "My_App.v2"
    other.mkdir()
    monkeypatch.chdir(other)
    scripted = platform()
    offered = answers(None, None)

    init()

    assert offered[1] == ("hostname", "my-app-v2")
    assert scripted.created[0]["user_values_json"]["hostname"] == "my-app-v2"


def test_a_taken_label_is_made_unique(platform, credential, answers):
    platform(verdicts={"arkanoid": "in_use"})
    offered = answers(None, None)

    init()

    assert offered[1] == ("hostname", "arkanoid-2")


def test_no_label_is_offered_after_five_unusable_candidates(platform, credential, answers):
    taken = {"arkanoid": "in_use", **{f"arkanoid-{n}": "in_use" for n in range(2, 7)}}
    scripted = platform(verdicts=taken)
    offered = answers(None, "breakout")

    init()

    assert offered[1] == ("hostname", None)
    assert scripted.checked[:5] == [
        "arkanoid",
        "arkanoid-2",
        "arkanoid-3",
        "arkanoid-4",
        "arkanoid-5",
    ]


def test_an_unusable_hostname_is_asked_again_with_its_reason(platform, credential, answers, capsys):
    scripted = platform(verdicts={"admin": "reserved"})
    offered = answers(None, "admin", "breakout")

    assert init() == EXIT_OK

    assert offered[2] == ("hostname", None)
    assert "reserved" in capsys.readouterr().err
    assert scripted.created[0]["user_values_json"]["hostname"] == "breakout"


def test_a_hostname_taken_in_between_is_asked_again(platform, credential, answers, capsys):
    scripted = platform(creates=[{"detail": "in_use"}])
    offered = answers(None, None, "breakout")

    assert init() == EXIT_OK

    assert offered[2] == ("hostname", None)
    assert [b["user_values_json"]["hostname"] for b in scripted.created] == ["arkanoid", "breakout"]


def test_a_bare_label_is_shown_completed(platform, credential, answers, capsys):
    platform()
    answers(None, "Photos")

    init()

    assert "→ photos-erik.dev.freepod.app" in capsys.readouterr().err


def test_an_unusable_hostname_option_fails_without_a_terminal(
    platform, credential, answers, capsys
):
    scripted = platform(verdicts={"admin": "reserved"})
    answers()

    assert init("--name", "A", "--hostname", "admin") != EXIT_OK

    assert "reserved" in capsys.readouterr().err
    assert scripted.created == []


# --------------------------------------------------------------------------
# An existing project file
# --------------------------------------------------------------------------


def test_a_linked_project_is_protected(platform, credential, answers, in_tmp_dir, capsys):
    (in_tmp_dir / PROJECT_FILE).write_text(json.dumps({"version": 2, "deployment": "old-1"}))
    scripted = platform()
    answers()

    assert init() == EXIT_USAGE

    err = capsys.readouterr().err
    assert "old-1" in err and "--force" in err
    assert "freepod init" not in err
    assert scripted.created == []


def test_force_names_the_deployment_it_unlinks_and_keeps_the_files_keys(
    platform, credential, answers, in_tmp_dir, capsys
):
    (in_tmp_dir / PROJECT_FILE).write_text(
        json.dumps({"version": 2, "env": "dev", "deployment": "old-1", "auth": {"enabled": True}})
    )
    platform(deployments=[{"id": "old-1", "name": "Old arkanoid", "status": "ready"}])
    answers(None, None)

    assert init("--force") == EXIT_OK

    assert "'Old arkanoid'" in capsys.readouterr().err
    document = saved(in_tmp_dir)
    assert document["deployment"] == "new-1"
    assert document["auth"] == {"enabled": True}


def test_an_unlinked_files_keys_are_claimed_in_the_create(
    platform, credential, answers, in_tmp_dir
):
    (in_tmp_dir / PROJECT_FILE).write_text(
        json.dumps({"version": 2, "name": "Arkanoid", "auth": {"enabled": True}})
    )
    scripted = platform()
    offered = answers(None)

    assert init() == EXIT_OK

    assert [label for label, _ in offered] == ["hostname"]
    [body] = scripted.created
    assert body["name"] == "Arkanoid"
    assert body["user_values_json"]["auth"] == {"enabled": True}
    assert body["managed_fields"] == ["auth", "name"]
    document = saved(in_tmp_dir)
    assert document["name"] == "Arkanoid" and document["auth"] == {"enabled": True}


def test_a_hostname_the_file_holds_is_not_asked(platform, credential, answers, in_tmp_dir):
    (in_tmp_dir / PROJECT_FILE).write_text(json.dumps({"version": 2, "hostname": "breakout"}))
    scripted = platform()
    offered = answers(None)

    assert init() == EXIT_OK

    assert [label for label, _ in offered] == ["name"]
    assert scripted.created[0]["user_values_json"]["hostname"] == "breakout"
    assert scripted.created[0]["managed_fields"] == ["hostname"]


# --------------------------------------------------------------------------
# Product resolution and credentials
# --------------------------------------------------------------------------


def test_a_missing_custom_product_is_explained_in_the_users_terms(
    platform, credential, answers, capsys
):
    platform(products=OTHER_PRODUCTS)

    assert init() != EXIT_OK

    stderr = capsys.readouterr().err
    assert "does not offer user-supplied application deployments" in stderr
    assert "KeyError" not in stderr


def test_the_product_is_resolved_by_slug_not_by_name(platform, credential, answers):
    platform(products=[{"id": 9, "slug": "something-else", "name": "Custom user app"}])
    assert init() != EXIT_OK


def test_init_without_a_credential_exits_three(platform, answers, capsys):
    from freepod import EXIT_NOT_AUTHENTICATED

    platform()
    assert init() == EXIT_NOT_AUTHENTICATED
    assert "not authenticated" in capsys.readouterr().err


def test_init_checks_the_identity_before_reading_public_data(platform, credential, answers):
    scripted = platform()
    answers(None, None)

    init()

    assert scripted.calls[0] == ("GET", "/api/me")
