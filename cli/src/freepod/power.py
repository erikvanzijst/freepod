"""Stopping and starting the deployment a project points at (cli-power).

Like `delete`, these address only the deployment recorded in `.freepod.json`.
Stopping keeps every piece of data and is undone by `freepod start`, so unlike
`delete` it asks for no confirmation. The platform applies the change in the
background; the client follows it until the applied power matches.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from . import FreepodError, UsageError
from .api import ApiClient, _json_detail
from .config import ROLLOUT_WAIT_SECONDS, env_suffix
from .delete import POLL_SECONDS, address, read_deployment
from .project import require_project

STOPPED = "stopped"
RUNNING = "running"
STATUS_ERROR = "error"

CODE_NOT_READY = "deployment_not_ready"
CODE_NOT_STARTABLE = "not_startable"
CODE_UNDER_MAINTENANCE = "under_maintenance"

_VERB = {STOPPED: "stop", RUNNING: "start"}
_DOING = {STOPPED: "Stopping", RUNNING: "Starting"}
_DONE = {STOPPED: "stopped", RUNNING: "started"}


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def power(deployment: Dict[str, Any]) -> Dict[str, Any]:
    return deployment.get("power") or {"desired": RUNNING, "applied": RUNNING}


def stopped_notice(deployment: Dict[str, Any]) -> Optional[str]:
    """What `deploy` says when it released to a stopped deployment."""
    if power(deployment).get("desired") != STOPPED:
        return None
    return (
        "The deployment is stopped and stays stopped: the release is applied, "
        "but nothing runs.\n  Run `freepod start` to run it."
    )


def _refusal(response, target: str) -> FreepodError:
    verb = _VERB[target]
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    code = payload.get("code") if isinstance(payload, dict) else None
    detail = _json_detail(response) or response.text.strip()[:300]
    if code == CODE_UNDER_MAINTENANCE:
        return FreepodError(
            "the deployment is stopped for platform maintenance and cannot be started now.\n"
            "  It returns to how it was once the maintenance ends; try again later."
        )
    if code == CODE_NOT_STARTABLE:
        return FreepodError(
            "the deployment is stopped for payment and cannot be started from the CLI.\n"
            "  Settle the subscription from the dashboard to run it again."
        )
    if code == CODE_NOT_READY:
        if "is error" in detail:
            return FreepodError(
                f"the deployment is failed, so it cannot be {_DONE[target]}.\n"
                f"  A successful `freepod deploy` is needed first."
            )
        return FreepodError(
            f"the deployment is not ready ({detail}).\n"
            f"  Wait for its current operation to finish, then run `freepod {verb}` again."
        )
    return FreepodError(
        "another operation on this deployment is already queued or running.\n"
        f"  This is worth retrying once it finishes: `freepod {verb}`."
    )


def request(api: ApiClient, user_id: int, deployment_id: str, target: str) -> Dict[str, Any]:
    response = api.post(f"/api/users/{user_id}/deployments/{deployment_id}/{_VERB[target]}")
    if response.status_code == 409:
        raise _refusal(response, target)
    if not response.is_success:
        raise FreepodError(
            f"could not {_VERB[target]} deployment {deployment_id}: HTTP "
            f"{response.status_code} {response.text.strip()[:300]}"
        )
    return response.json()


def wait_until_applied(
    api: ApiClient,
    user_id: int,
    deployment_id: str,
    target: str,
    *,
    timeout: int = ROLLOUT_WAIT_SECONDS,
    poll: float = POLL_SECONDS,
) -> Dict[str, Any]:
    """Poll until the applied power is `target`, or the platform reports a failure."""
    deadline = time.monotonic() + timeout
    while True:
        record = read_deployment(api, user_id, deployment_id)
        if record is None:
            raise FreepodError(f"deployment {deployment_id} no longer exists.")
        if record.get("status") == STATUS_ERROR:
            raise FreepodError(
                f"the platform could not {_VERB[target]} deployment {record.get('name')}.\n"
                f"  The platform recorded: {record.get('last_error') or 'no error message'}"
            )
        if power(record).get("applied") == target and power(record).get("desired") == target:
            return record
        if time.monotonic() >= deadline:
            raise FreepodError(
                f"stopped waiting after {timeout}s. The platform is still applying the "
                f"{_VERB[target]} of deployment {record.get('name')}; it was not canceled."
            )
        time.sleep(poll)


def change(
    api: ApiClient,
    env_name: str,
    target: str,
    *,
    root: Optional[Path] = None,
    wait: bool = True,
    timeout: int = ROLLOUT_WAIT_SECONDS,
    poll: float = POLL_SECONDS,
    echo: Callable[[str], None] = _log,
) -> Dict[str, Any]:
    """Stop or start the project's deployment. Returns the deployment as last read."""
    project = require_project(root)
    verb = _VERB[target]
    if project.env != env_name and project.deployment_id:
        raise UsageError(
            f"{project.path} records deployment '{project.deployment_name}' on "
            f"'{project.env}', not on '{env_name}'.\n"
            f"  Re-run without --env (or with --env {project.env}) to {verb} it."
        )
    if not project.deployment_id:
        raise UsageError(
            f"{project.path} records no deployment, so there is nothing to {verb}.\n"
            f"  Run `freepod deploy` to create one."
        )

    user_id = api.me()["id"]
    deployment_id = project.deployment_id
    record = read_deployment(api, user_id, deployment_id)
    if record is None:
        raise FreepodError(
            f"deployment {deployment_id} no longer exists{env_suffix(env_name)}.\n"
            f"  Run `freepod deploy` to create a new one."
        )
    name = record.get("name")
    current = power(record)

    if current.get("desired") == target and current.get("applied") == target:
        echo(f"Deployment '{name}' is already {target}.")
        return record
    if current.get("desired") == target:
        echo(f"Deployment '{name}' is already {_DOING[target].lower()}.")
    else:
        record = request(api, user_id, deployment_id, target)
        echo(f"{_DOING[target]} deployment '{name}'...")

    if not wait:
        echo(f"The {verb} continues on the platform.")
        return record

    record = wait_until_applied(api, user_id, deployment_id, target, timeout=timeout, poll=poll)
    live = address(record)
    if target == STOPPED:
        where = f"{live} shows" if live else "Visitors see"
        echo(f"Stopped. Its data is kept, and {where} a \"stopped\" page until you run `freepod start`.")
    else:
        echo(f"Started.{f' Live at {live}' if live else ''}")
    return record
