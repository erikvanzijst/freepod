"""`freepod db status`: the deployment's database, its credential and its health.

The command reports no address and no connection URL, which is the point of
several of these tests: the pooler resolves inside the cluster and nowhere
else, so a URL printed here would be the input to a `psql` that cannot connect.
"""

from __future__ import annotations

import re

import httpx
import pytest

from freepod import EXIT_ERROR, EXIT_OK, EXIT_USAGE
from freepod.cli import main
from freepod.database import NO_DATABASE_CODE, format_bytes, format_usage

from conftest import json_response
from test_deploy import project_at
from test_vars import DEPLOYMENT_ID, POINTER, _StubSession, httpx_client

MEGABYTE = 1024 ** 2

PASSWORD = "p@ss/w:rd?#[]&=+ 90%"
POOLER_HOST = "caelus-tenant-pooler.caelus-tenant.svc.cluster.local"


def details(**overrides):
    body = {
        "host": POOLER_HOST,
        "port": 6432,
        "database": "dpl_0f2c",
        "role": "dpl_0f2c",
        "password": PASSWORD,
        "password_withheld": False,
        "quota_state": "ok",
        "allowance_bytes": 100 * MEGABYTE,
        "size_bytes": 42 * MEGABYTE,
        "measured_at": "2026-08-29T09:14:00",
    }
    body.update(overrides)
    return body


class DatabasePlatform:
    """A platform serving one deployment's database details."""

    def __init__(self, *, body=None, status=200):
        self.body = details() if body is None else body
        self.status = status
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append((method, path))

        if path == "/api/me":
            return json_response(200, {"id": 7, "email": "dev@example.com"})
        if re.fullmatch(r"/api/users/7/deployments/[^/]+/database", path):
            return json_response(self.status, self.body)
        return json_response(404, {"detail": f"unrouted {method} {path}"})


@pytest.fixture
def run_db(monkeypatch, tmp_path):
    """Drive `main(['db', ...])` against a scripted platform in `tmp_path`."""

    def go(platform, argv, *, pointer=POINTER):
        project_at(tmp_path, pointer=pointer)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "freepod.cli.Context.session", lambda self, force_flow=None: _StubSession()
        )
        monkeypatch.setattr(
            "freepod.cli.Context.client", lambda self, session: httpx_client(platform)
        )
        return main(argv)

    return go


# --------------------------------------------------------------------------
# What it reports
# --------------------------------------------------------------------------


def test_it_reports_the_database_its_role_and_its_health(run_db, capsys):
    code = run_db(DatabasePlatform(), ["db", "status"])
    out = capsys.readouterr().out

    assert code == EXIT_OK
    assert "dpl_0f2c" in out
    assert "42% (42 MB of 100 MB)" in out
    assert "healthy" in out


def test_it_reports_no_address_and_no_connection_url(run_db, capsys):
    run_db(DatabasePlatform(), ["db", "status"])
    captured = capsys.readouterr()
    everything = captured.out + captured.err

    assert POOLER_HOST not in everything
    assert "6432" not in everything
    assert "postgresql://" not in everything


def test_no_flag_combination_prints_an_address(run_db, capsys):
    for argv in (["db", "status"], ["db", "status", "--show-password"]):
        run_db(DatabasePlatform(), argv)
        captured = capsys.readouterr()
        everything = captured.out + captured.err
        assert POOLER_HOST not in everything, argv
        assert "postgresql://" not in everything, argv


def test_the_password_is_masked_and_says_how_to_reveal_it(run_db, capsys):
    run_db(DatabasePlatform(), ["db", "status"])
    out = capsys.readouterr().out

    assert PASSWORD not in out
    assert "--show-password" in out
    # The mask must not be mistakable for the value.
    assert "•" in out


def test_show_password_prints_it(run_db, capsys):
    run_db(DatabasePlatform(), ["db", "status", "--show-password"])
    assert PASSWORD in capsys.readouterr().out


def test_a_withheld_password_is_stated_rather_than_shown_as_absent(run_db, capsys):
    platform = DatabasePlatform(body=details(password=None, password_withheld=True))
    run_db(platform, ["db", "status"])
    out = capsys.readouterr().out

    assert "withheld" in out.lower()
    assert "--show-password" not in out


def test_it_says_where_the_database_can_be_reached_from(run_db, capsys):
    run_db(DatabasePlatform(), ["db", "status"])
    captured = capsys.readouterr()

    # A diagnostic, not the result.
    assert "not from this machine" in captured.err
    assert "not from this machine" not in captured.out


