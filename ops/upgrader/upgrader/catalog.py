"""Which curated products a run covers, and which ones "Run one product" offers (product-upgrade-runs,
product-upgrade-dashboard)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

PLACEHOLDER = "OWNER/REPO"


def eligible(clone: Path) -> list[str]:
    """Slugs of the catalog files with a real `upstream` block, in slug order."""
    slugs = []
    for path in sorted((clone / "products" / "catalog").glob("*.yaml")):
        doc = yaml.safe_load(path.read_text()) or {}
        upstream = doc.get("upstream")
        source = upstream.get("source") if isinstance(upstream, dict) else None
        if isinstance(source, dict) and PLACEHOLDER not in source.values():
            slugs.append(path.stem)
    return slugs


def fetch(repo_url: str, git: str = "git", workdir: Path | None = None) -> list[str]:
    """The eligible products on a fresh shallow clone of master."""
    scratch = Path(tempfile.mkdtemp(prefix="catalog-", dir=workdir))
    try:
        subprocess.run([git, "clone", "-q", "--depth", "1", "--branch", "master", repo_url,
                        str(scratch / "freepod")], check=True, capture_output=True, timeout=120)
        return eligible(scratch / "freepod")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


class Choices:
    """The products "Run one product" offers, re-read from master at most every TTL seconds. A failed
    read keeps the last list it had."""

    TTL = 300

    def __init__(self, read: Callable[[], list[str]], clock: Callable[[], float] = time.monotonic):
        self.read, self.clock = read, clock
        self._slugs: list[str] = []
        self._at: float | None = None
        self._lock = threading.Lock()

    def __call__(self) -> list[str]:
        with self._lock:
            if self._at is None or self.clock() - self._at >= self.TTL:
                self._at = self.clock()
                try:
                    self._slugs = self.read()
                except Exception:
                    log.exception("could not read the catalog from master")
            return list(self._slugs)
