from __future__ import annotations

import logging
import multiprocessing
import os
import queue
import signal
import sys
import time

from app import db
from app.db import session_scope
from app.services import (
    reconcile as reconcile_service,
    jobs as jobs_service,
)
from app.services.reconcile_constants import DEPLOYMENT_STATUS_ERROR

logger = logging.getLogger(__name__)

_CHILD_CHECK_SECONDS = 5.0


def process_one_job(base_worker_id: str) -> dict | None:
    """Claim and process a single job.

    Each call opens its own database session so it is safe to run in a
    subprocess.  Returns a result dict on success/failure, or ``None`` when
    no job was available.
    """
    effective_worker_id = f"{base_worker_id}-{os.getpid()}"
    with session_scope() as session:
        jobs = jobs_service.JobService(session)
        claimed = jobs.claim_next_job(worker_id=effective_worker_id)
        if claimed is None:
            return None

        # Capture claim metadata before mark_done/mark_failed clears it
        job_id = claimed.id
        deployment_id = claimed.deployment_id
        reason = claimed.reason
        locked_by = claimed.locked_by
        locked_at = claimed.locked_at

        reconciler = reconcile_service.DeploymentReconciler(session=session)
        result = reconciler.reconcile(deployment_id)

        # Report the result under our own worker id: if this process was wedged
        # long enough for its lease to be reclaimed, the job now belongs to
        # another worker and these calls must not clobber its outcome. The
        # returned row carries whatever status actually stuck.
        last_error: str | None = result.last_error
        if result.status == DEPLOYMENT_STATUS_ERROR:
            completed = jobs.mark_job_failed(
                job_id=job_id,
                error=result.last_error or "unknown error",
                worker_id=effective_worker_id,
            )
        else:
            completed = jobs.mark_job_done(job_id=job_id, worker_id=effective_worker_id)
        status = completed.status

        return {
            "id": job_id,
            "deployment_id": deployment_id,
            "reason": reason,
            "status": status,
            "locked_by": locked_by,
            "locked_at": locked_at,
            "last_error": last_error,
        }


def _poll_once(
    base_worker_id: str, result_queue: multiprocessing.Queue, poll_seconds: float
) -> None:
    """Process at most one job. A failure is logged, never raised.

    A job claimed before the failure stays leased, and is retried once its
    lease expires.
    """
    try:
        payload = process_one_job(base_worker_id)
    except Exception:
        logger.exception("Reconcile pass failed; continuing")
        payload = None
    if payload is None:
        time.sleep(poll_seconds)
    else:
        result_queue.put(payload)


def _crashed(workers: list) -> list:
    """Worker processes that died without finishing normally."""
    return [p for p in workers if not p.is_alive() and p.exitcode not in (0, None)]


def _worker_loop(
    base_worker_id: str, result_queue: multiprocessing.Queue, poll_seconds: float
) -> None:
    """Run in a worker process. Claims and processes jobs until signaled."""
    # A forked child inherits the parent's pool, sockets included. Sharing one
    # connection between processes desyncs the wire protocol; `close=False`
    # drops them without closing sockets the parent still owns.
    db.get_engine().dispose(close=False)

    shutdown = False

    def _handle_signal(signum: int, frame: object) -> None:
        nonlocal shutdown
        shutdown = True
        logger.info(f"Caught signal {signum}, shutting down worker process {os.getpid()}")

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while not shutdown:
        _poll_once(base_worker_id, result_queue, poll_seconds)

    # Sentinel: tell the master this worker is done
    result_queue.put(None)


def run_worker(
    *, base_worker_id: str, concurrency: int, poll_seconds: float, emit: callable
) -> None:
    """Spawn worker processes and collect results.

    ``emit`` is called with each completed job result dict (used by the CLI
    to print YAML output).
    """
    result_queue: multiprocessing.Queue = multiprocessing.Queue()
    workers = []
    for _ in range(concurrency):
        p = multiprocessing.Process(
            target=_worker_loop,
            args=(base_worker_id, result_queue, poll_seconds),
        )
        p.start()
        workers.append(p)

    def _handle_signal(signum: int, frame: object) -> None:
        logger.info(f"Master caught signal {signum} in master process {os.getpid()} -- waiting for workers to exit")

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Master: read results until all workers have exited. A worker that dies
    # without its sentinel would leave the master waiting forever, so exit
    # instead and let the container restart.
    exited = 0
    while exited < concurrency:
        try:
            result = result_queue.get(timeout=_CHILD_CHECK_SECONDS)
        except queue.Empty:
            crashed = _crashed(workers)
            if crashed:
                for p in crashed:
                    logger.error(f"Worker process {p.pid} exited with code {p.exitcode}; exiting")
                for p in workers:
                    if p.is_alive():
                        p.terminate()
                for p in workers:
                    p.join()
                sys.exit(1)
            continue
        if result is None:
            exited += 1
        else:
            emit(result)
    logger.info(f"All workers exited, shutting down master process {os.getpid()}")

    for p in workers:
        p.join()
