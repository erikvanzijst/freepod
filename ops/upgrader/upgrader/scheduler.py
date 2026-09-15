"""One run at a time, requested or nightly (D5, D11)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime

from .config import Settings
from .db import now
from .schedule import next_run

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, execute: Callable[[str, str | None], object],
                 settings: Callable[[], Settings] = Settings.from_env,
                 clock: Callable[[], datetime] = now, tick: float = 60):
        self.execute, self.settings, self.clock, self.tick = execute, settings, clock, tick
        self.lock = threading.Lock()
        self.stop = threading.Event()

    def active(self) -> bool:
        return self.lock.locked()

    def request(self, scope: str | None) -> bool:
        """Start a manual run now, or refuse when one is active. Nothing is queued."""
        if not self.lock.acquire(blocking=False):
            return False
        threading.Thread(target=self._run, args=("manual", scope), daemon=True).start()
        return True

    def _run(self, trigger: str, scope: str | None) -> None:
        try:
            self.execute(trigger, scope)
        except Exception:
            log.exception("the %s run failed", trigger)
        finally:
            self.lock.release()

    def nightly(self) -> None:
        while not self.stop.is_set():
            settings = self.settings()
            problems = settings.schedule_problems()
            if problems:
                log.error("no nightly run: %s", "; ".join(problems))
                self.stop.wait()
                return
            due = next_run(self.clock(), settings.schedule_time, settings.schedule_timezone)
            if due is None:
                self.stop.wait()
                return
            log.info("next scheduled run at %s", due.isoformat())
            while not self.stop.is_set() and self.clock() < due:
                self.stop.wait(min(self.tick, max((due - self.clock()).total_seconds(), 0.001)))
            if self.stop.is_set():
                return
            self.lock.acquire()
            self._run("scheduled", None)

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.nightly, name="nightly", daemon=True)
        thread.start()
        return thread