def test_quiet_silences_the_diagnostic_and_leaves_the_result(run_db, capsys):
    run_db(DatabasePlatform(), ["--quiet", "db", "status"])
    captured = capsys.readouterr()

    assert "dpl_0f2c" in captured.out
    assert captured.err == ""


# --------------------------------------------------------------------------
# Quota states and measurement
# --------------------------------------------------------------------------


def test_read_only_says_writes_are_rejected(run_db, capsys):
    run_db(DatabasePlatform(body=details(quota_state="readonly")), ["db", "status"])
    out = capsys.readouterr().out

    assert "read-only" in out
    assert "write" in out and "rejected" in out


def test_suspended_says_the_app_cannot_connect(run_db, capsys):
    run_db(DatabasePlatform(body=details(quota_state="blocked")), ["db", "status"])
    out = capsys.readouterr().out

    assert "suspended" in out
    assert "cannot connect" in out


def test_never_measured_is_not_reported_as_zero(run_db, capsys):
    platform = DatabasePlatform(body=details(size_bytes=None, measured_at=None))
    run_db(platform, ["db", "status"])
    out = capsys.readouterr().out

    assert "not yet measured" in out
    assert "0 B" not in out


def test_measured_at_zero_is_a_measurement(run_db, capsys):
    platform = DatabasePlatform(body=details(size_bytes=0))
    run_db(platform, ["db", "status"])
    out = capsys.readouterr().out

    assert "0% (0 B of 100 MB)" in out
    assert "not yet measured" not in out


def test_a_non_empty_database_never_rounds_down_to_nothing(run_db, capsys):
    run_db(DatabasePlatform(body=details(size_bytes=64 * 1024)), ["db", "status"])
    assert "<1% (64 KB of 100 MB)" in capsys.readouterr().out


def test_a_database_past_its_allowance_reads_over_100(run_db, capsys):
    platform = DatabasePlatform(body=details(size_bytes=142 * MEGABYTE, quota_state="readonly"))
    run_db(platform, ["db", "status"])
    assert "142% (142 MB of 100 MB)" in capsys.readouterr().out


def test_a_size_carries_the_age_of_its_measurement(run_db, capsys):
    run_db(DatabasePlatform(), ["db", "status"])
    assert "measured" in capsys.readouterr().out


def test_format_usage_matches_the_dashboard():
    assert format_usage(42 * MEGABYTE, 100 * MEGABYTE) == "42% (42 MB of 100 MB)"
    assert format_usage(0, 100 * MEGABYTE) == "0% (0 B of 100 MB)"
    assert format_usage(64 * 1024, 100 * MEGABYTE) == "<1% (64 KB of 100 MB)"


def test_format_bytes_scales():
    assert format_bytes(0) == "0 B"
    assert format_bytes(2048) == "2 KB"
    assert format_bytes(42 * MEGABYTE) == "42 MB"
    assert format_bytes(3 * 1024 ** 3) == "3.0 GB"


# --------------------------------------------------------------------------
# Absence
# --------------------------------------------------------------------------


def test_a_product_without_a_database_is_not_an_error(run_db, capsys):
    platform = DatabasePlatform(
        status=404, body={"detail": "no relational storage", "code": NO_DATABASE_CODE}
    )
    code = run_db(platform, ["db", "status"])
    captured = capsys.readouterr()

    assert code == EXIT_OK
    assert "no database" in captured.err.lower()
    assert captured.out == ""


def test_a_missing_deployment_is_an_error(run_db, capsys):
    platform = DatabasePlatform(status=404, body={"detail": "Deployment not found"})
    code = run_db(platform, ["db", "status"])

    assert code == EXIT_ERROR
    assert "Traceback" not in capsys.readouterr().err


def test_a_project_recording_no_deployment_is_a_usage_error(run_db, capsys):
    code = run_db(DatabasePlatform(), ["db", "status"], pointer=None)

    assert code == EXIT_USAGE
    assert "freepod init" in capsys.readouterr().err


# --------------------------------------------------------------------------
# The group
# --------------------------------------------------------------------------


def test_the_group_and_its_subcommand_are_reachable(capsys):
    """`db` is the group `db proxy` and `db shell` will join."""
    assert main(["db", "--help"]) == EXIT_OK
    group_help = capsys.readouterr().out
    assert "status" in group_help

    assert main(["db", "status", "--help"]) == EXIT_OK
    assert "--show-password" in capsys.readouterr().out


def test_the_group_help_promises_no_connection_it_cannot_make(capsys):
    main(["db", "--help"])
    help_text = capsys.readouterr().out

    assert "not reachable from this machine" in help_text
    assert "postgresql://" not in help_text
