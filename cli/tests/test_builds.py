"""`freepod builds`: what the history reads, and how it renders."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from freepod import EXIT_OK, EXIT_USAGE
from freepod.cli import main
from freepod.history import (
    DEFAULT_LIMIT,
    LIVE_MARKER,
    abbreviate,
    deployed_image,
    duration,
    format_duration,
    format_time,
    list_builds,
    parse_time,
    render,
    rows,
)

from conftest import json_response

DIGEST = "a" * 64
IMAGE = f"7@sha256:{DIGEST}"
OTHER_IMAGE = f"7@sha256:{'b' * 64}"

DEPLOYMENT_ID = "40bd8dea-0000-4000-8000-000000000001"


def build(
    id="b0000000-0000-4000-8000-000000000001",
    status="succeeded",
    created_at="2026-08-15T21:45:39.121435",
    started_at="2026-08-15T21:45:39.273312",
    finished_at="2026-08-15T21:46:39.729868",
    image=IMAGE,
):
    return {
        "id": id,
        "deployment_id": DEPLOYMENT_ID,
        "artifact_id": "f7fdc396465f41dd8710577b1417eccf",
        "status": status,
        "created_at": created_at,
        "started_at": started_at,
        "finished_at": finished_at,
        "image": image,
    }


class Platform:
    """The reads a listing performs, and nothing else. Builds are served only
    under the project's deployment."""

    def __init__(self, *, user_id=7, builds=None, deployment=None, deployment_status=200):
        self.user_id = user_id
        self.builds = [build()] if builds is None else builds
        self.deployment = deployment
        self.deployment_status = deployment_status
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))

        if path == "/api/me":
            return json_response(200, {"id": self.user_id, "email": "dev@example.com"})
        if path == f"/api/users/{self.user_id}/deployments/{DEPLOYMENT_ID}/builds":
            return json_response(200, self.builds)
        if re.fullmatch(r"/api/users/\d+/deployments/[^/]+", path):
            if self.deployment_status != 200:
                return json_response(self.deployment_status, {"detail": "Deployment not found"})
            return json_response(200, self.deployment or {})
        return json_response(404, {"detail": "Not Found"})

    def paths(self):
        return [p for _m, p in self.calls]


def deployment_running(image):
    return {
        "id": DEPLOYMENT_ID,
        "name": "custom-d8dtx4",
        "status": "ready",
        "hostname": "myapp.freepod.eu",
        "user_values_json": {"hostname": "myapp.freepod.eu", "image": image},
    }


def project_at(tmp_path, *, env="prod", pointer=None):
    document = {
        "version": 1,
        "env": env,
        "deployment": pointer,
        "user_values": {"hostname": "myapp.freepod.eu"},
    }
    (tmp_path / ".freepod.json").write_text(json.dumps(document))
    return tmp_path


POINTER = {"id": DEPLOYMENT_ID, "name": "custom-d8dtx4"}


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def test_the_platforms_order_is_kept(make_api):
    """Most recent first is the endpoint's contract. Re-sorting here would mean
    parsing every timestamp to reproduce an answer already given."""
    ordered = [build(id="b-1"), build(id="b-2"), build(id="b-3")]
    api, _, _ = make_api(Platform(builds=ordered))

    listed = list_builds(api, 7, DEPLOYMENT_ID)

    assert [record["id"] for record in listed] == ["b-1", "b-2", "b-3"]


def test_the_deployed_image_comes_from_the_projects_deployment(make_api):
    api, _, _ = make_api(Platform(deployment=deployment_running(IMAGE)))

    assert deployed_image(api, 7, DEPLOYMENT_ID) == IMAGE


def test_a_deleted_deployment_marks_nothing(make_api):
    """The platform no longer answers for it, but its builds are still listed."""
    api, _, _ = make_api(Platform(deployment_status=404))

    assert deployed_image(api, 7, DEPLOYMENT_ID) is None


def test_a_deployment_with_no_image_marks_nothing(make_api):
    api, _, _ = make_api(Platform(deployment=deployment_running(None)))

    assert deployed_image(api, 7, DEPLOYMENT_ID) is None


# --------------------------------------------------------------------------
# Timestamps and durations
# --------------------------------------------------------------------------


