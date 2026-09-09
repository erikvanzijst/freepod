"""`freepod var`: reading, writing, staging, and what rolls the deployment."""

from __future__ import annotations

import json
import re

import httpx
import pytest

from freepod import EXIT_ERROR, EXIT_OK, EXIT_USAGE, UsageError
from freepod.cli import main
from freepod.vars import (
    HIDDEN,
    load_entries,
    mark_sensitive,
    parse_assignments,
    render_table,
)

from conftest import json_response
from test_deploy import deployment, plan, product, project_at

DEPLOYMENT_ID = "40bd8dea-0000-4000-8000-000000000001"
POINTER = {"id": DEPLOYMENT_ID, "name": "custom-d8dtx4"}
IMAGE = "7@sha256:" + "a" * 64
SECRET = "hunter2-swordfish"


def entry(value=None, sensitive=False, updated_at="2026-08-20T09:12:44"):
    """One var as the platform reports it. A secret carries no value."""
    body = {
        "sensitive": sensitive,
        "updated_at": updated_at,
        "updated_by": {"id": 7, "email": "dev@example.com"},
    }
    if not sensitive:
        body["value"] = value
    return body


def deployment_with(vars_=None, *, pending=False, status="ready", applied_number=1):
    record = deployment(status=status)
    record["vars"] = vars_ if vars_ is not None else {}
    record["pending"] = pending
    record["applied_release"] = {
        "id": "r-1",
        "number": applied_number,
        "build_id": "b-1",
        "values_json": {"hostname": "myapp.freepod.eu", "image": IMAGE},
    }
    return record


class VarPlatform:
    """A platform that serves one deployment's vars and records the writes."""

    def __init__(self, *, vars_=None, pending=False, status="ready", write_status=200,
                 write_detail=None, release_vars=None):
        self.vars = dict(vars_ or {})
        self.pending = pending
        self.status = status
        self.write_status = write_status
        self.write_detail = write_detail
        self.release_vars = release_vars if release_vars is not None else {}
        self.writes = []
        self.updates = []
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append((method, path))

        if path == "/api/me":
            return json_response(200, {"id": 7, "email": "dev@example.com"})
        if path == "/api/products":
            return json_response(200, [product()])
        if re.fullmatch(r"/api/products/\d+/plans", path):
            return json_response(200, [plan()])
        if path == "/api/me/subdomain":
            return json_response(
                200, {"subdomain": "dev", "fqdn": "dev.freepod.eu", "domain": "freepod.eu"}
            )
        if path.startswith("/api/hostnames/"):
            fqdn = path.rsplit("/", 1)[-1]
            return json_response(200, {"fqdn": fqdn, "usable": True, "reason": None})

        if re.fullmatch(r"/api/users/7/deployments/[^/]+/vars/runtime", path):
            if method == "PATCH":
                body = json.loads(request.content)
                self.writes.append(body["vars"])
                if self.write_detail is not None:
                    return json_response(self.write_status, {"detail": self.write_detail})
                self._apply(body["vars"])
                return json_response(200, self._payload())
            return json_response(200, self._payload())

        if re.fullmatch(r"/api/users/7/deployments/[^/]+/vars/runtime/[^/]+", path):
            key = path.rsplit("/", 1)[-1]
            self.vars.pop(key, None)
            self.pending = True
            return httpx.Response(204)

        if re.fullmatch(r"/api/users/7/deployments/[^/]+/releases/\d+", path):
            return json_response(200, {"number": 1, "vars": self.release_vars})

        if re.fullmatch(r"/api/users/7/deployments/[^/]+", path):
            if method == "PUT":
                self.updates.append(json.loads(request.content))
                self.pending = False
                return json_response(200, deployment_with(self.vars, status="ready"))
            return json_response(
                200, deployment_with(self.vars, pending=self.pending, status=self.status)
            )

        return json_response(404, {"detail": f"unrouted {method} {path}"})

    def _apply(self, entries):
        for key, body in entries.items():
            if body.get("value") is None and "value" in body:
                self.vars.pop(key, None)
            elif "value" in body:
                self.vars[key] = entry(body["value"], bool(body.get("sensitive")))
        self.pending = True

    def _payload(self):
        return {"vars": self.vars, "pending": self.pending}


@pytest.fixture
def run_var(monkeypatch, tmp_path):
    """Drive `main(['var', ...])` against a scripted platform in `tmp_path`."""

    def go(platform, argv, *, stdin=None, isatty=False):
        project_at(tmp_path, pointer=POINTER)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "freepod.cli.Context.session", lambda self, force_flow=None: _StubSession()
        )
        monkeypatch.setattr(
            "freepod.cli.Context.client",
            lambda self, session: httpx_client(platform),
        )
        monkeypatch.setattr("sys.stdin.isatty", lambda: isatty)
        if stdin is not None:
            monkeypatch.setattr("sys.stdin.read", lambda: stdin)
        return main(argv)

    return go


