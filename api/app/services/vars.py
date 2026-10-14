"""Deployment vars: the effective set, writes, release snapshots, `pending`.

`deployment_var` is an append-only history (see `app/models/core.py`), so
nothing here updates a row: a write inserts, a delete inserts a tombstone, and
the deployment's *effective* configuration -- its **head** -- is derived.

Two invariants this module exists to keep:

  * head is resolved in exactly one function, because the tombstone filter is
    easy to omit and the omission is silent -- a deleted var would come back;

  * every write and every snapshot binding takes the deployment's row lock
    first, which gives a total order per deployment and stops a var write from
    landing between head resolution and the `release_var` insert.
"""

from __future__ import annotations

import logging
from typing import Iterable
from uuid import UUID

from sqlmodel import Session, func, select

from app.models import (
    DeploymentORM,
    DeploymentVarORM,
    ProductTemplateVersionORM,
    ReleaseVarORM,
    UserORM,
    VarRead,
    VarWrite,
    VarWriter,
    VarsRead,
)
from app.services import var_crypto
from app.services.errors import (
    DeploymentInProgressException,
    NotFoundException,
    ValidationException,
)
from app.services.reconcile_constants import DEPLOYMENT_STATUS_DELETING
from app.services.template_values import (
    SENSITIVE_KEY,
    check_var_name,
    derive_projections,
    validate_vars,
)

logger = logging.getLogger(__name__)

# The phase a var is consumed in. A path segment rather than a filter, because
# two vars may share a key when their phases differ; `runtime` is the only one
# until build vars exist. Never an environment: a staging app is its own
# deployment, one path segment earlier.
RUNTIME_PHASE = "runtime"
VAR_PHASES = (RUNTIME_PHASE,)

# design.md D12. Enforced when the request is handled so an oversized var
# fails with a clear error instead of opaquely inside Helm. A Kubernetes
# Secret tops out at 1 MiB, shared with the object-storage credentials.
MAX_VAR_VALUE_BYTES = 8 * 1024
MAX_VARS_TOTAL_BYTES = 128 * 1024
MAX_VARS_PER_DEPLOYMENT = 256


def head(session: Session, deployment_id: UUID) -> dict[str, DeploymentVarORM]:
    """The newest row per key, tombstones excluded, keyed by var name.

    **The only place head is resolved.** Spelled as `id = max(id) per key`
    rather than Postgres `DISTINCT ON` so that it runs on both backends the
    project supports -- a head query that only runs in production is a head
    query nothing tests. `ix_deployment_var_head` serves the grouping.
    """
    newest = (
        select(func.max(DeploymentVarORM.id))
        .where(DeploymentVarORM.deployment_id == deployment_id)
        .group_by(DeploymentVarORM.key)  # type: ignore[arg-type]
        .scalar_subquery()
    )
    rows = session.exec(
        select(DeploymentVarORM)
        .where(
            DeploymentVarORM.id.in_(newest),  # type: ignore[union-attr]
            # The tombstone filter, applied *after* picking the newest row: a
            # key whose latest row is a tombstone is gone, even though older
            # live rows for it remain in history.
            DeploymentVarORM.value_encrypted.is_not(None),  # type: ignore[union-attr]
        )
        .order_by(DeploymentVarORM.key)  # type: ignore[arg-type]
    ).all()
    return {row.key: row for row in rows}


def _lock_deployment(session: Session, deployment_id: UUID) -> None:
    """Serialize everything that touches one deployment's vars.

    `id` is monotonic per insert, but transactions commit out of order, so
    concurrent writers to one key could otherwise produce a head reflecting
    neither intent.
    """
    session.exec(
        select(DeploymentORM.id)
        .where(DeploymentORM.id == deployment_id)
        .with_for_update()
    ).one_or_none()


def _plaintext(row: DeploymentVarORM) -> str:
    assert row.value_encrypted is not None and row.key_id is not None
    return var_crypto.decrypt(row.value_encrypted, row.key_id)


def vars_projection(session: Session, deployment: DeploymentORM) -> dict | None:
    """The vars half of the deployment's desired template schema.

    `None` when the template declares no schema at all, which rejects vars
    outright; an empty closed projection when it declares one but marks
    nothing runtime.
    """
    template = session.get(ProductTemplateVersionORM, deployment.desired_template_id)
    if template is None:
        raise NotFoundException("Template not found")
    return derive_projections(template.values_schema_json).vars


