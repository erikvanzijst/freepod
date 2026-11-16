"""`freepod apply`: send the project file to its deployment, without building.

One update carries the file's identity keys, the deployment's stored chart
values with the file's keys over them, and the file's keys as
`managed_fields`. The platform releases only when the running app would
change; a rename, say, is a row update. Staged vars are rolled out by naming
the build the deployment runs, which releases.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import click

from . import FreepodError, UsageError
from . import deploy as deploy_module
from .api import ApiClient
from .fields import claimed_body
from .project import IDENTITY_KEYS, PROJECT_FILE, Project, require_project
from .values import check_public_patterns


def _log(message: str) -> None:
    click.echo(message, err=True)


def apply(
    api: ApiClient,
    env_name: str,
    *,
    root: Optional[Path] = None,
    extra: Optional[Dict[str, Any]] = None,
    timeout: int = deploy_module.ROLLOUT_WAIT_SECONDS,
    poll: float = deploy_module.POLL_SECONDS,
    echo: Callable[[str], None] = _log,
) -> Optional[str]:
    """Apply the project file. Returns the address once any release is live."""
    project = linked_project(root, env_name, "apply")
    claimed = claimed_body(project)
    check_public_patterns(project.chart_values)

    user_id = api.me()["id"]
    record = deploy_module.read_linked(api, user_id, project)

    stored = dict(record.get("user_values_json") or {})
    values = {**stored, **project.chart_values}
    body: Dict[str, Any] = {"user_values_json": values, **claimed, **(extra or {})}
    releasing = values != stored or "build_id" in body
    if record.get("pending") and "build_id" not in body:
        build = (record.get("applied_release") or {}).get("build_id")
        if build:
            body["build_id"] = str(build)
            releasing = True
        else:
            echo("Pending vars stay pending until the next `freepod deploy`, which builds.")

    changes = describe_changes(project, record)
    if releasing:
        record = deploy_module.wait_until_settled(
            api, user_id, record, timeout=timeout, poll=poll, echo=echo
        )
    updated = deploy_module.put_update(api, user_id, record["id"], body)

    for line in changes:
        echo(line)
    released = updated.get("generation", 0) > record.get("generation", 0)
    if not changes and not released:
        echo("Nothing changed.")
    if not released:
        return deploy_module.address(updated)

    echo(f"Rolling out '{updated.get('name')}'...")
    return deploy_module.finish_rollout(
        api, user_id, updated, timeout=timeout, poll=poll, echo=echo
    )


def linked_project(root: Optional[Path], env_name: str, verb: str) -> Project:
    """The project, refused when it records no deployment or one on another environment."""
    project = require_project(root)
    if project.deployment_id and project.env != env_name:
        raise UsageError(
            f"{project.path} records deployment {project.deployment_id} on "
            f"'{project.env}', but this command targets '{env_name}'.\n"
            f"  Re-run without --env, or run `freepod init --force` on '{env_name}' "
            f"to point this project there."
        )
    if not project.deployment_id:
        raise FreepodError(
            f"{project.path} records no deployment, so there is nothing to {verb} to.\n"
            f"  Run `freepod init` to create one, or `freepod link` to point this "
            f"project at an existing one."
        )
    return project


def _current(record: Dict[str, Any], key: str) -> Any:
    if key in IDENTITY_KEYS:
        return record.get(key)
    return (record.get("user_values_json") or {}).get(key)


def _shown(value: Any) -> str:
    return "(unset)" if value is None else json.dumps(value, ensure_ascii=False)


def describe_changes(project: Project, record: Dict[str, Any]) -> List[str]:
    """One line per file key whose value differs from the deployment's, the icon left out."""
    lines = []
    for key in sorted(project.fields):
        if key == "icon":
            continue
        old, new = _current(record, key), project.fields[key]
        if old == new:
            continue
        multiline = any(isinstance(v, str) and "\n" in v for v in (old, new))
        lines.append(f"{key}: changed" if multiline else f"{key}: {_shown(old)} → {_shown(new)}")
    released = sorted(set(record.get("managed_fields") or []) - set(project.fields))
    if released:
        lines.append(
            f"No longer managed by {PROJECT_FILE}: {', '.join(released)} (values unchanged)."
        )
    return lines


def unapplied_keys(project: Project, record: Dict[str, Any]) -> List[str]:
    """The file's keys, other than `icon`, whose value the deployment does not have."""
    return sorted(
        key
        for key in project.fields
        if key != "icon" and project.fields[key] != _current(record, key)
    )


def warn_unapplied(project: Project, record: Dict[str, Any], echo: Callable[[str], None]) -> None:
    """One line naming `freepod apply` when the file holds changes the deployment lacks."""
    keys = unapplied_keys(project, record)
    if keys:
        echo(
            f"Warning: {PROJECT_FILE} has changes not yet applied ({', '.join(keys)}). "
            f"Run `freepod apply` to send them."
        )
