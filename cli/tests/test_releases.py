"""`freepod releases`: what the listing reads, how it marks, and how it renders."""

from __future__ import annotations

import json
import re

import httpx

from freepod import EXIT_OK, EXIT_USAGE
from freepod.cli import main
from freepod.releases import (
    LIVE_MARKER,
    applied_number,
    failures,
    image_of,
    list_releases,
    render_table,
    rows,
)

from conftest import json_response

DEPLOYMENT_ID = "40bd8dea-0000-4000-8000-000000000001"
IMAGE = "7@sha256:" + "a" * 64
POINTER = {"id": DEPLOYMENT_ID, "name": "custom-d8dtx4"}


def build(image=IMAGE, status="succeeded"):
    return {
        "id": "b0000000-0000-4000-8000-000000000001",
        "user_id": 7,
        "artifact_id": "f" * 32,
        "status": status,
        "created_at": "2026-08-15T21:45:39.121435",
        "started_at": "2026-08-15T21:45:39.273312",
        "finished_at": "2026-08-15T21:46:39.729868",
        "image": image,
    }


def release(
    number=1,
    status="succeeded",
    created_at="2026-08-15T21:45:39.121435",
    started_at="2026-08-15T21:45:40.000000",
    ended_at="2026-08-15T21:46:10.000000",
    error=None,
    with_build=True,
):
    return {
        "id": f"1e000000-0000-4000-8000-00000000000{number}",
        "deployment_id": DEPLOYMENT_ID,
        "number": number,
        "template_id": 3,
        "build_id": build()["id"] if with_build else None,
        "build": build() if with_build else None,
        "values_json": {"hostname": "myapp.freepod.eu"},
        "created_at": created_at,
        "started_at": started_at,
        "ended_at": ended_at,
        "error": error,
        "helm_revision": number,
        "status": status,
    }


class Platform:
    """The two reads the listing performs, and nothing else."""

    def __init__(self, *, user_id=7, releases=None, deployment=None, deployment_status=200):
        self.user_id = user_id
        self.releases = [release()] if releases is None else releases
        self.deployment = deployment
        self.deployment_status = deployment_status
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))

        if path == "/api/me":
            return json_response(200, {"id": self.user_id, "email": "dev@example.com"})
        if re.fullmatch(r"/api/users/\d+/deployments/[^/]+/releases", path):
            return json_response(200, self.releases)
        if re.fullmatch(r"/api/users/\d+/deployments/[^/]+", path):
            if self.deployment_status != 200:
                return json_response(self.deployment_status, {"detail": "Deployment not found"})
            return json_response(200, self.deployment or {})
        return json_response(404, {"detail": "Not Found"})

    def paths(self):
        return [p for _m, p in self.calls]


def deployment_applying(number):
    return {
        "id": DEPLOYMENT_ID,
        "name": "custom-d8dtx4",
        "status": "ready",
        "hostname": "myapp.freepod.eu",
        "applied_release": None if number is None else {"number": number, "id": "x"},
        "desired_release": {"number": 99, "id": "y"},
    }


def project_at(tmp_path, *, env="prod", pointer=None):
    document = {"version": 2, "env": env, "hostname": "myapp"}
    if pointer:
        document["deployment"] = pointer["id"]
    (tmp_path / ".freepod.json").write_text(json.dumps(document))
    return tmp_path


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def test_the_platforms_order_is_kept(make_api):
    ordered = [release(number=3), release(number=2), release(number=1)]
    api, _, _ = make_api(Platform(releases=ordered))

    assert [r["number"] for r in list_releases(api, 7, DEPLOYMENT_ID)] == [3, 2, 1]


def test_the_listing_is_read_under_the_deployment(make_api):
    api, recorder, _ = make_api(Platform())

    list_releases(api, 7, DEPLOYMENT_ID)

    assert recorder.paths()[-1] == f"/api/users/7/deployments/{DEPLOYMENT_ID}/releases"


# --------------------------------------------------------------------------
# The mark
# --------------------------------------------------------------------------


def test_the_applied_release_is_the_mark_not_the_desired_one():
    assert applied_number(deployment_applying(2)) == 2


def test_no_applied_release_means_no_mark():
    assert applied_number(deployment_applying(None)) is None
    assert applied_number(None) is None
    assert applied_number({}) is None


def test_a_failed_newest_release_does_not_move_the_mark():
    """The newest release failed; release 2 is still the one serving traffic."""
    listed = [
        release(number=3, status="failed", error="helm upgrade failed"),
        release(number=2),
        release(number=1),
    ]

    table = rows(listed, live_number=2)

    marked = [row[1] for row in table[1:] if row[0] == LIVE_MARKER]
    assert marked == ["2"]


