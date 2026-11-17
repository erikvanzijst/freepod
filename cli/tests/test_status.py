"""`freepod status` (cli-status)."""

from __future__ import annotations

import json
import re

import httpx
import pytest

from freepod import EXIT_ERROR, EXIT_OK, EXIT_USAGE, FreepodError, UsageError
from freepod.cli import main
from freepod.status import collect, render_table

from conftest import json_response
from test_deploy import deployment, project_at

DEPLOYMENT_ID = deployment()["id"]
PASSWORD = "pg-password-do-not-print"
SECRET = "s3-secret-do-not-print"
ACCESS_KEY = "GKaccesskeydonotprint"

JSON_KEYS = {
    "id", "name", "description", "product", "url", "environment", "created_at",
    "status", "last_error", "last_reconcile_at", "power", "state", "release",
    "plan", "sign_in", "drift", "database", "bucket",
}


def record(status="ready", desired="running", applied="running", reason=None, **extra):
    d = deployment(status=status, last_error=extra.pop("last_error", None))
    d.update(
        name="myapp",
        description=None,
        created_at="2026-08-19T14:05:00",
        last_reconcile_at="2026-11-11T17:50:11",
        desired_template_id=49,
        applied_template={**d["desired_template"], "product": {"name": "Custom user app", "slug": "custom"}},
        applied_release={
            "number": 24, "status": "succeeded", "ended_at": "2026-11-06T23:48:38", "build_id": None,
        },
        subscription={
            "status": "active",
            "payment_status": "current",
            "plan_template": {"price_cents": 0, "billing_interval": "monthly", "plan": {"name": "Free"}},
        },
        auth={"enabled": False, "access": "anyone", "listed_count": None},
        pending=False,
        power={"desired": desired, "applied": applied, "reason": reason},
    )
    d.update(extra)
    return d


DATABASE = {
    "host": "pooler.internal", "port": 5432, "database": "db", "role": "role",
    "password": PASSWORD, "quota_state": "ok", "allowance_bytes": 100 * 1024 ** 2,
    "size_bytes": 3 * 1024 ** 2, "measured_at": "2026-11-17T12:00:00",
}
BUCKET = {
    "bucket": "b", "endpoint": "https://blob.example", "region": "garage",
    "access_key_id": ACCESS_KEY, "secret_access_key": SECRET,
    "usage": {"bytes": 2 * 1024 ** 2, "objects": 14, "max_size_bytes": 1024 ** 3, "max_objects": None},
}
NO_DATABASE = (404, {"detail": "none", "code": "relational_storage_unavailable"})
NO_BUCKET = (404, {"detail": "none", "code": "object_storage_unavailable"})


class Platform:
    def __init__(self, deployment=None, database=(200, DATABASE), bucket=(200, BUCKET)):
        self.deployment = deployment if deployment is not None else record()
        self.database = database
        self.bucket = bucket
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        if path == "/api/me":
            return json_response(200, {"id": 7, "email": "dev@example.com"})
        if path.endswith("/database"):
            return json_response(*self.database)
        if path.endswith("/bucket"):
            return json_response(*self.bucket)
        if re.fullmatch(r"/api/users/7/deployments/[^/]+", path):
            if self.deployment == 404:
                return json_response(404, {"detail": "Not Found"})
            return json_response(200, self.deployment)
        return json_response(404, {"detail": "Not Found"})


def summary_for(make_api, tmp_path, platform, **project):
    project_at(tmp_path, **project)
    api, _, _ = make_api(platform)
    return collect(api, "prod", root=tmp_path)


def table_for(make_api, tmp_path, platform, verbose=False, **project):
    return render_table(summary_for(make_api, tmp_path, platform, **project), verbose=verbose)


def row(table, label):
    for line in table.splitlines():
        if line.startswith(label + " "):
            return line[len(label):].strip()
    return None


# --------------------------------------------------------------------------
# Which deployment
# --------------------------------------------------------------------------


def test_outside_a_project_is_a_usage_error(make_api, tmp_path):
    platform = Platform()
    api, _, _ = make_api(platform)
    with pytest.raises(UsageError):
        collect(api, "prod", root=tmp_path)
    assert platform.calls == []


def test_a_project_without_a_deployment_is_a_usage_error(make_api, tmp_path):
    with pytest.raises(UsageError, match="records no deployment"):
        summary_for(make_api, tmp_path, Platform(), pointer=None)


def test_a_deployment_on_another_environment_is_refused_by_name(make_api, tmp_path):
    platform = Platform()
    with pytest.raises(UsageError, match="on 'dev'"):
        summary_for(make_api, tmp_path, platform, env="dev")
    assert platform.calls == []


def test_a_deleted_deployment_points_at_init(make_api, tmp_path):
    with pytest.raises(FreepodError, match="(?s)no longer exists.*init --force"):
        summary_for(make_api, tmp_path, Platform(deployment=404))


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


