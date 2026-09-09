from __future__ import annotations

import json

import httpx
import pytest

from freepod import EXIT_OK, EXIT_USAGE
from freepod.auth import store_refresh_token
from freepod.cli import main
from freepod.project import PROJECT_FILE, load

from conftest import json_response

ME = {"id": 7, "email": "erik@example.com", "is_admin": False}

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


@pytest.fixture
def dev_api(monkeypatch):
    """Route the command's API client at a scripted dev-shaped platform."""

    def install(*, products=None, hostname_verdicts=None, account=None):
        products = OTHER_PRODUCTS + [CUSTOM_PRODUCT] if products is None else products
        verdicts = list(hostname_verdicts) if hostname_verdicts else None
        state = {"writes": []}

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if request.method != "GET":
                state["writes"].append((request.method, path))
                return json_response(201, {})
            if path == "/api/me":
                return json_response(200, ME)
            if path == "/api/products":
                return json_response(200, products)
            if path == "/api/me/subdomain":
                return json_response(
                    200,
                    account
                    if account is not None
                    else {
                        "subdomain": "erik",
                        "fqdn": "erik.dev.freepod.eu",
                        "domain": "dev.freepod.eu",
                    },
                )
            if path.startswith("/api/hostnames/"):
                fqdn = path.rsplit("/", 1)[-1]
                reason = verdicts.pop(0) if verdicts else None
                return json_response(
                    200, {"fqdn": fqdn, "usable": reason is None, "reason": reason}
                )
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
        return state

    return install


@pytest.fixture
def credential(monkeypatch):
    from freepod import auth

    store_refresh_token("dev", "freepod-cli-dev", "dev-refresh")
    monkeypatch.setattr(
        auth, "post_form", lambda url, fields, timeout=30: {"access_token": "at"}
    )


@pytest.fixture
def answers(monkeypatch):
    def install(*responses):
        queue = list(responses)

        def fake_prompt(text, default=None, err=False, **kwargs):
            if not queue:
                raise AssertionError(f"unexpected prompt: {text}")
            return queue.pop(0)

        monkeypatch.setattr("freepod.values.click.prompt", fake_prompt)
        return queue

    return install


@pytest.fixture(autouse=True)
def in_tmp_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --------------------------------------------------------------------------
# Product resolution (task 7.1)
# --------------------------------------------------------------------------


def test_init_writes_the_project_file(dev_api, credential, answers, in_tmp_dir, capsys):
    dev_api()
    answers("myapp")

    assert main(["--env", "dev", "init"]) == EXIT_OK

    project = load(in_tmp_dir)
    assert project.env == "dev"
    assert project.user_values == {"hostname": "myapp.erik.dev.freepod.eu"}
    assert project.deployment is None
    capsys.readouterr()


def test_a_missing_custom_product_is_explained_in_the_users_terms(
    dev_api, credential, answers, capsys
):
    dev_api(products=OTHER_PRODUCTS)

    assert main(["--env", "dev", "init"]) != EXIT_OK

    stderr = capsys.readouterr().err
    assert "does not offer user-supplied application deployments" in stderr
    # Not a lookup failure, not a stack trace.
    assert "KeyError" not in stderr and "None" not in stderr


def test_the_product_is_resolved_by_slug_not_by_name(dev_api, credential, answers, in_tmp_dir):
    """A product named 'Custom user app' but slugged otherwise must not match."""
    dev_api(products=[{"id": 9, "slug": "something-else", "name": "Custom user app"}])
    assert main(["--env", "dev", "init"]) != EXIT_OK


def test_a_product_with_a_null_slug_is_not_matched(dev_api, credential, capsys):
    dev_api(products=[{"id": 1, "slug": None, "name": "Hello World"}])
    assert main(["--env", "dev", "init"]) != EXIT_OK
    capsys.readouterr()


# --------------------------------------------------------------------------
# Schema-driven prompting (task 7.2)
# --------------------------------------------------------------------------


def test_the_hostname_is_completed_and_shown(dev_api, credential, answers, in_tmp_dir, capsys):
    dev_api()
    answers("myapp")
    main(["--env", "dev", "init"])

    assert load(in_tmp_dir).hostname == "myapp.erik.dev.freepod.eu"
    assert "myapp.erik.dev.freepod.eu" in capsys.readouterr().err


