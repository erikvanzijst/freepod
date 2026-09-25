"""The build worker: one repeating, non-blocking pass.

Each pass does three things and blocks on none of them:

1. **advance** every `running` build — mirror its Job's output into the log,
   adopt its outcome if it finished, and enforce the deadline backstop;
2. **claim** queued builds while below the in-flight limit, creating a Job for
   each;
3. **recover**, which is not a separate step — it *is* step 1. Visiting every
   running build on every pass is what makes a worker restart survivable: a
   build whose worker died is picked up by whichever worker runs next, and its
   log self-heals because the log is a mirror rather than an append.

Advancing before claiming is deliberate: a build that finished this pass frees
its in-flight slot immediately rather than a whole interval later.

Nothing here follows a log stream or waits for a build. Blocking for the
duration of a build would make recovery a second writer racing this one over
whether a build succeeded — at an in-flight limit of 1, a single long build
would suspend recovery entirely, exactly when it is most needed.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from app.config import CaelusSettings, get_settings
from app.db import session_scope
from app.models import BuildORM
from app.services import artifacts as artifact_service
from app.services import builds as build_service
from app.services.build_constants import (
    BUILD_STATUS_FAILED,
    BUILD_STATUS_QUEUED,
    BUILD_STATUS_RUNNING,
    BUILD_STATUS_SUCCEEDED,
)
from app.services.build_jobs import (
    BuildJobClient,
    KubectlBuildJobClient,
    build_job_manifest,
    job_is_complete,
    job_is_failed,
    job_name,
    parse_image_from_termination_message,
)

logger = logging.getLogger(__name__)

# Appended when a build's output is discarded at the cap. ASCII, and counted
# against the cap itself, so the stored log never exceeds the configured size.
TRUNCATION_MARKER = b"\n[log truncated: build produced more than %d bytes]\n"


@dataclass
class PassResult:
    """What one pass did — returned for logging and for tests to assert on."""

    claimed: list[UUID]
    succeeded: list[UUID]
    failed: list[UUID]
    advanced: int

    @property
    def changed(self) -> bool:
        return bool(self.claimed or self.succeeded or self.failed)


# ---------------------------------------------------------------------------
# Log mirroring
# ---------------------------------------------------------------------------


def truncate_log(data: bytes, *, cap: int) -> bytes:
    """`data` bounded to `cap` bytes, ending with a marker when truncated.

    The marker is included *within* the cap rather than appended past it, so
    the column bound is the real one.
    """
    if len(data) <= cap:
        return data
    marker = TRUNCATION_MARKER % cap
    keep = max(cap - len(marker), 0)
    return data[:keep] + marker[: cap - keep]


def merge_log(stored: bytes, fresh: bytes | None, *, cap: int) -> bytes:
    """The log to store, given what is already stored and what was just read.

    The log is a *mirror* of the Job's current output, re-read in full each
    pass, which needs no offset bookkeeping and lets a restarted worker resume
    with no notion of its own position. The one hazard of that design is that a
    container runtime may rotate older output away, so a later read can be
    shorter than an earlier one — and clients have already read the longer
    version at byte offsets that must stay meaningful. A read that returns less
    than what is stored is therefore discarded, never applied.
    """
    if not fresh:
        return stored
    candidate = truncate_log(fresh, cap=cap)
    if len(candidate) < len(stored):
        return stored
    return candidate


# ---------------------------------------------------------------------------
# Claiming
# ---------------------------------------------------------------------------


def _running_count(session: Session) -> int:
    return len(
        session.exec(select(BuildORM).where(BuildORM.status == BUILD_STATUS_RUNNING)).all()
    )


def _claim_next_build(session: Session, *, now: datetime) -> BuildORM | None:
    """Atomically move the oldest queued build to `running`, or return None.

    Mirrors ``JobService.claim_next_job``: ``FOR UPDATE SKIP LOCKED`` so
    concurrent workers step over each other's rows rather than blocking.

    The claim is a single statement because two workers each reading "oldest
    queued" and then writing would hand the same build to both.
    """
    build = session.exec(
        select(BuildORM)
        .where(BuildORM.status == BUILD_STATUS_QUEUED)
        .order_by(BuildORM.created_at, BuildORM.id)  # type: ignore[arg-type]
        .with_for_update(skip_locked=True)
        .limit(1)
    ).first()
    if build is None:
        return None
    # Held under FOR UPDATE until the commit, so this remains a single claim.
    build.status = BUILD_STATUS_RUNNING
    build.started_at = now
    session.add(build)
    session.commit()
    session.refresh(build)
    return build


def _start_build(
    session: Session,
    build: BuildORM,
    *,
    client: BuildJobClient,
    settings: CaelusSettings,
) -> None:
    """Create the Kubernetes Job for a freshly claimed build.

    ``job_id`` is recorded only *after* the Job exists. A crash in between
    therefore leaves a `running` build with a null ``job_id``, which is
    unambiguous — the Job may or may not exist, but nothing recorded says it
    does — and the next pass fails that build rather than guessing.
    """
    # The owner is the deployment's: it scopes the artifact key, the image
    # repository and the push capability alike.
    owner_id = build_service.build_owner_id(session, build)
    artifact_url = artifact_service.artifact_download_url(
        owner_id, build.artifact_id, settings=settings
    )
    manifest = build_job_manifest(
        build_id=build.id,
        user_id=owner_id,
        artifact_url=artifact_url,
        settings=settings,
    )
    client.create_job(manifest)

    build.job_id = job_name(build.id)
    session.add(build)
    session.commit()
    logger.info("Started build id=%s job=%s", build.id, build.job_id)


# ---------------------------------------------------------------------------
# Advancing a running build
# ---------------------------------------------------------------------------


def _finish(
    session: Session,
    build: BuildORM,
    *,
    status: str,
    image: str | None = None,
    now: datetime,
    reason: str,
) -> None:
    build.transition_to(status, image=image, now=now)
    session.add(build)
    session.commit()
    logger.info("Build id=%s -> %s (%s)", build.id, status, reason)


def _advance_build(
    session: Session,
    build: BuildORM,
    *,
    client: BuildJobClient,
    settings: CaelusSettings,
    now: datetime,
    result: PassResult,
) -> None:
    """Mirror one running build's output, then decide whether it is done."""
    # Log first, and unconditionally: whatever happens to the build below, the
    # output explaining it should already be stored.
    fresh = client.read_log(str(build.id))
    merged = merge_log(bytes(build.log or b""), fresh, cap=settings.build_log_max_bytes)
    if merged != bytes(build.log or b""):
        build.log = merged
        session.add(build)
        session.commit()

    if build.job_id is None:
        # The worker died between claiming and recording the Job. Delete any
        # Job that was in fact created — the name is deterministic — so a
        # build we are about to give up on cannot keep consuming the node.
        client.delete_job(job_name(build.id))
        _finish(
            session, build, status=BUILD_STATUS_FAILED, now=now,
            reason="no Kubernetes Job was recorded for this build",
        )
        result.failed.append(build.id)
        return

    job = client.get_job(build.job_id)
    if job is None:
        _finish(
            session, build, status=BUILD_STATUS_FAILED, now=now,
            reason="its Kubernetes Job no longer exists",
        )
        result.failed.append(build.id)
        return

    if job_is_complete(job):
        image = parse_image_from_termination_message(
            client.read_termination_message(str(build.id))
        )
        if image:
            _finish(
                session, build, status=BUILD_STATUS_SUCCEEDED, image=image, now=now,
                reason="Job succeeded and reported an image",
            )
            result.succeeded.append(build.id)
        else:
            # A success that reports no usable image reference is not a usable
            # build: there is nothing a deployment could run.
            _finish(
                session, build, status=BUILD_STATUS_FAILED, now=now,
                reason="Job succeeded but reported no usable image",
            )
            result.failed.append(build.id)
        return

    if job_is_failed(job):
        _finish(
            session, build, status=BUILD_STATUS_FAILED, now=now,
            reason="Job terminated unsuccessfully",
        )
        result.failed.append(build.id)
        return

    # Still running. Kubernetes owns the deadline via activeDeadlineSeconds;
    # this is only the backstop for Kubernetes having failed to enforce it, so
    # it waits a grace period beyond the deadline before intervening.
    started = build.started_at
    if started is not None:
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        overdue_at = started + timedelta(
            seconds=settings.build_deadline_seconds + settings.build_deadline_grace_seconds
        )
        if now > overdue_at:
            logger.warning(
                "Build id=%s is past its deadline and its Job is still active; deleting",
                build.id,
            )
            client.delete_job(build.job_id)
            _finish(
                session, build, status=BUILD_STATUS_FAILED, now=now,
                reason="exceeded its deadline and had to be terminated",
            )
            result.failed.append(build.id)
            return

    result.advanced += 1