def test_a_timestamp_without_an_offset_is_read_as_utc():
    """The API serializes naive datetimes that are UTC by construction. Reading
    them as local would misreport every duration by the reader's own offset."""
    assert parse_time("2026-08-15T21:45:39.121435") == datetime(
        2026, 8, 15, 21, 45, 39, 121435, tzinfo=timezone.utc
    )


def test_a_zulu_timestamp_is_understood():
    """`fromisoformat` only learned `Z` in 3.11, and 3.9 is the floor."""
    assert parse_time("2026-08-15T21:45:39Z") == datetime(
        2026, 8, 15, 21, 45, 39, tzinfo=timezone.utc
    )


def test_an_unparseable_timestamp_is_shown_rather_than_guessed_at():
    assert parse_time("shortly after lunch") is None
    assert format_time("shortly after lunch") == "shortly after lunch"


def test_the_duration_is_measured_from_the_start_not_the_queueing():
    """Counting the wait for a worker would report a five-second build as a
    five-minute one whenever the queue was busy."""
    record = build(
        created_at="2026-08-15T21:40:00",
        started_at="2026-08-15T21:45:00",
        finished_at="2026-08-15T21:45:30",
    )

    assert format_duration(duration(record)) == "30s"


def test_a_running_build_reports_how_long_it_has_been_running():
    record = build(started_at="2026-08-15T21:45:00", finished_at=None, status="running")
    now = datetime(2026, 8, 15, 21, 47, 30, tzinfo=timezone.utc)

    assert format_duration(duration(record, now)) == "2m 30s"


def test_a_queued_build_has_no_duration():
    record = build(status="queued", started_at=None, finished_at=None, image=None)

    assert duration(record) is None
    assert format_duration(None) == "-"


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "0s"), (45, "45s"), (59, "59s"), (60, "1m 0s"), (192, "3m 12s"), (3840, "1h 4m")],
)
def test_durations_carry_two_units_at_most(seconds, expected):
    assert format_duration(timedelta(seconds=seconds)) == expected


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def test_a_digest_is_abbreviated_to_twelve_characters():
    assert abbreviate(IMAGE) == f"7@sha256:{'a' * 12}…"


def test_verbose_prints_the_reference_in_full():
    assert abbreviate(IMAGE, full=True) == IMAGE


def test_a_reference_without_a_digest_is_left_alone():
    assert abbreviate("registry.home/caelus/app:1.2.3") == "registry.home/caelus/app:1.2.3"


def test_a_build_with_no_image_shows_a_placeholder():
    assert abbreviate(None) == "-"


def test_the_deployed_build_is_the_only_one_marked():
    table = rows([build(id="b-1", image=IMAGE), build(id="b-2", image=OTHER_IMAGE)], live_image=IMAGE)

    assert [row[0] for row in table[1:]] == [LIVE_MARKER, ""]


def test_nothing_is_marked_when_the_deployed_image_is_unknown():
    table = rows([build(image=IMAGE)], live_image=None)

    assert table[1][0] == ""


def test_the_table_starts_with_its_headers():
    table = rows([build()])

    assert table[0][1:] == ["BUILD", "STATUS", "CREATED", "DURATION", "IMAGE"]


def test_columns_are_wide_enough_for_their_contents():
    text = render(rows([build(id="b-1", status="failed", image=None)]))
    header, row = text.splitlines()

    assert header.index("STATUS") == row.index("failed")
    # `rindex`: the date carries dashes of its own, and the placeholder is last.
    assert header.index("IMAGE") == row.rindex("-")


def test_no_row_carries_trailing_whitespace():
    """A marker column that is blank on every row must not pad every line."""
    text = render(rows([build(image=IMAGE)], live_image=None))

    assert all(line == line.rstrip() for line in text.splitlines())


# --------------------------------------------------------------------------
# Through `main`
# --------------------------------------------------------------------------


def test_the_table_is_the_result_and_the_legend_is_not(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path, pointer=POINTER)
    stub_api(Platform(builds=[build()], deployment=deployment_running(IMAGE)))
    monkeypatch.chdir(tmp_path)

    assert main(["builds"]) == EXIT_OK

    captured = capsys.readouterr()
    assert "BUILD" in captured.out
    assert "succeeded" in captured.out
    assert f"{LIVE_MARKER} the build this project's deployment is running." in captured.err
    assert "this project's deployment" not in captured.out