def test_identity_rows(make_api, tmp_path):
    table = table_for(make_api, tmp_path, Platform())
    assert row(table, "Name") == "myapp"
    assert row(table, "Address") == "https://myapp-erik.freepod.app"
    assert row(table, "Product") == "Custom user app (chart 0.1.0)"
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", row(table, "Created"))
    assert row(table, "Description") is None


def test_the_deployments_own_description_is_shown(make_api, tmp_path):
    table = table_for(make_api, tmp_path, Platform(record(description="A board\nfor tasks")))
    assert row(table, "Description") == "A board for tasks"


def test_the_platforms_name_wins_and_the_file_key_is_reported(make_api, tmp_path):
    values = {"hostname": "myapp-erik.freepod.app", "name": "renamed"}
    summary = summary_for(make_api, tmp_path, Platform(), values=values)
    assert summary["name"] == "myapp"
    assert summary["drift"]["unapplied_keys"] == ["name"]
    assert "not applied (name)" in row(render_table(summary), "Changes")


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, state, text",
    [
        ({}, "running", "running"),
        ({"desired": "stopped"}, "stopping", "stopping"),
        ({"applied": "stopped"}, "starting", "starting"),
        ({"desired": "stopped", "applied": "stopped", "reason": "manual"}, "stopped", "`freepod start` runs it"),
        ({"desired": "stopped", "applied": "stopped", "reason": "payment"}, "stopped", "cannot be started from the CLI — settle the subscription"),
        ({"desired": "stopped", "applied": "stopped", "reason": "maintenance"}, "stopped", "returns to how it was once that ends"),
        ({"desired": "stopped", "applied": "stopped", "reason": "audit"}, "stopped", "stopped (audit)"),
        ({"status": "pending"}, "pending", "rolling out"),
        ({"status": "provisioning", "applied_release": None}, "provisioning", "being set up"),
        ({"status": "deleting", "desired": "stopped"}, "deleting", "being deleted"),
        ({"status": "error", "last_error": "CrashLoopBackOff", "desired": "stopped", "applied": "stopped"}, "failed", "failed: CrashLoopBackOff"),
    ],
)
def test_state(make_api, tmp_path, kwargs, state, text):
    summary = summary_for(make_api, tmp_path, Platform(record(**kwargs)))
    assert summary["state"] == state
    assert text in row(render_table(summary), "State")


def test_raw_power_is_in_the_json(make_api, tmp_path):
    summary = summary_for(make_api, tmp_path, Platform(record(desired="stopped", applied="stopped", reason="payment")))
    assert summary["power"] == {"desired": "stopped", "applied": "stopped", "reason": "payment"}


# --------------------------------------------------------------------------
# Release, plan, sign-in, drift
# --------------------------------------------------------------------------


def test_release_row(make_api, tmp_path):
    release = {"number": 3, "status": "succeeded", "ended_at": "2026-11-06T23:48:38", "build_id": "4f757be0-6825"}
    text = row(table_for(make_api, tmp_path, Platform(record(applied_release=release))), "Release")
    assert re.fullmatch(r"#3, succeeded \d{4}-\d\d-\d\d \d\d:\d\d \(build 4f757be0\)", text)


def test_no_release_yet(make_api, tmp_path):
    table = table_for(make_api, tmp_path, Platform(record(applied_release=None)))
    assert row(table, "Release") == "nothing released yet"


def plan_record(price=0, interval="monthly", name="Free", status="active", payment="current"):
    return record(subscription={
        "status": status, "payment_status": payment,
        "plan_template": {"price_cents": price, "billing_interval": interval, "plan": {"name": name}},
    })


@pytest.mark.parametrize(
    "kwargs, text",
    [
        ({}, "Free"),
        ({"name": "Hobby"}, "Hobby, free"),
        ({"name": "Pro", "price": 500}, "Pro, €5/month"),
        ({"name": "Pro", "price": 4950, "interval": "annual"}, "Pro, €49.50/year"),
        ({"name": "Pro", "price": 500, "payment": "arrears"}, "Pro, €5/month — payment overdue"),
        ({"name": "Pro", "price": 500, "payment": "pending"}, "Pro, €5/month — awaiting the first payment"),
        ({"name": "Pro", "price": 500, "status": "cancelled"}, "Pro, €5/month — canceled"),
    ],
)
def test_plan_row(make_api, tmp_path, kwargs, text):
    assert row(table_for(make_api, tmp_path, Platform(plan_record(**kwargs))), "Plan") == text


def test_no_subscription_leaves_the_plan_out(make_api, tmp_path):
    table = table_for(make_api, tmp_path, Platform(record(subscription=None)))
    assert row(table, "Plan") is None


