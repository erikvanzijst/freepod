"""`freepod delete`: confirmation, the request, and following the teardown."""

from __future__ import annotations

import json
import re

import httpx
import pytest

from freepod import EXIT_OK, EXIT_USAGE, FreepodError, UsageError
from freepod.cli import main
from freepod.delete import delete, wait_until_gone
from freepod.project import load

from conftest import json_response
from test_deploy import deployment, project_at

POINTER = {"id": deployment()["id"], "name": "custom-d8dtx4"}


class Platform:
    """A scripted API covering the reads and the one write a delete performs.

    `reads` is the queue successive `GET .../deployments/{id}` calls return,
    repeating the last forever — which is how a teardown is scripted without a
    clock. `None` in the queue is the platform having forgotten the deployment.
    """

    def __init__(
        self,
        *,
        user_id=7,
        reads=None,
        delete_status=204,
        delete_detail=None,
    ):
        self.user_id = user_id
        self.reads = list(reads) if reads is not None else [deployment()]
        self.delete_status = delete_status
        self.delete_detail = delete_detail
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        self.calls.append((method, path))

        if path == "/api/me":
            return json_response(200, {"id": self.user_id, "email": "dev@example.com"})

        if re.fullmatch(r"/api/users/\d+/deployments/[^/]+", path):
            if method == "DELETE":
                if self.delete_detail is not None:
                    return json_response(
                        self.delete_status, {"detail": self.delete_detail}
                    )
                return httpx.Response(self.delete_status)
            record = self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]
            if record is None:
                return json_response(404, {"detail": "Deployment not found"})
            return json_response(200, record)

        return json_response(404, {"detail": "Not Found"})

    def paths(self, method=None):
        return [p for m, p in self.calls if method is None or m == method]

    @property
    def deletions(self):
        return self.paths("DELETE")


def run(make_api, platform, tmp_path, **kwargs):
    api, _, _ = make_api(platform)
    kwargs.setdefault("assume_yes", True)
    kwargs.setdefault("echo", lambda _m: None)
    # `no_sleep` frees the poll but leaves `time.monotonic` real, so a
    # mis-scripted read queue fails fast instead of waiting out the default.
    kwargs.setdefault("timeout", 5)
    return delete(api, "prod", root=tmp_path, poll=0, **kwargs)


def refuse(_question):
    return False


def accept(_question):
    return True


# --------------------------------------------------------------------------
# What must exist before anything is asked
# --------------------------------------------------------------------------


def test_delete_needs_a_project(make_api, tmp_path):
    with pytest.raises(UsageError) as raised:
        run(make_api, Platform(), tmp_path)

    assert "not initialized" in str(raised.value)


def test_a_project_with_no_deployment_has_nothing_to_delete(make_api, tmp_path):
    project_at(tmp_path, pointer=None)
    platform = Platform()

    with pytest.raises(UsageError) as raised:
        run(make_api, platform, tmp_path)

    assert "records no deployment" in str(raised.value)
    # Not even a credential was spent on a question the file already answers.
    assert platform.calls == []


def test_a_project_for_another_environment_is_named_rather_than_touched(
    make_api, tmp_path
):
    """A delete on the wrong environment must not read as success, so the
    deployment is named where it actually lives."""
    platform = Platform()
    project_at(tmp_path, pointer=POINTER, env="dev")

    with pytest.raises(UsageError) as raised:
        run(make_api, platform, tmp_path)

    message = str(raised.value)
    assert "'dev'" in message and "'prod'" in message
    assert "Re-run without --env" in message
    # Nothing was read from the platform: the file already answers.
    assert platform.calls == []


def test_the_credential_is_exercised_before_the_deployment_is_read(make_api, tmp_path):
    """`/api/me` first, as everywhere: the read below is scoped by its answer."""
    project_at(tmp_path, pointer=POINTER)
    platform = Platform(reads=[deployment(), None])

    run(make_api, platform, tmp_path)

    assert platform.paths()[0] == "/api/me"


# --------------------------------------------------------------------------
# Confirmation
# --------------------------------------------------------------------------


def test_a_declined_delete_deletes_nothing(make_api, tmp_path):
    project_at(tmp_path, pointer=POINTER)
    platform = Platform()

    assert run(make_api, platform, tmp_path, assume_yes=False, ask=refuse) is False

    assert platform.deletions == []
    assert load(tmp_path).deployment_id == POINTER["id"]