def test_an_unusable_hostname_re_prompts(dev_api, credential, answers, in_tmp_dir, capsys):
    dev_api(hostname_verdicts=["in_use", None])
    answers("taken", "free")

    assert main(["--env", "dev", "init"]) == EXIT_OK

    assert load(in_tmp_dir).hostname == "free.erik.dev.freepod.eu"
    assert "already taken" in capsys.readouterr().err


def test_the_optional_image_property_is_not_written(dev_api, credential, answers, in_tmp_dir):
    dev_api()
    answers("myapp")
    main(["--env", "dev", "init"])

    assert "image" not in load(in_tmp_dir).user_values


# --------------------------------------------------------------------------
# No server-side writes (task 7.3)
# --------------------------------------------------------------------------


def test_init_creates_no_resource(dev_api, credential, answers, capsys):
    state = dev_api()
    answers("myapp")

    main(["--env", "dev", "init"])

    assert state["writes"] == [], "init must perform reads only"
    capsys.readouterr()


def test_a_failed_file_write_leaves_nothing_behind(
    dev_api, credential, answers, in_tmp_dir, monkeypatch, capsys
):
    state = dev_api()
    answers("myapp")

    def refuse(self):
        raise OSError("disk full")

    monkeypatch.setattr("freepod.project.Project.save", refuse)

    assert main(["--env", "dev", "init"]) != EXIT_OK
    assert not (in_tmp_dir / PROJECT_FILE).exists()
    assert state["writes"] == []
    capsys.readouterr()


# --------------------------------------------------------------------------
# Overwrite protection (task 7.4)
# --------------------------------------------------------------------------


def test_an_existing_project_file_is_protected(dev_api, credential, in_tmp_dir, capsys):
    (in_tmp_dir / PROJECT_FILE).write_text(
        json.dumps({"version": 1, "env": "dev", "user_values": {"hostname": "old.dev.freepod.eu"}}),
        encoding="utf-8",
    )

    assert main(["--env", "dev", "init"]) == EXIT_USAGE

    stderr = capsys.readouterr().err
    assert "--force" in stderr
    assert load(in_tmp_dir).hostname == "old.dev.freepod.eu", "the file must be untouched"


def test_force_warns_that_it_discards_the_deployment_pointer(
    dev_api, credential, answers, in_tmp_dir, capsys
):
    (in_tmp_dir / PROJECT_FILE).write_text(
        json.dumps(
            {
                "version": 1,
                "env": "dev",
                "deployment": {"id": "abc", "name": "custom-old99"},
                "user_values": {"hostname": "old.dev.freepod.eu"},
            }
        ),
        encoding="utf-8",
    )
    dev_api()
    answers("fresh")

    assert main(["--env", "dev", "init", "--force"]) == EXIT_OK

    stderr = capsys.readouterr().err
    assert "custom-old99" in stderr
    assert "discards" in stderr

    project = load(in_tmp_dir)
    assert project.deployment is None, "--force discards the whole file, pointer included"
    assert project.hostname == "fresh.erik.dev.freepod.eu"


def test_the_protection_message_does_not_recommend_init_for_a_missing_value(
    dev_api, credential, in_tmp_dir, capsys
):
    """init must never be presented as the remedy for a missing value."""
    (in_tmp_dir / PROJECT_FILE).write_text(
        json.dumps({"version": 1, "env": "dev", "user_values": {}}), encoding="utf-8"
    )
    main(["--env", "dev", "init"])

    stderr = capsys.readouterr().err
    assert "freepod deploy" in stderr


# --------------------------------------------------------------------------
# Credential handling
# --------------------------------------------------------------------------


def test_init_without_a_credential_exits_three(dev_api, answers, capsys):
    from freepod import EXIT_NOT_AUTHENTICATED

    dev_api()
    assert main(["--env", "dev", "init"]) == EXIT_NOT_AUTHENTICATED
    assert "not authenticated" in capsys.readouterr().err


def test_init_checks_the_identity_before_reading_public_data(
    dev_api, credential, answers, monkeypatch, capsys
):
    """`/api/me` first, or a bad credential surfaces as an unrelated failure."""
    dev_api()
    answers("myapp")

    seen = []
    from freepod.api import ApiClient

    original = ApiClient.get_json
    monkeypatch.setattr(
        ApiClient,
        "get_json",
        lambda self, path, **kwargs: (seen.append(path), original(self, path, **kwargs))[1],
    )

    main(["--env", "dev", "init"])

    assert seen[0] == "/api/me", f"public reads happened first: {seen}"
    capsys.readouterr()
