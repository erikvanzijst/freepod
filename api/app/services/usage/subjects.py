"""Who an allocation belongs to: a stable reference, its namespace, its deployment.

Attribution is read from the `deployment` table, never from the measurement source's
labels, which vanish with the namespace. An unresolved controller is recorded rather
than skipped: see the design's "Unattributable is not unavailable".
"""

from __future__ import annotations

import logging

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select

from app.models import DeploymentORM, UsageSubjectORM
from app.models.usage import SubjectKind
from app.services.usage.opencost import Allocation

logger = logging.getLogger(__name__)

# Not OpenCost's `__unallocated__`: a vendor token in a stored identity would be wrong
# the day upstream renames it.
UNRESOLVED = "unresolved"


def subject_ref(allocation: Allocation) -> str:
    """Stable for this container's lifetime; pod names are not."""
    kind = allocation.controller_kind or UNRESOLVED
    controller = allocation.controller or UNRESOLVED
    return f"{allocation.namespace}/{kind}/{controller}/{allocation.container}"


def is_degraded(ref: str) -> bool:
    """Whether this reference was recorded without a resolved workload."""
    parts = ref.split("/")
    return len(parts) == 4 and parts[1] == UNRESOLVED


def deployment_ids_by_namespace(session: Session, namespaces: set[str]) -> dict:
    """Namespace -> owning deployment id, for the namespaces that resolve.

    Deleted deployments are included: a past period must stay attributable.
    """
    if not namespaces:
        return {}
    rows = session.exec(
        select(DeploymentORM.namespace, DeploymentORM.id).where(
            DeploymentORM.namespace.in_(namespaces)
        )
    ).all()
    return {namespace: deployment_id for namespace, deployment_id in rows}


def upsert_subject(
    session: Session,
    *,
    ref: str,
    namespace: str | None,
    deployment_id=None,
    observed_at: datetime,
    kind: SubjectKind = SubjectKind.CONTAINER,
) -> int:
    """Get or create the subject, returning its id.

    One statement, so concurrent samplers settle on the unique constraint.
    `deployment_id` is only ever filled in, never cleared: a later window that fails to
    resolve must not undo a backfill.
    """
    table = UsageSubjectORM.__table__
    statement = insert(table).values(
        kind=kind.value,
        ref=ref,
        namespace=namespace,
        deployment_id=deployment_id,
        first_seen_at=observed_at,
        last_seen_at=observed_at,
    )
    return session.execute(
        statement.on_conflict_do_update(
            index_elements=["kind", "ref"],
            set_={
                "last_seen_at": statement.excluded.last_seen_at,
                "deployment_id": func.coalesce(
                    table.c.deployment_id, statement.excluded.deployment_id
                ),
            },
        ).returning(table.c.id)
    ).scalar_one()


def resolve_subjects(
    session: Session, allocations: list[Allocation], *, observed_at: datetime
) -> dict[str, int]:
    """Subject reference -> subject id, for every allocation in a window.

    Platform namespaces resolve to no deployment and are still recorded.
    """
    namespaces = {a.namespace for a in allocations if a.namespace}
    owners = deployment_ids_by_namespace(session, namespaces)

    subjects: dict[str, int] = {}
    unresolved_namespaces = set()
    for allocation in allocations:
        ref = subject_ref(allocation)
        if ref in subjects:
            continue
        deployment_id = owners.get(allocation.namespace)
        if deployment_id is None:
            unresolved_namespaces.add(allocation.namespace)
        subjects[ref] = upsert_subject(
            session,
            ref=ref,
            namespace=allocation.namespace,
            deployment_id=deployment_id,
            observed_at=observed_at,
        )

    if unresolved_namespaces:
        logger.debug(
            "Namespaces with no deployment (platform overhead or unknown): %s",
            sorted(unresolved_namespaces),
        )
    return subjects
