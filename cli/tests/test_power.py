"""`freepod stop` and `freepod start` (cli-power)."""

from __future__ import annotations

import re

import httpx
import pytest

from freepod import EXIT_ERROR, EXIT_OK, EXIT_USAGE, FreepodError, UsageError
from freepod.cli import main
from freepod.power import RUNNING, STOPPED, change

from conftest import json_response
from test_deploy import deployment, project_at

POINTER = {"id": deployment()["id"], "name": "custom-d8dtx4"}


def record(desired="running", applied="running", status="ready", reason=None, last_error=None):
    d = deployment(status=status, last_error=last_error)
    d["power"] = {"desired": desired, "applied": applied, "reason": reason}
    return d


class Platform:
    """`reads` is the queue of GETs, repeating the last; `answer` is what the
    POST returns: a status code and a body."""

    def __init__(self, reads, answer=(200, None)):
        self.reads = list(reads)
        self.answer = answer
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        if path == "/api/me":
            return json_response(200, {"id": 7, "email": "dev@example.com"})
        if method == "POST" and re.fullmatch(r"/api/users/7/deployments/[^/]+/(stop|start)", path):
            status, body = self.answer
            return json_response(status, body if body is not None else self.reads[0])
        if re.fullmatch(r"/api/users/7/deployments/[^/]+", path):
            current = self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]
            return json_response(200, current)
        return json_response(404, {"detail": "Not Found"})

    def posts(self):
        return [p for m, p in self.calls if m == "POST"]


def run(make_api, platform, tmp_path, target, **kwargs):
    api, _, _ = make_api(platform)
    messages = []
    kwargs.setdefault("timeout", 5)
    result = change(api, "prod", target, root=tmp_path, poll=0, echo=messages.append, **kwargs)
    return result, "\n".join(messages)


def test_outside_a_project_is_a_usage_error(make_api, tmp_path):
    platform = Platform([record()])
    with pytest.raises(UsageError):
        run(make_api, platform, tmp_path, STOPPED)
    assert platform.calls == []


def test_a_project_without_a_deployment_is_a_usage_error(make_api, tmp_path):
    project_at(tmp_path, pointer=None)
    with pytest.raises(UsageError, match="records no deployment"):
        run(make_api, Platform([record()]), tmp_path, STOPPED)


def test_a_deployment_on_another_environment_is_refused_by_name(make_api, tmp_path):
    project_at(tmp_path, pointer=POINTER, env="dev")
    platform = Platform([record()])
    with pytest.raises(UsageError, match="on 'dev'"):
        run(make_api, platform, tmp_path, STOPPED)
    assert platform.posts() == []


def test_stop_asks_nothing_and_waits_until_applied(make_api, tmp_path):
    project_at(tmp_path, pointer=POINTER)
    platform = Platform(
        [record(), record("stopped", "running"), record("stopped", "stopped")],
        answer=(200, record("stopped", "running")),
    )
    final, said = run(make_api, platform, tmp_path, STOPPED)
    assert platform.posts() == [f"/api/users/7/deployments/{POINTER['id']}/stop"]
    assert final["power"]["applied"] == "stopped"
    assert '"stopped" page' in said and "freepod start" in said


def test_no_wait_returns_once_accepted(make_api, tmp_path):
    project_at(tmp_path, pointer=POINTER)
    platform = Platform([record()], answer=(200, record("stopped", "running")))
    _, said = run(make_api, platform, tmp_path, STOPPED, wait=False)
    assert "continues on the platform" in said
    assert len([p for m, p in platform.calls if m == "GET" and "deployments" in p]) == 1


def test_a_failed_change_reports_the_platforms_reason(make_api, tmp_path):
    project_at(tmp_path, pointer=POINTER)
    platform = Platform(
        [record(), record(status="error", last_error="timed out waiting for the condition")],
        answer=(200, record("stopped", "running")),
    )
    with pytest.raises(FreepodError, match="timed out waiting"):
        run(make_api, platform, tmp_path, STOPPED)


@pytest.mark.parametrize("target, state", [(RUNNING, "running"), (STOPPED, "stopped")])
def test_already_in_state_succeeds_without_a_request(make_api, tmp_path, target, state):
    project_at(tmp_path, pointer=POINTER)
    platform = Platform([record(state, state)])
    _, said = run(make_api, platform, tmp_path, target)
    assert f"already {state}" in said
    assert platform.posts() == []


def test_a_change_in_progress_is_followed(make_api, tmp_path):
    project_at(tmp_path, pointer=POINTER)
    platform = Platform([record("stopped", "running"), record("stopped", "stopped")])
    final, said = run(make_api, platform, tmp_path, STOPPED)
    assert "already stopping" in said
    assert platform.posts() == []
    assert final["power"]["applied"] == "stopped"


def test_a_failed_deployment_needs_a_deploy_first(make_api, tmp_path):
    project_at(tmp_path, pointer=POINTER)
    platform = Platform(
        [record("stopped", "stopped", status="error")],
        answer=(409, {"detail": "Deployment is error; only a ready deployment can be started", "code": "deployment_not_ready"}),
    )
    with pytest.raises(FreepodError, match="(?s)failed.*freepod deploy"):
        run(make_api, platform, tmp_path, RUNNING)


def test_a_payment_stop_cannot_be_started_from_the_cli(make_api, tmp_path):
    project_at(tmp_path, pointer=POINTER)
    platform = Platform(
        [record("stopped", "stopped", reason="payment")],
        answer=(409, {"detail": "Deployment is stopped for payment and cannot be started", "code": "not_startable"}),
    )
    with pytest.raises(FreepodError, match="stopped for payment"):
        run(make_api, platform, tmp_path, RUNNING)


def test_a_busy_deployment_is_worth_retrying(make_api, tmp_path):
    project_at(tmp_path, pointer=POINTER)
    platform = Platform([record()], answer=(409, {"detail": "A deployment job is already queued or running"}))
    with pytest.raises(FreepodError, match="worth retrying"):
        run(make_api, platform, tmp_path, STOPPED)


def test_stop_through_main(stub_api, cached_credential, tmp_path, monkeypatch, capsys):
    project_at(tmp_path, pointer=POINTER)
    stub_api(Platform([record(), record("stopped", "stopped")], answer=(200, record("stopped", "running"))))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["stop"]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Stopped." in captured.err


def test_start_outside_a_project_exits_two(stub_api, cached_credential, tmp_path, monkeypatch):
    stub_api(Platform([record()]))
    monkeypatch.chdir(tmp_path)
    assert main(["start"]) == EXIT_USAGE


def test_a_refusal_exits_one(stub_api, cached_credential, tmp_path, monkeypatch):
    project_at(tmp_path, pointer=POINTER)
    stub_api(Platform([record()], answer=(409, {"detail": "A deployment job is already queued or running"})))
    monkeypatch.chdir(tmp_path)
    assert main(["stop"]) == EXIT_ERROR
