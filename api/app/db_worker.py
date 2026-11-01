"""The database housekeeping worker: periodic sweeps over the tenant cluster.

One process, several ticks, each on its own cadence. The quota tick lives here;
the purge and orphan ticks join it later.

**Ticks share a process but not a `try`.** Purge performs the only irreversible
operation in this subsystem and a bug there must not stop quota enforcement, or
the reverse, so a tick that raises is logged and its neighbors still run.

No keyring verification at startup, unlike the API and `caelus worker`: every
tick connects as the platform admin and none of them decrypts a tenant password
(design D10).
"""

from __future__ import annotations

import logging
import os
import signal
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from sqlmodel import Session, select

from app.config import CaelusSettings, get_settings
from app.db import session_scope
from app.models import DeploymentDatabaseORM, DeploymentORM
from app.services import app_access, relational_storage
from app.services.postgres_admin import PostgresAdminClient

logger = logging.getLogger(__name__)


@dataclass
class TickResult:
    """What one sweep did, for the operator watching the log."""

    name: str
    swept: int = 0
    changed: dict[str, str] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)
    orphans: dict[str, list[str]] = field(default_factory=dict)


def quota_tick(
    session: Session,
    *,
    tenant_db: PostgresAdminClient | None = None,
    settings: CaelusSettings | None = None,
) -> TickResult:
    """Measure every provisioned database and apply the state it lands in.

    One deployment's failure is recorded and skipped rather than abandoning the
    rest of the fleet.
    """
    settings = settings or get_settings()
    tenant_db = tenant_db or PostgresAdminClient.from_settings(settings)
    result = TickResult(name="quota")

    # Rows awaiting purge are deleted deployments; evaluating one would
    # re-assert the LOGIN its teardown removed.
    records = session.exec(
        select(DeploymentDatabaseORM).where(DeploymentDatabaseORM.purge_after.is_(None))
    ).all()

    for record in records:
        deployment = session.get(DeploymentORM, record.deployment_id)
        if deployment is None:
            continue
        previous = record.quota_state
        try:
            state = relational_storage.evaluate_quota_state(
                session,
                deployment,
                tenant_db=tenant_db,
                settings=settings,
                record=record,
            )
        except Exception as exc:
            logger.exception("Quota evaluation failed deployment_id=%s", deployment.id)
            result.failed[str(deployment.id)] = str(exc)
            session.rollback()
            continue
        result.swept += 1
        if state != previous:
            result.changed[str(deployment.id)] = f"{previous} -> {state}"

    # Every sweep, including the ones that change nothing: on a small fleet
    # that is the only evidence the process is alive and reaching the cluster.
    logger.info(
        "Quota sweep complete: swept=%s changed=%s failed=%s",
        result.swept,
        len(result.changed),
        len(result.failed),
    )
    return result


def purge_tick(
    session: Session,
    *,
    tenant_db: PostgresAdminClient | None = None,
    settings: CaelusSettings | None = None,
) -> TickResult:
    """Destroy the databases of deployments whose grace period has elapsed.

    The only irreversible work this process does. It is capped per run, refuses
    anything not yet due, and logs every drop with its deployment id.
    """
    settings = settings or get_settings()
    tenant_db = tenant_db or PostgresAdminClient.from_settings(settings)
    result = TickResult(name="purge")
    now = datetime.now(UTC).replace(tzinfo=None)

    due = session.exec(
        select(DeploymentDatabaseORM)
        .where(
            DeploymentDatabaseORM.purge_after.is_not(None),
            DeploymentDatabaseORM.purge_after <= now,
        )
        .order_by(DeploymentDatabaseORM.purge_after)
        .limit(settings.db_worker_max_purges_per_run)
    ).all()

    for record in due:
        deployment_id = str(record.deployment_id)
        try:
            relational_storage.purge_database(
                session, record, tenant_db=tenant_db, settings=settings
            )
        except Exception as exc:
            logger.exception("Purge failed deployment_id=%s", deployment_id)
            result.failed[deployment_id] = str(exc)
            session.rollback()
            continue
        result.swept += 1
        result.changed[deployment_id] = "purged"

    logger.info(
        "Purge sweep complete: purged=%s failed=%s due=%s",
        result.swept,
        len(result.failed),
        len(due),
    )
    return result