def test_only_one_release_is_ever_marked():
    table = rows([release(number=2), release(number=1)], live_number=2)

    assert [row[0] for row in table[1:]] == [LIVE_MARKER, ""]


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------


def test_the_image_comes_from_the_inlined_build():
    assert image_of(release()) == IMAGE
    assert image_of(release(with_build=False)) is None


def test_duration_is_measured_from_when_the_rollout_began():
    """30s of rollout, not the wait since the release was created."""
    table = rows([release()])

    assert table[1][4] == "30s"


def test_a_release_that_never_started_reports_no_duration():
    table = rows([release(number=4, status="queued", started_at=None, ended_at=None)])

    assert table[1][4] == "-"


def test_a_release_naming_no_build_shows_no_image_rather_than_being_omitted():
    table = rows([release(number=2, with_build=False), release(number=1)])

    assert len(table) == 3
    assert table[1][5] == "-"


def test_failed_releases_surface_their_error():
    notes = failures(
        [release(number=3, status="failed", error="helm upgrade failed"), release(number=2)]
    )

    assert notes == ["release 3 failed: helm upgrade failed"]


def test_a_blank_marker_column_does_not_pad_every_line():
    text = render_table([release()], live_number=None)

    assert all(line == line.rstrip() for line in text.splitlines())


# --------------------------------------------------------------------------
# Through `main`
# --------------------------------------------------------------------------


def test_the_table_is_the_result_and_the_legend_is_not(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path, pointer=POINTER)
    stub_api(Platform(releases=[release(number=1)], deployment=deployment_applying(1)))
    monkeypatch.chdir(tmp_path)

    assert main(["releases"]) == EXIT_OK

    captured = capsys.readouterr()
    assert "RELEASE" in captured.out
    assert "succeeded" in captured.out
    assert f"{LIVE_MARKER} the release this deployment is running." in captured.err
    assert "this deployment is running" not in captured.out


def test_quiet_keeps_the_table(stub_api, cached_credential, tmp_path, monkeypatch, capsys):
    project_at(tmp_path, pointer=POINTER)
    stub_api(Platform(releases=[release(number=1)], deployment=deployment_applying(1)))
    monkeypatch.chdir(tmp_path)

    assert main(["--quiet", "releases"]) == EXIT_OK

    captured = capsys.readouterr()
    assert "RELEASE" in captured.out
    assert captured.err == ""


def test_limit_keeps_the_most_recent_and_says_what_it_hid(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path, pointer=POINTER)
    stub_api(
        Platform(
            releases=[release(number=n) for n in (5, 4, 3, 2, 1)],
            deployment=deployment_applying(5),
        )
    )
    monkeypatch.chdir(tmp_path)

    assert main(["releases", "--limit", "2"]) == EXIT_OK

    captured = capsys.readouterr()
    assert "Showing 2 of 5 releases" in captured.err


def test_all_lifts_the_bound(stub_api, cached_credential, tmp_path, monkeypatch, capsys):
    project_at(tmp_path, pointer=POINTER)
    stub_api(
        Platform(
            releases=[release(number=n) for n in (5, 4, 3, 2, 1)],
            deployment=deployment_applying(5),
        )
    )
    monkeypatch.chdir(tmp_path)

    assert main(["releases", "--all"]) == EXIT_OK

    captured = capsys.readouterr()
    assert "Showing" not in captured.err


def test_a_bound_that_shows_nothing_is_a_usage_error(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path, pointer=POINTER)
    stub_api(Platform())
    monkeypatch.chdir(tmp_path)

    assert main(["releases", "--limit", "0"]) == EXIT_USAGE


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


def test_no_project_file_is_refused(stub_api, cached_credential, tmp_path, monkeypatch, capsys):
    stub_api(Platform())
    monkeypatch.chdir(tmp_path)

    assert main(["releases"]) == EXIT_USAGE
    assert "freepod init" in capsys.readouterr().err


def test_a_project_that_has_never_deployed_is_refused(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path, pointer=None)
    stub_api(Platform())
    monkeypatch.chdir(tmp_path)

    assert main(["releases"]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "no deployment" in err and "freepod init" in err


def test_a_project_on_another_environment_is_refused(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    """Only an explicit `--env` can disagree: without one the project decides."""
    project_at(tmp_path, env="dev", pointer=POINTER)
    stub_api(Platform())
    monkeypatch.chdir(tmp_path)

    assert main(["--env", "prod", "releases"]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "dev" in err and "prod" in err


def test_a_refusal_reads_nothing_from_the_platform(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    """The preflight refuses before authenticating, so no request goes out."""
    project_at(tmp_path, pointer=None)
    platform = Platform()
    stub_api(platform)
    monkeypatch.chdir(tmp_path)

    main(["releases"])

    assert platform.paths() == []
