"""Deleting the deployment a project points at.

The mirror image of `deploy`, and deliberately the only destructive thing this
client does. It addresses the deployment recorded in `.freepod.json` and
nothing else: a command that could name an arbitrary deployment would be one
whose worst typo is unrecoverable, and the project file is the only place the
client knows a deployment by.

Teardown is asynchronous. `DELETE` answers **204** and moves the deployment to
`deleting`; the reconciler uninstalls the release and removes the namespace
afterwards, which is what actually destroys the volumes and frees the hostname.
The client therefore follows the teardown to `deleted` by default — not for
ceremony, but because the hostname stays claimed until it lands, so a `delete`
followed immediately by a `deploy` would otherwise collide with the deployment
it just removed.

The pointer is discarded from the project file the moment the platform accepts
the deletion, before the teardown is followed. From that instant the deployment
can never serve this project again — an update is refused for anything outside
`ready`/`error` — so keeping the pointer would only make the next `deploy`
fail on a deployment the user already asked to be rid of. The user values stay
put: the hostname is intent, and re-deploying should re-claim the same name.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import click

from . import FreepodError, UsageError
from .api import ApiClient, _json_detail
from .config import ROLLOUT_WAIT_SECONDS, env_suffix
from .deploy import describe_conflict
from .project import PROJECT_FILE, Project, require_project

#: Where a teardown ends. `deleted` is the record the platform keeps behind;
#: a 404 means it stopped keeping one, and both mean the same thing here.
STATUS_DELETED = "deleted"

#: In flight. Requesting a deletion again from here is accepted and changes
#: nothing, so it is a state to wait out rather than an error.
STATUS_DELETING = "deleting"

STATUS_ERROR = "error"

#: How often to re-read while following a teardown. Matched to the deploy
#: pipeline's cadence for the same reason: the reconciler's own work is
#: measured in tens of seconds.
POLL_SECONDS = 3.0


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _ask(question: str) -> bool:
    return click.confirm(question, default=False, err=True)


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


def read_deployment(
    api: ApiClient, user_id: int, deployment_id: str
) -> Optional[Dict[str, Any]]:
    """The deployment, or None if the platform no longer has it.

    A 404 is an ordinary answer here rather than a failure: the pointer lives
    in a committed file and outliving the deployment is exactly what it does.
    """
    response = api.get(f"/api/users/{user_id}/deployments/{deployment_id}")
    if response.status_code == 404:
        return None
    if not response.is_success:
        raise FreepodError(
            f"could not read deployment {deployment_id}: HTTP {response.status_code} "
            f"{response.text.strip()[:300]}"
        )
    return response.json()


def address(deployment: Dict[str, Any]) -> Optional[str]:
    hostname = deployment.get("hostname")
    return f"https://{hostname}" if hostname else None


# --------------------------------------------------------------------------
# Asking
# --------------------------------------------------------------------------


def present(deployment: Dict[str, Any], env_name: str, echo: Callable[[str], None]) -> None:
    """Show what is about to be destroyed, by name and by address.

    The name alone is not enough to recognize a deployment — they are generated
    and interchangeable at a glance — so the address is shown too. It is the
    part a user actually knows.
    """
    echo("")
    echo(f"About to delete deployment '{deployment.get('name')}'{env_suffix(env_name)}:")
    live = address(deployment)
    if live:
        echo(f"  address  {live}")
    echo(f"  status   {deployment.get('status')}")
    echo(f"  id       {deployment.get('id')}")
    echo("")
    echo(
        "This tears down the deployment and destroys everything it stores. It "
        "cannot be undone."
    )


def confirm(
    deployment: Dict[str, Any],
    env_name: str,
    *,
    assume_yes: bool,
    interactive: bool,
    echo: Callable[[str], None],
    ask: Callable[[str], bool],
) -> bool:
    """Whether to go ahead. `--yes` answers in advance; nothing else may.

    Without a terminal and without `--yes` this refuses rather than proceeding:
    an unattended run that deletes because nobody was there to object is the
    one behavior this command must not have.
    """
    if assume_yes:
        return True
    if not interactive:
        raise UsageError(
            "deleting a deployment needs confirmation and there is no terminal to "
            "ask on.\n"
            "  Re-run with --yes to confirm in advance. Nothing has been deleted."
        )

    present(deployment, env_name, echo)
    return ask(f"Delete '{deployment.get('name')}'?")


# --------------------------------------------------------------------------
# The request
# --------------------------------------------------------------------------


def request_deletion(api: ApiClient, user_id: int, deployment_id: str) -> None:
    """`DELETE /api/users/{user_id}/deployments/{deployment_id}`.

    Idempotent on the platform: deleting something already being deleted still
    answers 204. A 404 is treated as success for the same reason — the caller
    asked for the deployment to be gone, and it is.
    """
    response = api.delete(f"/api/users/{user_id}/deployments/{deployment_id}")
    if response.status_code == 404:
        return
    if response.status_code == 409:
        message, retryable = describe_conflict(_json_detail(response))
        if retryable:
            message = f"{message}\n  Nothing has been deleted."
        raise FreepodError(message)
    if response.status_code not in (200, 202, 204):
        raise FreepodError(
            f"could not delete deployment {deployment_id}: HTTP {response.status_code} "
            f"{response.text.strip()[:300]}"
        )


# --------------------------------------------------------------------------
# Following the teardown
# --------------------------------------------------------------------------


def wait_until_gone(
    api: ApiClient,
    user_id: int,
    deployment_id: str,
    *,
    timeout: int = ROLLOUT_WAIT_SECONDS,
    poll: float = POLL_SECONDS,
    echo: Callable[[str], None] = _log,
) -> None:
    """Poll until the deployment is `deleted`, or the platform says it failed.

    A teardown that raises leaves the deployment in `error` with `last_error`
    set, exactly as a failed rollout does. Waiting that out to the timeout
    would report "still deleting" for something the platform has already given
    up on, so it is read as the failure it is.
    """
    reported: Optional[str] = None
    deadline = time.monotonic() + timeout

    while True:
        record = read_deployment(api, user_id, deployment_id)
        if record is None:
            return

        status = record.get("status")
        if status == STATUS_DELETED:
            return
        if status == STATUS_ERROR:
            raise FreepodError(
                f"the teardown of deployment {deployment_id} failed on the platform.\n"
                f"  The platform recorded: {record.get('last_error') or 'no error message'}\n"
                f"  The deployment may still hold its hostname. Delete it from "
                f"{api.env.api_base} once the cause is resolved."
            )

        if status != reported:
            echo(f"  {status}...")
            reported = status

        if time.monotonic() >= deadline:
            raise FreepodError(
                f"stopped waiting after {timeout}s. Deployment {deployment_id} is "
                f"still being torn down on the platform — the deletion was not "
                f"canceled, and {PROJECT_FILE} no longer points at it."
            )
        time.sleep(poll)


# --------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------


def delete(
    api: ApiClient,
    env_name: str,
    *,
    root: Optional[Path] = None,
    assume_yes: bool = False,
    wait: bool = True,
    interactive: bool = True,
    timeout: int = ROLLOUT_WAIT_SECONDS,
    poll: float = POLL_SECONDS,
    echo: Callable[[str], None] = _log,
    ask: Callable[[str], bool] = _ask,
) -> bool:
    """Delete this project's deployment. Returns whether anything was deleted.

    A declined confirmation returns False rather than raising: the user was
    asked and answered, which is not a failure of the command.
    """
    project = require_project(root)

    if project.env != env_name and project.deployment_id:
        # The recorded deployment is minted on another environment. Naming it
        # rather than refusing opaquely keeps the pointer safe: a delete that
        # silently did nothing on the wrong environment would read as success.
        raise UsageError(
            f"{project.path} records deployment "
            f"'{project.deployment_name}' on '{project.env}', not on "
            f"'{env_name}'.\n"
            f"  Re-run without --env (or with --env {project.env}) to delete it."
        )

    if not project.deployment_id:
        raise UsageError(
            f"{project.path} records no deployment, so there is nothing to delete.\n"
            f"  Run `freepod deploy` to create one."
        )

    # `/api/me` first, as everywhere: it is the request that actually exercises
    # the credential, and the deployment read below is scoped by its answer.
    user_id = api.me()["id"]
    deployment_id = project.deployment_id
    record = read_deployment(api, user_id, deployment_id)

    if record is None:
        # Gone already — deleted from the web UI, or from another checkout.
        # Clearing the stale pointer is the whole of what is left to do.
        name = project.deployment_name
        echo(
            f"Deployment {deployment_id}{f' ({name})' if name else ''} no longer "
            f"exists{env_suffix(env_name)}; nothing to delete."
        )
        _forget(project, echo)
        return False

    status = record.get("status")
    if status in (STATUS_DELETING, STATUS_DELETED):
        # The platform has already accepted a deletion for this one, so there
        # is nothing to confirm: the destructive decision was made earlier.
        echo(f"Deployment '{record.get('name')}' is already {status}.")
        _forget(project, echo)
        if wait and status == STATUS_DELETING:
            wait_until_gone(
                api, user_id, deployment_id, timeout=timeout, poll=poll, echo=echo
            )
            echo("Deleted.")
        return False

    if not confirm(
        record,
        env_name,
        assume_yes=assume_yes,
        interactive=interactive,
        echo=echo,
        ask=ask,
    ):
        echo("Nothing was deleted.")
        return False

    request_deletion(api, user_id, deployment_id)
    echo(f"Deleting deployment '{record.get('name')}' ({deployment_id})...")

    # Discarded now, not after the wait: the deployment is on its way out and
    # can never serve this project again, so an interrupted wait must not leave
    # the project pointing at it.
    _forget(project, echo)

    if wait:
        wait_until_gone(api, user_id, deployment_id, timeout=timeout, poll=poll, echo=echo)
        echo("Deleted.")
    else:
        echo(
            "Teardown continues on the platform. Its hostname stays claimed until "
            "it finishes."
        )
    return True


def _forget(project: Project, echo: Callable[[str], None]) -> None:
    project.forget_deployment()
    echo(f"Removed the deployment from {project.path}.")
