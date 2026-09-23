"""The usage sampling worker: one tick, repeated until signalled.

A process of its own rather than another tick inside `db-worker`, because its cadence,
failure modes and blast radius differ and the ledger should keep recording when
reconciliation or database housekeeping breaks.

The tick is a retry mechanism, not a resolution choice. Windows are hourly, so only one
tick an hour finds work and the rest return immediately; the short interval means a
failed pass recovers in minutes instead of an hour, and no separate retry machinery is
needed because every write is idempotent.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from typing import Any

from app.config import CaelusSettings, get_settings
from app.db import session_scope
from app.services.usage import OpenCostClient, OpenCostException, SampleRun, sample_once

logger = logging.getLogger(__name__)


def run_usage_worker(
    *,
    settings: CaelusSettings | None = None,
    client: OpenCostClient | None = None,
    emit: Any = None,
    max_passes: int | None = None,
) -> None:
    """Repeat the sampling pass until signalled.

    ``max_passes`` bounds the loop for tests; production leaves it unset.
    """
    settings = settings or get_settings()
    client = client or OpenCostClient.from_settings(settings)
    shutdown = False

    def _handle_signal(signum: int, frame: object) -> None:
        nonlocal shutdown
        shutdown = True
        logger.info(
            "Caught signal %s, finishing pass then exiting (pid=%s)", signum, os.getpid()
        )

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    interval = settings.usage_worker_interval_seconds
    logger.info(
        "Usage worker started: interval=%ss window=%ss settle=%ss",
        interval,
        settings.usage_window_seconds,
        settings.usage_settle_seconds,
    )

    passes = 0
    while not shutdown:
        try:
            with session_scope() as session:
                result = sample_once(session, client, settings=settings)
        except OpenCostException as exc:
            logger.warning("Usage pass could not reach its source: %s", exc)
            result = SampleRun()
        except Exception:
            logger.exception("Usage pass failed; retrying next tick")
            result = SampleRun()

        if emit is not None and (result.windows_recorded or result.windows_skipped):
            emit(
                {
                    "windows_recorded": result.windows_recorded,
                    "windows_skipped": result.windows_skipped,
                    "samples_written": result.samples_written,
                }
            )

        passes += 1
        if max_passes is not None and passes >= max_passes:
            break
        deadline = time.monotonic() + interval
        while not shutdown and time.monotonic() < deadline:
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))

    logger.info("Usage worker stopped after %s pass(es)", passes)