# ---------------------------------------------------------------------------
# One pass
# ---------------------------------------------------------------------------


def run_pass(
    session: Session,
    *,
    client: BuildJobClient,
    settings: CaelusSettings | None = None,
    now: datetime | None = None,
) -> PassResult:
    """Advance every running build, then claim queued ones up to the limit."""
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    result = PassResult(claimed=[], succeeded=[], failed=[], advanced=0)

    running = session.exec(
        select(BuildORM).where(BuildORM.status == BUILD_STATUS_RUNNING).order_by(
            BuildORM.started_at  # type: ignore[arg-type]
        )
    ).all()
    for build in running:
        try:
            _advance_build(
                session, build, client=client, settings=settings, now=now, result=result
            )
        except Exception:
            # One build's cluster hiccup must not stop the pass: the others
            # still need advancing, and this one is retried next pass.
            session.rollback()
            logger.exception("Failed to advance build id=%s", build.id)

    while _running_count(session) < settings.build_max_in_flight:
        build = _claim_next_build(session, now=now)
        if build is None:
            break
        try:
            _start_build(session, build, client=client, settings=settings)
            result.claimed.append(build.id)
        except Exception:
            # The build stays `running` with a null job_id and is failed by the
            # next pass, which also deletes any Job that did get created.
            session.rollback()
            logger.exception("Failed to start build id=%s", build.id)
            break

    return result


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def run_build_worker(
    *,
    settings: CaelusSettings | None = None,
    client: BuildJobClient | None = None,
    emit: Any = None,
) -> None:
    """Repeat ``run_pass`` until signalled.

    A single process with a single loop: concurrency is the in-flight limit,
    not a process count, because one non-blocking pass can advance any number
    of running builds.
    """
    settings = settings or get_settings()
    client = client or KubectlBuildJobClient(namespace=settings.builds_namespace)
    shutdown = False

    def _handle_signal(signum: int, frame: object) -> None:
        nonlocal shutdown
        shutdown = True
        logger.info("Caught signal %s, finishing pass then exiting (pid=%s)", signum, os.getpid())

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info(
        "Build worker started: namespace=%s in_flight=%s interval=%ss",
        settings.builds_namespace,
        settings.build_max_in_flight,
        settings.build_worker_interval_seconds,
    )

    while not shutdown:
        try:
            with session_scope() as session:
                result = run_pass(session, client=client, settings=settings)
            if result.changed and emit is not None:
                emit(
                    {
                        "claimed": [str(b) for b in result.claimed],
                        "succeeded": [str(b) for b in result.succeeded],
                        "failed": [str(b) for b in result.failed],
                        "advanced": result.advanced,
                    }
                )
        except Exception:
            # A pass that blew up entirely — a database blip, say — must not
            # kill the worker: the next pass re-reads everything from scratch.
            logger.exception("Build worker pass failed; continuing")

        # Interruptible sleep, so shutdown does not wait out a whole interval.
        deadline = time.monotonic() + settings.build_worker_interval_seconds
        while not shutdown and time.monotonic() < deadline:
            time.sleep(min(0.25, max(deadline - time.monotonic(), 0)))

    logger.info("Build worker exiting cleanly (pid=%s)", os.getpid())