def _resolve_sensitive(
    key: str,
    entry: VarWrite,
    declared: dict,
    existing: DeploymentVarORM | None,
) -> bool:
    """Decide whether a var is sensitive (design.md D7, E6).

    Schema-authoritative where the projection declares the property: a caller
    that contradicts it is rejected rather than silently overridden, because
    quietly downgrading a password is worse than an error.

    Where the projection declares nothing -- an open projection, which is
    `custom` -- the caller decides. A caller that says nothing about an
    *existing* var keeps that var's current flag rather than resetting it to
    the default: every other absent field in this API means "unchanged", and
    the alternative silently exposes a value someone marked sensitive.
    """
    if key in declared and isinstance(declared[key], dict):
        schema_sensitive = bool(declared[key].get(SENSITIVE_KEY, False))
        if entry.sensitive is not None and entry.sensitive != schema_sensitive:
            raise ValidationException(
                f"{key}: this product template declares sensitive="
                f"{str(schema_sensitive).lower()} for this var"
            )
        return schema_sensitive
    if entry.sensitive is not None:
        return entry.sensitive
    return existing.sensitive if existing is not None else False


def _check_limits(desired: dict[str, tuple[str, bool]]) -> None:
    """Bound the head a write would produce. No value is ever quoted back."""
    if len(desired) > MAX_VARS_PER_DEPLOYMENT:
        raise ValidationException(
            f"a deployment may hold at most {MAX_VARS_PER_DEPLOYMENT} vars; "
            f"this write would leave {len(desired)}"
        )
    total = 0
    for key, (plaintext, _) in desired.items():
        size = len(plaintext.encode("utf-8"))
        if size > MAX_VAR_VALUE_BYTES:
            raise ValidationException(
                f"{key}: value exceeds the {MAX_VAR_VALUE_BYTES} byte limit"
            )
        total += size
    if total > MAX_VARS_TOTAL_BYTES:
        raise ValidationException(
            f"a deployment's vars may total at most {MAX_VARS_TOTAL_BYTES} bytes; "
            f"this write would leave {total}"
        )


def write_vars(
    session: Session,
    *,
    deployment: DeploymentORM,
    actor: UserORM,
    entries: dict[str, VarWrite],
    replace: bool = False,
) -> None:
    """Apply a merge (`PATCH`) or a replace (`PUT`) to a deployment's vars.

    Writes rows; does **not** mint a release. Vars are desired state, and a
    write the caller did not ask to deploy stays staged until one is asked
    for -- `pending` is what reports the difference.

    The caller commits. Nothing here commits on its own, so a var write that
    is part of a larger transaction (a deployment create, which must land its
    vars and its release together) cannot half-apply.
    """
    _lock_deployment(session, deployment.id)
    current = head(session, deployment.id)
    projection = vars_projection(session, deployment)
    if entries and projection is None:
        raise ValidationException("vars are not supported on this product template")
    declared = (projection or {}).get("properties") or {}

    desired: dict[str, tuple[str, bool]] = {}
    deletions: set[str] = set()

    for key, entry in entries.items():
        check_var_name(key)
        existing = current.get(key)
        supplies_value = "value" in entry.model_fields_set

        if supplies_value and entry.value is None:
            deletions.add(key)
            continue
        if not supplies_value:
            if existing is None:
                # Nothing to leave unchanged. Silently creating an empty var
                # here would be a surprising way to spell "I have no value".
                raise ValidationException(
                    f"{key}: no value supplied and this var does not exist"
                )
            plaintext = _plaintext(existing)
        else:
            plaintext = entry.value  # type: ignore[assignment]

        sensitive = _resolve_sensitive(key, entry, declared, existing)
        if existing is not None and existing.sensitive and not sensitive and not supplies_value:
            # E6: the reverse flip needs a new value. Exposing a value someone
            # marked sensitive is worse than making them retype it.
            raise ValidationException(
                f"{key}: making a sensitive var readable requires a new value"
            )
        desired[key] = (plaintext, sensitive)

    for key, row in current.items():
        if key in desired or key in deletions:
            continue
        if replace:
            deletions.add(key)
            continue
        desired[key] = (_plaintext(row), row.sensitive)

    validate_vars({key: value for key, (value, _) in desired.items()}, projection)
    _check_limits(desired)

    for key, (plaintext, sensitive) in sorted(desired.items()):
        existing = current.get(key)
        if (
            existing is not None
            and existing.sensitive == sensitive
            and _plaintext(existing) == plaintext
        ):
            # E3: setting a var to what it already holds writes nothing.
            # Without this diff every deploy appends a full copy of the
            # configuration and the history becomes landfill.
            continue
        ciphertext, key_id = var_crypto.encrypt(plaintext)
        session.add(
            DeploymentVarORM(
                deployment_id=deployment.id,
                key=key,
                value_encrypted=ciphertext,
                key_id=key_id,
                sensitive=sensitive,
                created_by=actor.id,
            )
        )

    for key in sorted(deletions):
        if key not in current:
            # E2: deleting a key that is not there is a no-op, not a tombstone
            # over nothing.
            continue
        session.add(
            DeploymentVarORM(deployment_id=deployment.id, key=key, created_by=actor.id)
        )