def orphan_tick(
    session: Session,
    *,
    tenant_db: PostgresAdminClient | None = None,
    settings: CaelusSettings | None = None,
) -> TickResult:
    """Report cluster objects no row accounts for. Destroys nothing."""
    settings = settings or get_settings()
    tenant_db = tenant_db or PostgresAdminClient.from_settings(settings)
    result = TickResult(name="orphan")

    result.orphans = relational_storage.find_orphans(
        session, tenant_db=tenant_db, settings=settings
    )
    result.swept = sum(len(names) for names in result.orphans.values())
    if result.swept:
        logger.warning(
            "Orphaned tenant objects: databases=%s roles=%s",
            result.orphans["databases"],
            result.orphans["roles"],
        )
    else:
        logger.info("Orphan sweep complete: nothing unaccounted for")
    return result


def invitation_tick(
    session: Session,
    *,
    tenant_db: PostgresAdminClient | None = None,
    settings: CaelusSettings | None = None,
) -> TickResult:
    """Forget access list invitations too old to count against any limit."""
    result = TickResult(name="invitations", swept=app_access.sweep_invitations(session))
    logger.info("Invitation sweep complete: forgot=%s", result.swept)
    return result


def run_ticks(ticks: list[Callable[[], TickResult]], *, emit: Any = None) -> list[TickResult]:
    """Run each tick, letting a failure in one stop only that one."""
    results: list[TickResult] = []
    for tick in ticks:
        try:
            result = tick()
        except Exception:
            logger.exception("Tick failed; continuing with the rest")
            continue
        results.append(result)
        if emit is not None and (result.swept or result.changed or result.failed):
            emit(
                {
                    "tick": result.name,
                    "swept": result.swept,
                    "changed": result.changed,
                    "failed": result.failed,
                }
            )
    return results


def run_db_worker(
    *,
    settings: CaelusSettings | None = None,
    tenant_db: PostgresAdminClient | None = None,
    emit: Any = None,
    max_passes: int | None = None,
) -> None:
    """Repeat the ticks until signalled.

    ``max_passes`` bounds the loop for tests; production leaves it unset.
    """
    settings = settings or get_settings()
    shutdown = False

    def _handle_signal(signum: int, frame: object) -> None:
        nonlocal shutdown
        shutdown = True
        logger.info("Caught signal %s, finishing pass then exiting (pid=%s)", signum, os.getpid())

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Each tick keeps its own cadence: quotas are customer-facing state and
    # move minute to minute, while purging and orphan-hunting are daily.
    schedule = [
        (quota_tick, settings.db_worker_quota_interval_seconds),
        (purge_tick, settings.db_worker_purge_interval_seconds),
        (orphan_tick, settings.db_worker_orphan_interval_seconds),
        (invitation_tick, settings.db_worker_purge_interval_seconds),
    ]
    logger.info(
        "Database worker started: quota=%ss purge=%ss orphan=%ss invitations=%ss",
        *(interval for _, interval in schedule),
    )

    # Every tick runs on the first pass, so a restart is also a full sweep.
    due_at = {tick.__name__: 0.0 for tick, _ in schedule}
    passes = 0
    while not shutdown:
        now = time.monotonic()
        ready = [(tick, interval) for tick, interval in schedule if due_at[tick.__name__] <= now]
        if ready:
            with session_scope() as session:
                run_ticks(
                    [
                        _bind(tick, session, tenant_db=tenant_db, settings=settings)
                        for tick, _ in ready
                    ],
                    emit=emit,
                )
            for tick, interval in ready:
                due_at[tick.__name__] = time.monotonic() + interval

        passes += 1
        if max_passes is not None and passes >= max_passes:
            break
        sleep_until = min(due_at.values())
        while not shutdown and time.monotonic() < sleep_until:
            time.sleep(min(1.0, max(0.0, sleep_until - time.monotonic())))

    logger.info("Database worker stopped after %s pass(es)", passes)


def _bind(tick, session, **kwargs) -> Callable[[], TickResult]:
    """A zero-argument tick, so `run_ticks` guards each one identically."""
    return lambda: tick(session, **kwargs)