def test_limit_keeps_the_most_recent_and_says_what_it_hid(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    stub_api(Platform(builds=[build(id=f"b-{n}") for n in range(5)]))
    project_at(tmp_path, pointer=POINTER)
    monkeypatch.chdir(tmp_path)

    assert main(["builds", "--limit", "2"]) == EXIT_OK

    captured = capsys.readouterr()
    assert "b-0" in captured.out and "b-1" in captured.out
    assert "b-2" not in captured.out
    assert "Showing 2 of 5 builds" in captured.err


def test_all_overrides_the_limit(stub_api, cached_credential, tmp_path, monkeypatch, capsys):
    stub_api(Platform(builds=[build(id=f"b-{n}") for n in range(DEFAULT_LIMIT + 3)]))
    project_at(tmp_path, pointer=POINTER)
    monkeypatch.chdir(tmp_path)

    assert main(["builds", "--all"]) == EXIT_OK

    captured = capsys.readouterr()
    assert f"b-{DEFAULT_LIMIT + 2}" in captured.out
    assert "Showing" not in captured.err


def test_a_limit_of_zero_is_a_usage_error(stub_api, cached_credential, tmp_path, monkeypatch, capsys):
    platform = Platform()
    stub_api(platform)
    monkeypatch.chdir(tmp_path)

    assert main(["builds", "--limit", "0"]) == EXIT_USAGE

    # Refused before a request was spent on it.
    assert platform.calls == []
    capsys.readouterr()


def test_a_project_with_no_builds_says_so_and_prints_no_table(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    stub_api(Platform(builds=[]))
    project_at(tmp_path, pointer=POINTER)
    monkeypatch.chdir(tmp_path)

    assert main(["builds"]) == EXIT_OK

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no builds" in captured.err


def test_verbose_widens_the_image_column(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    stub_api(Platform(builds=[build()]))
    project_at(tmp_path, pointer=POINTER)
    monkeypatch.chdir(tmp_path)

    assert main(["--verbose", "builds"]) == EXIT_OK

    assert IMAGE in capsys.readouterr().out


def test_quiet_leaves_the_table_and_drops_the_legend(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path, pointer=POINTER)
    stub_api(Platform(builds=[build()], deployment=deployment_running(IMAGE)))
    monkeypatch.chdir(tmp_path)

    assert main(["--quiet", "builds"]) == EXIT_OK

    captured = capsys.readouterr()
    assert "BUILD" in captured.out
    assert captured.err == ""


def test_only_the_projects_builds_are_listed(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path, pointer=POINTER)
    platform = Platform(builds=[build(id="b-mine")], deployment=deployment_running(IMAGE))
    stub_api(platform)
    monkeypatch.chdir(tmp_path)

    assert main(["builds"]) == EXIT_OK

    assert "b-mine" in capsys.readouterr().out
    assert f"/api/users/7/deployments/{DEPLOYMENT_ID}/builds" in platform.paths()
    assert "/api/users/7/builds" not in platform.paths()


def test_a_deleted_deployments_builds_are_still_listed(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path, pointer=POINTER)
    stub_api(Platform(builds=[build(id="b-old")], deployment_status=404))
    monkeypatch.chdir(tmp_path)

    assert main(["builds"]) == EXIT_OK

    captured = capsys.readouterr()
    assert "b-old" in captured.out
    assert LIVE_MARKER not in captured.err


def test_outside_a_project_the_history_is_refused(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    platform = Platform()
    stub_api(platform)
    monkeypatch.chdir(tmp_path)

    assert main(["builds"]) == EXIT_USAGE

    assert "freepod init" in capsys.readouterr().err
    assert platform.calls == []


def test_a_project_that_has_not_deployed_is_refused(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    project_at(tmp_path, pointer=None)
    platform = Platform()
    stub_api(platform)
    monkeypatch.chdir(tmp_path)

    assert main(["builds"]) == EXIT_USAGE

    err = capsys.readouterr().err
    assert "no builds" in err and "freepod deploy" in err
    assert platform.calls == []


def test_a_project_for_another_environment_is_refused(
    stub_api, cached_credential, tmp_path, monkeypatch, capsys
):
    """The file's environment is the default; only an explicit `--env` can disagree."""
    project_at(tmp_path, env="dev", pointer=POINTER)
    platform = Platform()
    stub_api(platform)
    monkeypatch.chdir(tmp_path)

    assert main(["--env", "prod", "builds"]) == EXIT_USAGE

    assert "dev" in capsys.readouterr().err
    assert platform.calls == []