def require_phase(phase: str) -> None:
    """An unknown phase is a missing resource, as its path segment would be."""
    if phase not in VAR_PHASES:
        raise NotFoundException("Unknown phase")


def assert_writable(deployment: DeploymentORM) -> None:
    """A deployment on its way out takes its vars with it (E12).

    Every other status accepts a write: a staged change to a deployment that
    is provisioning is legal and lands in its next release.
    """
    if deployment.status == DEPLOYMENT_STATUS_DELETING:
        raise DeploymentInProgressException(
            "Deployment is being deleted; its vars cannot be written"
        )


def delete_var(
    session: Session, *, deployment: DeploymentORM, actor: UserORM, key: str
) -> None:
    """Delete one var. Idempotent: an absent key writes nothing."""
    write_vars(
        session,
        deployment=deployment,
        actor=actor,
        entries={key: VarWrite(value=None)},
    )


def snapshot_release(session: Session, *, release_id: UUID, deployment_id: UUID) -> None:
    """Bind head to a release, freezing what that release rolls out.

    Tombstones are never bound: a release ships the vars that existed, not the
    record that some no longer do. Called inside the transaction that creates
    the release, so the snapshot is atomic with it.
    """
    _lock_deployment(session, deployment_id)
    for row in head(session, deployment_id).values():
        session.add(ReleaseVarORM(release_id=release_id, var_id=row.id))


def snapshot(session: Session, release_id: UUID) -> list[DeploymentVarORM]:
    """The var rows one release was created with, by key."""
    return list(
        session.exec(
            select(DeploymentVarORM)
            .join(ReleaseVarORM, ReleaseVarORM.var_id == DeploymentVarORM.id)  # type: ignore[arg-type]
            .where(ReleaseVarORM.release_id == release_id)
            .order_by(DeploymentVarORM.key)  # type: ignore[arg-type]
        ).all()
    )


def pending(session: Session, deployment: DeploymentORM) -> bool:
    """Whether a rollout would change the running pod's environment.

    Compared against the **applied** release, never the desired one: after a
    failed rollout head equals the *failed* release's snapshot, so a diff
    against desired would report nothing pending while the running pod carries
    none of the changes.

    Row identity is the whole comparison, and it is exact: a row is inserted
    only when a value or its sensitivity actually changed, so identical
    configuration is literally the same rows. Re-encryption preserves ids, so
    a key rotation does not make every deployment look pending.
    """
    head_ids = {row.id for row in head(session, deployment.id).values()}
    if deployment.applied_release_id is None:
        return bool(head_ids)
    applied_ids = set(
        session.exec(
            select(ReleaseVarORM.var_id).where(
                ReleaseVarORM.release_id == deployment.applied_release_id
            )
        ).all()
    )
    return head_ids != applied_ids


def _writers(
    session: Session, rows: Iterable[DeploymentVarORM]
) -> dict[int, VarWriter]:
    """Resolve every author in one query, whatever the number of vars."""
    ids = {row.created_by for row in rows}
    if not ids:
        return {}
    found = session.exec(
        select(UserORM.id, UserORM.email).where(UserORM.id.in_(ids))  # type: ignore[attr-defined]
    ).all()
    writers = {user_id: VarWriter(id=user_id, email=email) for user_id, email in found}
    # A missing row leaves the id, which is the identity; the email is the
    # part that may be unavailable.
    return {uid: writers.get(uid, VarWriter(id=uid)) for uid in ids}


def _read_entry(row: DeploymentVarORM, writers: dict[int, VarWriter]) -> VarRead:
    """One row as it is reported. `VarRead` drops the value when sensitive."""
    return VarRead(
        value=None if row.sensitive else _plaintext(row),
        sensitive=row.sensitive,
        updated_at=row.created_at,
        updated_by=writers.get(row.created_by, VarWriter(id=row.created_by)),
    )


def read_vars(session: Session, deployment: DeploymentORM) -> VarsRead:
    """A deployment's head, with `pending`. The one read path for vars."""
    rows = head(session, deployment.id)
    writers = _writers(session, rows.values())
    return VarsRead(
        vars={key: _read_entry(row, writers) for key, row in rows.items()},
        pending=pending(session, deployment),
    )


def read_snapshot(session: Session, release_id: UUID) -> dict[str, VarRead]:
    """One release's frozen vars, through the same serializer every read uses."""
    rows = snapshot(session, release_id)
    writers = _writers(session, rows)
    return {row.key: _read_entry(row, writers) for row in rows}


def read_var(session: Session, deployment: DeploymentORM, key: str) -> VarsRead:
    """One var, in the same shape as the collection."""
    row = head(session, deployment.id).get(key)
    if row is None:
        raise NotFoundException("Var not found")
    return VarsRead(
        vars={key: _read_entry(row, _writers(session, [row]))},
        pending=pending(session, deployment),
    )
