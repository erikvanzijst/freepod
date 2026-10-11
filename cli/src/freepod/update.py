"""Notice a newer release, at most once a day.

Nothing a user installs with keeps the client current on its own, so the client
looks for itself and prints a one-line hint with the upgrade command for however
it was installed. It never upgrades itself: a running `freepod.exe` cannot
replace itself on Windows, and a package manager's install is that manager's to
change.

The latest version is read from the repository the install actually upgrades
from. The Homebrew tap is published after PyPI, often a day later, so a brew
user told about a PyPI release would run `brew upgrade` and get nothing.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import NamedTuple, Optional, Tuple

import httpx

from . import __version__
from .config import USER_AGENT, config_dir, ensure_config_dir

OPT_OUT_VAR = "FREEPOD_NO_UPDATE_CHECK"
STATE_FILE = "update.json"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
#: Short, because the check runs after a command the user is waiting on.
HTTP_TIMEOUT = 2.0

PYPI_URL = "https://pypi.org/pypi/freepod/json"
BREW_FORMULA_URL = (
    "https://raw.githubusercontent.com/erikvanzijst/homebrew-tap/HEAD/Formula/freepod.rb"
)
_FORMULA_VERSION = re.compile(r"/freepod-(\d+(?:\.\d+)*)\.tar\.gz\"")


class Install(NamedTuple):
    """Where this copy came from: which repository to ask, and how to upgrade."""

    source: str  # "pypi" or "brew"
    command: str


def detect_install(prefix: Optional[Path] = None) -> Install:
    """Work out how this copy was installed from the environment it runs in.

    Each installer leaves a marker in the environment it creates. mise is
    checked before uv and pipx because its `pipx:` backend installs through
    one of them, leaving their marker in a directory only mise upgrades.
    """
    prefix = Path(sys.prefix if prefix is None else prefix)
    parts = [part.lower() for part in prefix.parts]
    if "cellar" in parts:
        return Install("brew", "brew upgrade freepod")
    if "mise" in parts:
        return Install("pypi", "mise upgrade pipx:freepod")
    if (prefix / "uv-receipt.toml").is_file():
        return Install("pypi", "uv tool upgrade freepod")
    if (prefix / "pipx_metadata.json").is_file():
        return Install("pypi", "pipx upgrade freepod")
    return Install("pypi", "pip install --upgrade freepod")


def parse_version(text: str) -> Optional[Tuple[int, ...]]:
    """`1.2.3` as `(1, 2, 3)`; None for anything else, pre-releases included."""
    if not re.fullmatch(r"\d+(?:\.\d+)*", text.strip()):
        return None
    return tuple(int(part) for part in text.strip().split("."))


def latest_version(source: str, client: Optional[httpx.Client] = None) -> Optional[str]:
    """The newest release `source` offers, or None if it cannot be told."""
    owned = client is None
    if client is None:
        client = httpx.Client(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT})
    try:
        if source == "brew":
            match = _FORMULA_VERSION.search(client.get(BREW_FORMULA_URL).raise_for_status().text)
            return match.group(1) if match else None
        return str(client.get(PYPI_URL).raise_for_status().json()["info"]["version"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    finally:
        if owned:
            client.close()


def opted_out() -> bool:
    return os.environ.get(OPT_OUT_VAR, "").strip().lower() not in ("", "0", "false", "no")


def state_path() -> Path:
    return config_dir() / STATE_FILE


def _last_checked() -> float:
    try:
        return float(json.loads(state_path().read_text(encoding="utf-8"))["checked"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0


def _record_check(now: float) -> None:
    directory = ensure_config_dir()
    temporary = directory / f".{STATE_FILE}.tmp"
    temporary.write_text(json.dumps({"checked": now}) + "\n", encoding="utf-8")
    os.replace(temporary, state_path())


def check(now: Optional[float] = None, client: Optional[httpx.Client] = None) -> Optional[str]:
    """The notice to print, or None; asks the network at most once a day.

    The attempt is recorded before asking, so a machine that is offline or
    behind a proxy pays the timeout once a day rather than on every command.
    """
    now = time.time() if now is None else now
    if 0 <= now - _last_checked() < CHECK_INTERVAL_SECONDS:
        return None
    current = parse_version(__version__)
    if current is None:
        return None
    try:
        _record_check(now)
    except OSError:
        return None

    install = detect_install()
    latest = latest_version(install.source, client)
    newer = parse_version(latest) if latest else None
    if newer is None or newer <= current:
        return None
    return f"freepod {latest} available (you have {__version__}): {install.command}"
