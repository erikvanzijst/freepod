"""The user sessions run as, which can read none of the service's secrets (D1, D5)."""

from __future__ import annotations

import os
import pwd
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

USER = "agent"
_CLEAN = (
    'find "$1" -user "$(id -u)" -type d -exec chmod u+rwx {} + 2>/dev/null;'
    ' find "$1" -mindepth 1 -depth -user "$(id -u)" -delete 2>/dev/null; exit 0'
)


@dataclass(frozen=True)
class Agent:
    """`prefix` turns a command into one run as the session user. It is empty only when the service
    and its sessions share a user, as in the test suite, and then nothing is isolated."""

    uid: int
    gid: int
    home: str
    prefix: tuple[str, ...] = ()

    @classmethod
    def named(cls, user: str = USER) -> Agent:
        entry = pwd.getpwnam(user)
        return cls(entry.pw_uid, entry.pw_gid, entry.pw_dir, ("sudo", "-n", "-u", user, "--"))

    @classmethod
    def same_user(cls) -> Agent:
        return cls(os.getuid(), os.getgid(), os.environ.get("HOME", "/"))

    @property
    def isolated(self) -> bool:
        return bool(self.prefix)

    def command(self, argv: Sequence[str]) -> list[str]:
        return [*self.prefix, *argv]

    def run(self, argv: Sequence[str], env: Mapping[str, str], **kwargs) -> subprocess.CompletedProcess:
        """A command as the session user. The environment is never inherited: sudo passes on
        whatever it is given, so every caller says exactly what the session may see."""
        return subprocess.run(self.command(argv), env=dict(env), **kwargs)

    def popen(self, argv: Sequence[str], env: Mapping[str, str], **kwargs) -> subprocess.Popen:
        return subprocess.Popen(self.command(argv), env=dict(env), **kwargs)

    def share(self, path: Path, mode: int) -> None:
        """Hand a directory or file the service owns to the session user's group."""
        if self.isolated:
            os.chown(path, -1, self.gid)
        path.chmod(mode)

    def _signal_all(self, sig: int) -> None:
        """Signal every process of the session user, as that user."""
        self.run(["kill", f"-{sig}", "--", "-1"], env=_minimal_env(), capture_output=True, timeout=30)

    def _running(self) -> bool:
        """Whether any process of the session user is left. Not `kill -0 -1`: the kernel reports
        success for it whenever any other process exists, even one it may not signal."""
        out = subprocess.run(["pgrep", "-u", str(self.uid)], capture_output=True, timeout=30)
        return out.returncode == 0

    def interrupt(self, process: subprocess.Popen) -> None:
        """Ask the session to end, without waiting for it."""
        if self.isolated:
            self._signal_all(signal.SIGTERM)
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def terminate(self, process: subprocess.Popen, grace: float = 10) -> None:
        """End a session: as its own user, every process that user runs, including any that left
        the session's process group. Sharing a user, only that group can be told apart."""
        if self.isolated:
            alive, stop = self._running, self._signal_all
        else:
            def alive():
                try:
                    os.killpg(process.pid, 0)
                    return True
                except ProcessLookupError:
                    return False

            def stop(sig):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    pass
        stop(signal.SIGTERM)
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            process.poll()
            if not alive():
                break
            time.sleep(0.2)
        else:
            stop(signal.SIGKILL)
        process.wait()

    def clean(self, directory: Path) -> None:
        """Delete what the session user created under `directory`, including directories it made
        unwritable, which the service could not remove itself."""
        self.run(["sh", "-c", _CLEAN, "sh", str(directory)], env=_minimal_env(), capture_output=True,
                 timeout=600)


def _minimal_env() -> dict[str, str]:
    return {"PATH": os.defpath}