def test_a_declined_delete_is_not_an_error(make_api, tmp_path, capsys):
    """The user was asked and answered. Reporting that as a failure would tell
    them they did something wrong by saying no."""
    project_at(tmp_path, pointer=POINTER)
    messages = []

    run(
        make_api,
        Platform(),
        tmp_path,
        assume_yes=False,
        ask=refuse,
        echo=messages.append,
    )

    assert "Nothing was deleted." in messages


def test_without_a_terminal_and_without_yes_nothing_is_deleted(make_api, tmp_path):
    """An unattended run must not delete because nobody was there to object."""
    project_at(tmp_path, pointer=POINTER)
    platform = Platform()

    with pytest.raises(UsageError) as raised:
        run(make_api, platform, tmp_path, assume_yes=False, interactive=False)

    assert "--yes" in str(raised.value)
    assert platform.deletions == []
    assert load(tmp_path).deployment_id == POINTER["id"]


def test_yes_asks_nothing(make_api, tmp_path):
    project_at(tmp_path, pointer=POINTER)

    def explode(_question):
        raise AssertionError("--yes must not prompt")

    assert run(make_api, Platform(reads=[deployment(), None]), tmp_path, ask=explode)


def test_the_question_names_the_deployment_and_its_address(make_api, tmp_path):
    """A generated name is not recognizable on its own; the address is what the
    user actually knows the deployment by."""
    project_at(tmp_path, pointer=POINTER)
    messages = []
    asked = []

    run(
        make_api,
        Platform(reads=[deployment(), None]),
        tmp_path,
        assume_yes=False,
        ask=lambda question: asked.append(question) or True,
        echo=messages.append,
    )

    shown = "\n".join(messages)
    assert "custom-d8dtx4" in shown
    assert "https://myapp.erik.freepod.eu" in shown
    assert "cannot be undone" in shown
    assert "custom-d8dtx4" in asked[0]


# --------------------------------------------------------------------------
# The request
# --------------------------------------------------------------------------


def test_a_confirmed_delete_issues_the_delete_and_clears_the_pointer(make_api, tmp_path):
    project_at(tmp_path, pointer=POINTER)
    platform = Platform(reads=[deployment(), None])

    assert run(make_api, platform, tmp_path) is True

    assert platform.deletions == [f"/api/users/7/deployments/{POINTER['id']}"]
    assert load(tmp_path).deployment is None


def test_the_user_values_survive_the_deletion(make_api, tmp_path):
    """The pointer is the only thing the deployment owned. The hostname is
    intent, so a later `deploy` re-claims the same name."""
    project_at(tmp_path, pointer=POINTER)

    run(make_api, Platform(reads=[deployment(), None]), tmp_path)

    assert load(tmp_path).user_values == {"hostname": "myapp.erik.freepod.eu"}


def test_the_pointer_is_cleared_before_the_teardown_is_followed(make_api, tmp_path):
    """An interrupted or timed-out wait must not leave the project pointing at
    a deployment that is on its way out."""
    project_at(tmp_path, pointer=POINTER)

    with pytest.raises(FreepodError):
        run(
            make_api,
            Platform(reads=[deployment(), deployment(status="deleting")]),
            tmp_path,
            timeout=0,
        )

    assert load(tmp_path).deployment is None


def test_an_operation_already_in_progress_is_reported_as_worth_retrying(
    make_api, tmp_path
):
    project_at(tmp_path, pointer=POINTER)
    platform = Platform(
        delete_status=409,
        delete_detail="A deployment job is already queued or running",
    )

    with pytest.raises(FreepodError) as raised:
        run(make_api, platform, tmp_path)

    message = str(raised.value)
    assert "already queued or running" in message
    assert "Nothing has been deleted." in message
    # The refusal was the platform's, so the pointer still describes reality.
    assert load(tmp_path).deployment_id == POINTER["id"]


def test_an_unexpected_status_is_reported_verbatim(make_api, tmp_path):
    project_at(tmp_path, pointer=POINTER)
    platform = Platform(delete_status=500, delete_detail="boom")

    with pytest.raises(FreepodError) as raised:
        run(make_api, platform, tmp_path)

    assert "HTTP 500" in str(raised.value)
    assert load(tmp_path).deployment_id == POINTER["id"]


def test_a_404_on_the_delete_is_success(make_api, tmp_path):
    """It disappeared between the read and the delete. The caller asked for it
    to be gone, and it is."""
    project_at(tmp_path, pointer=POINTER)
    platform = Platform(reads=[deployment(), None], delete_status=404)

    assert run(make_api, platform, tmp_path) is True
    assert load(tmp_path).deployment is None


