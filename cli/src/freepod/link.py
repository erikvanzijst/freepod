"""`freepod link`: point a project at a deployment that already exists.

For a lost project file, a fresh clone without one, or a second machine. A
new file gets the deployment's managed fields back, so the next apply claims
them again rather than giving them up; an existing file keeps its keys, and
link reports how they differ instead of sending them.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import click

from . import FreepodError, UsageError
from .api import ApiClient
from .deploy import read_deployment
from .fields import list_deployments, named
from .picker import pick as pick_one
from .project import DEFAULT_ENV, IDENTITY_KEYS, PROJECT_FILE, Project, load


def _log(message: str) -> None:
    click.echo(message, err=True)


def link(
    api: ApiClient,
    root: Path,
    target: Optional[str],
    *,
    force: bool = False,
    pick: Optional[Callable[[List[Dict[str, Any]]], Optional[Dict[str, Any]]]] = None,
    echo: Callable[[str], None] = _log,
) -> Project:
    """Record the deployment `target` names, or the one picked. Returns the project."""
    existing = load(root) if (root / PROJECT_FILE).exists() else None
    if existing is not None and existing.deployment_id and not force:
        raise UsageError(
            f"{existing.path} already records deployment {existing.deployment_id}.\n"
            f"  Re-run with --force to point it at another deployment; the current "
            f"one is left as it is."
        )
    if target is None and not sys.stdin.isatty():
        raise UsageError(
            "no deployment named and no terminal to pick one on: run `freepod link <name-or-id>`"
        )

    user_id = api.me()["id"]
    deployments = list_deployments(api, user_id)
    if not deployments:
        raise FreepodError(
            f"you have no deployments on '{api.env.name}' to link.\n"
            f"  Run `freepod init` to create one."
        )
    if target is None:
        chosen = (pick or pick_deployment)(deployments)
        if chosen is None:
            raise click.Abort()
    else:
        chosen = _find(deployments, target)
        if chosen is None:
            raise FreepodError(
                f"none of your deployments on '{api.env.name}' is named or has the id "
                f"'{target}'.\n"
                f"  Run `freepod link` on a terminal to pick one, or `freepod init` to "
                f"create a new one."
            )

    record = read_deployment(api, user_id, chosen["id"])

    if existing is not None and existing.deployment_id:
        previous = next((d for d in deployments if d.get("id") == existing.deployment_id), None)
        label = f"'{previous['name']}'" if previous else existing.deployment_id
        echo(f"No longer pointing at deployment {label}; it is left as it is.")

    if existing is None:
        project = Project(root=root, fields=_managed_values(record))
        if "icon" in (record.get("managed_fields") or []):
            echo(
                f"The deployment's icon is managed by its project file, which held a "
                f"path to the image. Add `icon` back to {PROJECT_FILE}, or the next "
                f"`freepod apply` gives it up."
            )
    else:
        project = existing
        _report_differences(project, record, echo)

    project.declared_env = None if api.env.name == DEFAULT_ENV else api.env.name
    project.record_deployment(record["id"], api.env.api_base)
    echo(f"Linked to '{record.get('name')}' ({record['id']}).")
    return project


def _find(deployments: List[Dict[str, Any]], target: str) -> Optional[Dict[str, Any]]:
    by_id = next((d for d in deployments if d.get("id") == target), None)
    return by_id or named(deployments, target)


def _current(record: Dict[str, Any], key: str) -> Any:
    if key in IDENTITY_KEYS:
        return record.get(key)
    return (record.get("user_values_json") or {}).get(key)


def _managed_values(record: Dict[str, Any]) -> Dict[str, Any]:
    """The deployment's managed fields with their values, the icon left out:
    reads carry its URL, not the path the file held."""
    values: Dict[str, Any] = {}
    for key in record.get("managed_fields") or []:
        if key == "icon":
            continue
        value = _current(record, key)
        if value is not None:
            values[key] = value
    return values


def _report_differences(
    project: Project, record: Dict[str, Any], echo: Callable[[str], None]
) -> None:
    differing = sorted(
        key
        for key in project.fields
        if key != "icon" and project.fields[key] != _current(record, key)
    )
    given_up = sorted(set(record.get("managed_fields") or []) - set(project.fields))
    if differing:
        echo(
            f"{PROJECT_FILE} differs from the deployment in: {', '.join(differing)}. "
            f"Nothing was sent; run `freepod apply` to send them."
        )
    if given_up:
        echo(
            f"The deployment's {', '.join(given_up)} "
            f"{'is' if len(given_up) == 1 else 'are'} managed by a project file but not "
            f"in {PROJECT_FILE}: the next `freepod apply` gives "
            f"{'it' if len(given_up) == 1 else 'them'} up."
        )


# --------------------------------------------------------------------------
# The picker
# --------------------------------------------------------------------------


def _product(record: Dict[str, Any]) -> str:
    template = record.get("desired_template") or {}
    return str((template.get("product") or {}).get("name") or "")


def _rows(deployments: List[Dict[str, Any]]) -> List[str]:
    names = [str(d.get("name") or "") for d in deployments]
    hosts = [str(d.get("hostname") or "") for d in deployments]
    name_width = max(len(n) for n in names)
    host_width = max(len(h) for h in hosts)
    return [
        f"{n.ljust(name_width)}  {h.ljust(host_width)}  {_product(d)}".rstrip()
        for n, h, d in zip(names, hosts, deployments)
    ]


def pick_deployment(
    deployments: List[Dict[str, Any]], *, input: Any = None, output: Any = None
) -> Optional[Dict[str, Any]]:
    """Let the user pick one deployment: arrows move, typing narrows, Enter picks.

    Returns None when the user gives up with Escape or Ctrl-C.
    """
    return pick_one(
        deployments,
        _rows(deployments),
        title="Link which deployment? Type to narrow, ↑↓ to move, Enter to pick.",
        empty="no deployment matches",
        input=input,
        output=output,
    )
