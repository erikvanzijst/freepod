"""What usage is recorded against: subjects, their identity, and their upsert.

A container's identity is a stable reference built from its controller, and its
attribution is read from the `deployment` table, never from the measurement source's
labels, which vanish with the namespace. An unresolved controller is recorded rather
than skipped: see the design's "Unattributable is not unavailable".

Subjects are written in bulk, one statement per chunk, whatever their kind.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select

from app.models import DeploymentORM, UsageSubjectORM
from app.models.usage import SubjectKind
from app.services.usage.batching import CHUNK_SIZE, batched
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


@dataclass(frozen=True)
class SubjectSpec:
    """A subject as a source names it, before it has an id."""

    kind: SubjectKind
    ref: str
    namespace: str | None = None
    deployment_id: UUID | None = None

    @property
    def key(self) -> tuple[str, str]:
        """The subject's identity, as `upsert_subjects` keys its result."""
        return str(self.kind), self.ref


def container_subject(allocation: Allocation, deployment_id: UUID | None) -> SubjectSpec:
    return SubjectSpec(
        kind=SubjectKind.CONTAINER,
        ref=subject_ref(allocation),
        namespace=allocation.namespace,
        deployment_id=deployment_id,
    )


def _merged(chunk: Iterable[SubjectSpec]) -> list[SubjectSpec]:
    """One spec per identity: a statement may not upsert a row twice. A deployment
    named by any of the duplicates is kept."""
    merged: dict[tuple[str, str], SubjectSpec] = {}
    for spec in chunk:
        prior = merged.get(spec.key)
        if prior is None:
            merged[spec.key] = spec
        elif prior.deployment_id is None and spec.deployment_id is not None:
            merged[spec.key] = replace(prior, deployment_id=spec.deployment_id)
    return list(merged.values())


def upsert_subjects(
    session: Session,
    specs: Iterable[SubjectSpec],
    *,
    observed_at: datetime,
    chunk_size: int = CHUNK_SIZE,
) -> dict[tuple[str, str], int]:
    """Get or create every subject, returning their ids by `SubjectSpec.key`.

    One statement per chunk, so concurrent samplers settle on the unique constraint.
    `deployment_id` is only ever filled in, never cleared: a later window that fails to
    resolve must not undo a backfill. The result holds every id, so callers pass a
    bounded number of specs, as `ledger.record_observations` does.
    """
    table = UsageSubjectORM.__table__
    ids: dict[tuple[str, str], int] = {}
    for chunk in batched(specs, chunk_size):
        statement = insert(table).values(
            [
                {
                    "kind": str(spec.kind),
                    "ref": spec.ref,
                    "namespace": spec.namespace,
                    "deployment_id": spec.deployment_id,
                    "first_seen_at": observed_at,
                    "last_seen_at": observed_at,
                }
                for spec in _merged(chunk)
            ]
        )
        rows = session.execute(
            statement.on_conflict_do_update(
                index_elements=["kind", "ref"],
                set_={
                    "last_seen_at": statement.excluded.last_seen_at,
                    "deployment_id": func.coalesce(
                        table.c.deployment_id, statement.excluded.deployment_id
                    ),
                },
            ).returning(table.c.kind, table.c.ref, table.c.id)
        ).all()
        ids.update({(kind, ref): subject_id for kind, ref, subject_id in rows})
    return ids


def upsert_subject(
    session: Session,
    *,
    ref: str,
    namespace: str | None,
    deployment_id=None,
    observed_at: datetime,
    kind: SubjectKind = SubjectKind.CONTAINER,
) -> int:
    """Get or create one subject, returning its id."""
    spec = SubjectSpec(kind=kind, ref=ref, namespace=namespace, deployment_id=deployment_id)
    return upsert_subjects(session, [spec], observed_at=observed_at)[spec.key]