# --------------------------------------------------------------------------
# Deployments that are already going, or already gone
# --------------------------------------------------------------------------


def test_a_deployment_that_no_longer_exists_leaves_only_the_stale_pointer(
    make_api, tmp_path
):
    project_at(tmp_path, pointer=POINTER)
    platform = Platform(reads=[None])
    messages = []

    assert run(make_api, platform, tmp_path, echo=messages.append) is False

    assert platform.deletions == []
    assert load(tmp_path).deployment is None
    assert "no longer exists" in "\n".join(messages)


def test_a_deployment_already_being_torn_down_is_not_asked_about(make_api, tmp_path):
    """The destructive decision was made earlier; asking again would imply this
    run could still prevent it."""
    project_at(tmp_path, pointer=POINTER)
    platform = Platform(reads=[deployment(status="deleting"), None])

    def explode(_question):
        raise AssertionError("a deletion already under way must not be re-confirmed")

    assert run(make_api, platform, tmp_path, assume_yes=False, ask=explode) is False

    assert platform.deletions == []
    assert load(tmp_path).deployment is None


# --------------------------------------------------------------------------
# Following the teardown
# --------------------------------------------------------------------------


def test_the_wait_ends_when_the_platform_forgets_the_deployment(make_api):
    """A fully torn-down deployment answers 404, not `deleted` — the platform
    stops serving the record once it is gone."""
    platform = Platform(reads=[deployment(status="deleting"), None])
    api, _, _ = make_api(platform)

    wait_until_gone(api, 7, POINTER["id"], timeout=5, poll=0, echo=lambda _m: None)


def test_the_wait_ends_on_the_deleted_status(make_api):
    platform = Platform(reads=[deployment(status="deleted")])
    api, _, _ = make_api(platform)

    wait_until_gone(api, 7, POINTER["id"], timeout=5, poll=0, echo=lambda _m: None)


def test_a_failed_teardown_is_reported_rather_than_waited_out(make_api):
    """The reconciler records a failed teardown as `error`, exactly as it does
    a failed rollout. Waiting it out would report 'still deleting' for
    something the platform has already given up on."""
    platform = Platform(
        reads=[deployment(status="deleting"), deployment(status="error", last_error="helm timed out")]
    )
    api, _, _ = make_api(platform)

    with pytest.raises(FreepodError) as raised:
        wait_until_gone(api, 7, POINTER["id"], timeout=5, poll=0, echo=lambda _m: None)

    message = str(raised.value)
    assert "teardown" in message
    assert "helm timed out" in message


def test_a_teardown_timeout_says_the_deletion_was_not_canceled(make_api):
    platform = Platform(reads=[deployment(status="deleting")])
    api, _, _ = make_api(platform)

    with pytest.raises(FreepodError) as raised:
        wait_until_gone(api, 7, POINTER["id"], timeout=0, poll=0, echo=lambda _m: None)

    message = str(raised.value)
    assert "stopped waiting" in message
    assert "not canceled" in message


def test_no_wait_stops_once_the_teardown_is_scheduled(make_api, tmp_path):
    project_at(tmp_path, pointer=POINTER)
    platform = Platform(reads=[deployment()])

    run(make_api, platform, tmp_path, wait=False)

    # One read in preflight and no more: nothing was followed.
    reads = [p for m, p in platform.calls if m == "GET" and "deployments" in p]
    assert len(reads) == 1


# --------------------------------------------------------------------------
# Through `main`
# --------------------------------------------------------------------------


def test_delete_writes_nothing_to_stdout(stub_api, cached_credential, tmp_path, monkeypatch, capsys):
    """A deletion has no result to pipe."""
    project_at(tmp_path, pointer=POINTER)
    stub_api(Platform(reads=[deployment(), None]))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    assert main(["delete", "--yes"]) == EXIT_OK

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Deleted." in captured.err


def test_delete_without_a_terminal_exits_two(stub_api, cached_credential, tmp_path, monkeypatch, capsys):
    project_at(tmp_path, pointer=POINTER)
    stub_api(Platform())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    assert main(["delete"]) == EXIT_USAGE

    assert "no terminal" in capsys.readouterr().err
    assert json.loads((tmp_path / ".freepod.json").read_text())["deployment"] == POINTER
