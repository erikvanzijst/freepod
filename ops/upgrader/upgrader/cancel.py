"""Aborting the run that is executing now (product-upgrade-runs, D16)."""

from __future__ import annotations

import os
import signal
import subprocess
import threading


class Cancellation:
    """The run executing now, and whether the owner has asked to abort it. The runner
    registers the session it is waiting on; the dashboard asks (D1)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._run_id: int | None = None
        self._process: subprocess.Popen | None = None
        self._asked = False

    def start(self, run_id: int) -> None:
        with self._lock:
            self._run_id, self._process, self._asked = run_id, None, False

    def stop(self) -> bool:
        """Forget the run, reporting whether it was canceled."""
        with self._lock:
            asked = self._asked
            self._run_id, self._process, self._asked = None, None, False
            return asked

    def watch(self, process: subprocess.Popen | None) -> bool:
        """Register the session the run is waiting on, or None once it has ended. False when
        the abort was asked for first, so a session that just started is not left running."""
        with self._lock:
            self._process = process
            return not self._asked

    def asked(self) -> bool:
        with self._lock:
            return self._asked

    def request(self, run_id: int) -> bool:
        """Abort `run_id`, if that is the run executing now. The session is asked to end here so
        that the wait ends at once; the runner escalates to its process group, and the flag
        stops the run before its next product."""
        with self._lock:
            if self._run_id != run_id:
                return False
            self._asked = True
            process = self._process
        if process:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        return True