class _StubSession:
    access_token = "token"

    def authenticate(self, force_login: bool = False, interactive: bool = True) -> None:
        return None


def httpx_client(platform):
    from freepod.api import ApiClient
    from freepod.config import ENVIRONMENTS

    api = ApiClient(ENVIRONMENTS["prod"], _StubSession(), timeout=5)
    api._client = httpx.Client(
        base_url=api._client.base_url, transport=httpx.MockTransport(platform)
    )
    return api


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def test_assignments_are_key_equals_value():
    assert parse_assignments(["A=1", "B=x=y"], interactive=False) == {"A": "1", "B": "x=y"}


def test_a_bare_key_is_prompted_for_without_echo():
    asked = {}

    def prompt(text, hide_input=False):
        asked["text"], asked["hidden"] = text, hide_input
        return SECRET

    values = parse_assignments(["ADMIN_TOKEN"], interactive=True, prompt=prompt)

    assert values == {"ADMIN_TOKEN": SECRET}
    assert asked["hidden"] is True


def test_a_bare_key_off_a_terminal_is_a_usage_error():
    with pytest.raises(UsageError):
        parse_assignments(["ADMIN_TOKEN"], interactive=False)


def test_a_file_of_key_equals_value_lines(tmp_path):
    path = tmp_path / "vars.env"
    path.write_text("# a comment\nA=1\n\nB=two\n")

    assert load_entries(str(path)) == {"A": {"value": "1"}, "B": {"value": "two"}}


def test_the_wire_shape_loads_and_drops_platform_owned_fields(tmp_path):
    path = tmp_path / "vars.json"
    path.write_text(json.dumps({"vars": {"A": entry("1"), "S": entry(sensitive=True)}}))

    assert load_entries(str(path)) == {
        "A": {"value": "1", "sensitive": False},
        # No value: the platform did not return one, so this leaves it alone.
        "S": {"sensitive": True},
    }


def test_secret_defers_to_a_schema_that_declares_the_property():
    record = deployment()
    record["desired_template"]["values_schema_json"] = {
        "properties": {"ADMIN_TOKEN": {"type": "string", "x-caelus-sensitive": True}}
    }

    entries, declared = mark_sensitive(
        {"ADMIN_TOKEN": {"value": "x"}, "OTHER": {"value": "y"}}, record
    )

    assert declared == ["ADMIN_TOKEN"]
    assert "sensitive" not in entries["ADMIN_TOKEN"]
    assert entries["OTHER"]["sensitive"] is True


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def test_a_secret_lists_by_key_with_no_value():
    table = render_table({"vars": {"A": entry("1"), "S": entry(sensitive=True)}})

    assert "A" in table and "1" in table
    assert HIDDEN in table
    assert SECRET not in table


def test_the_listing_reports_when_and_by_whom():
    table = render_table({"vars": {"A": entry("1")}})

    assert "UPDATED" in table and "BY" in table
    assert "dev@example.com" in table
    # The account id identifies an account to a program, not to a person.
    assert " 7" not in table


def test_an_author_the_platform_cannot_name_renders_blank():
    orphan = {**entry("1"), "updated_by": {"id": 9}}

    assert render_table({"vars": {"A": orphan}}).splitlines()[-1].endswith("-")


# --------------------------------------------------------------------------
# The commands
# --------------------------------------------------------------------------


def test_list_json_emits_the_platform_shape(run_var, capsys):
    platform = VarPlatform(vars_={"A": entry("1"), "S": entry(sensitive=True)})

    assert run_var(platform, ["var", "list", "--json"]) == EXIT_OK

    printed = json.loads(capsys.readouterr().out)
    assert printed["vars"]["A"]["value"] == "1"
    assert "value" not in printed["vars"]["S"]


def test_the_json_round_trip_changes_nothing(run_var, capsys):
    """`var list --json` piped into `var set -f -` deletes nothing and alters
    nothing — the property the value-omission rule exists to make safe."""
    platform = VarPlatform(vars_={"A": entry("1"), "S": entry(sensitive=True)})
    run_var(platform, ["var", "list", "--json"])
    listed = capsys.readouterr().out

    assert run_var(platform, ["var", "set", "-f", "-", "--stage"], stdin=listed) == EXIT_OK

    written = platform.writes[-1]
    assert written["A"] == {"value": "1", "sensitive": False}
    assert written["S"] == {"sensitive": True}
    assert "value" not in written["S"]
    assert set(platform.vars) == {"A", "S"}


