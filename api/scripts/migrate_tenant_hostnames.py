"""Move every live deployment from `<app>.<handle>.<domain>` to
`<app>-<handle>.<tenant_domain>`.

A one-off for the flat-tenant-hostnames change, deleted once both environments
are migrated. Copy it into the API pod and run it there:

    python scripts/migrate_tenant_hostnames.py           # dry run
    python scripts/migrate_tenant_hostnames.py --apply   # rewrite and reconcile

Each move is an ordinary deployment update with the hostname rewritten
everywhere it appears in the user values, so it is validated by the current
rules, recorded as a release and reconciled. Running it again finds nothing
left to do. It ends by printing the `legacy_tenant_redirects` entry for
`tf/app/secrets.auto.tfvars`.
"""

from __future__ import annotations

import argparse
import copy
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from app.config import CaelusSettings, get_settings  # noqa: E402
from app.models import DeploymentORM, DeploymentUpdate  # noqa: E402
from app.services import deployments as deployment_service  # noqa: E402
from app.services.errors import CaelusException  # noqa: E402
from app.services.reconcile_constants import DEPLOYMENT_STATUS_DELETED  # noqa: E402
from app.util import set_value_at_path, value_for_path  # noqa: E402


@dataclass
class Move:
    deployment_id: UUID
    user_id: int
    old: str
    new: str


def new_hostname(old: str, *, handle: str | None, settings: CaelusSettings) -> str | None:
    """`<app>-<handle>.<tenant_domain>` for an old-pattern name under the
    owner's own handle, or None for any other name."""
    suffix = f".{settings.domain}"
    if not settings.domain or not old.endswith(suffix):
        return None
    labels = old[: -len(suffix)].split(".")
    if len(labels) != 2 or not handle or labels[1] != handle:
        return None
    return f"{labels[0]}-{handle}.{settings.tenant_domain}"


def plan(session: Session, settings: CaelusSettings) -> list[Move]:
    moves = []
    live = session.exec(
        select(DeploymentORM).where(DeploymentORM.status != DEPLOYMENT_STATUS_DELETED)
    ).all()
    for deployment in live:
        if not deployment.hostname:
            continue
        new = new_hostname(
            deployment.hostname.lower(), handle=deployment.user.handle, settings=settings
        )
        if new is not None:
            moves.append(Move(deployment.id, deployment.user_id, deployment.hostname, new))
    return sorted(moves, key=lambda move: move.old)


def rewritten_values(deployment: DeploymentORM, old: str, new: str) -> dict[str, Any]:
    """The user values with every hostname-titled path that holds *old* set
    to *new*, found by the walk the deployment service uses."""
    values = copy.deepcopy(deployment.user_values_json or {})
    schema = deployment.desired_template.values_schema_json or {}
    for path in deployment_service._iter_hostname_paths(schema):
        value = value_for_path(values, path)
        if isinstance(value, str) and value.lower() == old.lower():
            set_value_at_path(values, path, new)
    return values


def apply(session: Session, move: Move) -> None:
    deployment = session.get(DeploymentORM, move.deployment_id)
    deployment_service.update_deployment(
        session,
        DeploymentUpdate(
            id=deployment.id,
            user_id=deployment.user_id,
            desired_template_id=deployment.desired_template_id,
            user_values_json=rewritten_values(deployment, move.old, move.new),
        ),
    )


def redirects_snippet(moves: list[Move], settings: CaelusSettings) -> str:
    workspace = "prod" if settings.environment == "prod" else "default"
    lines = [f"  {workspace} = ["] + [f'    "{move.old}",' for move in moves] + ["  ]"]
    return "\n".join(["legacy_tenant_redirects = {", *lines, "}"])


def run(session: Session, *, settings: CaelusSettings, dry_run: bool, out=print) -> list[Move]:
    """Plan, and unless *dry_run*, apply every move. Returns the moves that
    were (or, in a dry run, would be) made."""
    done = []
    for move in plan(session, settings):
        if dry_run:
            out(f"would move {move.old} -> {move.new}")
            done.append(move)
            continue
        try:
            apply(session, move)
        except CaelusException as exc:
            session.rollback()
            out(f"FAILED {move.old} -> {move.new}: {exc}")
            continue
        out(f"moved {move.old} -> {move.new}")
        done.append(move)
    if not done:
        out("Nothing to move.")
    else:
        out("")
        out(redirects_snippet(done, settings))
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="rewrite and queue reconciles")
    args = parser.parse_args(argv)

    from app.db import session_scope

    with session_scope() as session:
        run(session, settings=get_settings(), dry_run=not args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