@pytest.mark.parametrize(
    "auth, text",
    [
        ({"enabled": False, "access": "anyone"}, "off"),
        ({"enabled": True, "access": "anyone"}, "on — any Freepod account"),
        ({"enabled": True, "access": "listed", "listed_count": 3}, "on — only you and 3 listed people"),
        ({"enabled": True, "access": "listed", "listed_count": 1}, "on — only you and 1 listed person"),
    ],
)
def test_sign_in_row(make_api, tmp_path, auth, text):
    assert row(table_for(make_api, tmp_path, Platform(record(auth=auth))), "Sign-in") == text


def test_up_to_date(make_api, tmp_path):
    assert row(table_for(make_api, tmp_path, Platform()), "Changes") == "up to date"


def test_staged_vars(make_api, tmp_path):
    summary = summary_for(make_api, tmp_path, Platform(record(pending=True)))
    assert summary["drift"]["pending_vars"] is True
    assert "vars staged, not rolled out — `freepod apply`" in row(render_table(summary), "Changes")


def test_template_update_in_flight(make_api, tmp_path):
    summary = summary_for(make_api, tmp_path, Platform(record(desired_template_id=50)))
    assert summary["drift"]["template_update"] is True
    assert "product update" in row(render_table(summary), "Changes")


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------


def test_storage_rows(make_api, tmp_path):
    table = table_for(make_api, tmp_path, Platform())
    assert row(table, "Database") == "3% (3 MB of 100 MB), healthy"
    assert row(table, "Bucket") == "<1% (2 MB of 1.0 GB), 14 objects"


def test_absent_storage_is_left_out(make_api, tmp_path):
    summary = summary_for(make_api, tmp_path, Platform(database=NO_DATABASE, bucket=NO_BUCKET))
    assert summary["database"] is None and summary["bucket"] is None
    table = render_table(summary)
    assert row(table, "Database") is None and row(table, "Bucket") is None


def test_a_failed_storage_read_marks_the_row_unavailable(make_api, tmp_path):
    summary = summary_for(make_api, tmp_path, Platform(bucket=(500, {"detail": "garage down"})))
    assert "error" in summary["bucket"]
    assert row(render_table(summary), "Bucket").startswith("unavailable (")
    assert row(render_table(summary), "Database") == "3% (3 MB of 100 MB), healthy"


def test_an_unmeasured_database(make_api, tmp_path):
    database = {**DATABASE, "size_bytes": None, "measured_at": None}
    table = table_for(make_api, tmp_path, Platform(database=(200, database)))
    assert row(table, "Database") == "not yet measured, healthy"


# --------------------------------------------------------------------------
# Through main
# --------------------------------------------------------------------------


@pytest.fixture
def at_project(stub_api, cached_credential, tmp_path, monkeypatch):
    def install(platform):
        project_at(tmp_path)
        stub_api(platform)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    return install


@pytest.mark.parametrize("args", [["status"], ["status", "--json"], ["--verbose", "status"]])
def test_no_credential_in_any_form(at_project, capsys, args):
    at_project(Platform())
    assert main(args) == EXIT_OK
    captured = capsys.readouterr()
    for secret in (PASSWORD, SECRET, ACCESS_KEY, "pooler.internal"):
        assert secret not in captured.out + captured.err


def test_json_keys_are_pinned(at_project, capsys):
    at_project(Platform())
    assert main(["status", "--json"]) == EXIT_OK
    assert set(json.loads(capsys.readouterr().out)) == JSON_KEYS


def test_verbose_adds_the_raw_values(at_project, capsys):
    at_project(Platform(record(desired="stopped", applied="stopped", reason="manual")))
    assert main(["--verbose", "status"]) == EXIT_OK
    out = capsys.readouterr().out
    assert row(out, "Id") == DEPLOYMENT_ID
    assert row(out, "Status") == "ready"
    assert row(out, "Power") == "stopped/stopped (manual)"


def test_a_failed_deployment_exits_zero(at_project, capsys):
    at_project(Platform(record(status="error", last_error="boom")))
    assert main(["status"]) == EXIT_OK
    assert "failed: boom" in capsys.readouterr().out


def test_quiet_leaves_only_the_result(at_project, capsys):
    at_project(Platform(record(pending=True)))
    assert main(["--quiet", "status"]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.err == ""
    assert row(captured.out, "Name") == "myapp"


def test_no_separate_unapplied_warning(at_project, capsys):
    at_project(Platform())
    assert main(["status"]) == EXIT_OK
    assert "Warning:" not in capsys.readouterr().err


def test_outside_a_project_exits_two(stub_api, cached_credential, tmp_path, monkeypatch):
    stub_api(Platform())
    monkeypatch.chdir(tmp_path)
    assert main(["status"]) == EXIT_USAGE


def test_a_deleted_deployment_exits_one(at_project):
    at_project(Platform(deployment=404))
    assert main(["status"]) == EXIT_ERROR