def test_setting_several_vars_produces_one_rollout(run_var):
    platform = VarPlatform()

    assert run_var(platform, ["var", "set", "A=1", "B=2"]) == EXIT_OK

    assert len(platform.writes) == 1
    assert set(platform.writes[0]) == {"A", "B"}
    assert len(platform.updates) == 1


def test_staging_writes_without_rolling(run_var):
    platform = VarPlatform()

    assert run_var(platform, ["var", "set", "A=1", "--stage"]) == EXIT_OK

    assert platform.writes == [{"A": {"value": "1"}}]
    assert platform.updates == []


def test_staging_works_while_a_rollout_is_in_flight(run_var):
    platform = VarPlatform(status="provisioning")

    assert run_var(platform, ["var", "set", "A=1", "--stage"]) == EXIT_OK

    assert platform.writes == [{"A": {"value": "1"}}]
    assert platform.updates == []


def test_applying_against_a_provisioning_deployment_fails_and_suggests_stage(
    run_var, capsys
):
    """The vars are recorded either way; only the rollout is refused."""
    platform = VarPlatform(status="provisioning")

    assert run_var(platform, ["var", "set", "A=1"]) == EXIT_ERROR

    assert platform.writes == [{"A": {"value": "1"}}]
    assert platform.updates == []
    assert "--stage" in capsys.readouterr().err


def test_a_failed_rollout_keeps_its_exit_code(run_var, capsys):
    """The vars-are-recorded hint must not flatten RolloutFailed into the
    generic failure code: a script that distinguishes "the rollout failed"
    from "something else went wrong" reads the exit code to do it."""
    from freepod import EXIT_ROLLOUT_FAILED, RolloutFailed
    import freepod.cli as cli_module

    platform = VarPlatform()

    def explode(*_args, **_kwargs):
        raise RolloutFailed("the rollout failed for deployment x")

    original = cli_module.deploy_module.release_current
    cli_module.deploy_module.release_current = explode
    try:
        code = run_var(platform, ["var", "set", "A=1"])
    finally:
        cli_module.deploy_module.release_current = original

    assert code == EXIT_ROLLOUT_FAILED
    err = capsys.readouterr().err
    assert "the rollout failed" in err
    assert "--stage" in err


def test_rm_removes_and_rolls(run_var):
    platform = VarPlatform(vars_={"A": entry("1")})

    assert run_var(platform, ["var", "rm", "A"]) == EXIT_OK

    assert "A" not in platform.vars
    assert len(platform.updates) == 1


def test_get_refuses_to_invent_a_value_for_a_secret(run_var, capsys):
    platform = VarPlatform(vars_={"S": entry(sensitive=True)})

    assert run_var(platform, ["var", "get", "S"]) == EXIT_USAGE
    assert "secret" in capsys.readouterr().err


def test_set_with_nothing_to_set_is_a_usage_error(run_var):
    assert run_var(VarPlatform(), ["var", "set"]) == EXIT_USAGE


# --------------------------------------------------------------------------
# What a rollout announces
# --------------------------------------------------------------------------


def test_pending_vars_are_counted_against_the_applied_release():
    from freepod.vars import pending_count

    platform = VarPlatform(
        vars_={"A": entry("2"), "B": entry("keep")},
        pending=True,
        release_vars={"A": entry("1"), "B": entry("keep")},
    )
    api = httpx_client(platform)
    record = deployment_with(platform.vars, pending=True)

    assert pending_count(api, 7, record) == 1


def test_nothing_pending_counts_zero_and_reads_no_release():
    from freepod.vars import pending_count

    platform = VarPlatform(vars_={"A": entry("1")})
    api = httpx_client(platform)

    assert pending_count(api, 7, deployment_with(platform.vars, pending=False)) == 0
    assert not [c for c in platform.calls if "/releases/" in c[1]]


def test_a_deploy_announces_what_it_will_also_apply():
    from freepod.deploy import Preflight, announce_pending_vars

    platform = VarPlatform(
        vars_={"A": entry("2")}, pending=True, release_vars={"A": entry("1")}
    )
    api = httpx_client(platform)
    said = []
    state = Preflight(
        project=None,
        user_id=7,
        product={},
        template={},
        values={},
        deployment=deployment_with(platform.vars, pending=True),
    )

    announce_pending_vars(api, state, echo=said.append)

    assert said == ["This rollout will also apply 1 pending var."]
