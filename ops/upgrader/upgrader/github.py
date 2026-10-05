"""GitHub as the App (D8): installation tokens, the bot's identity, and PR states (D13)."""

from __future__ import annotations

import base64
import binascii
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from .config import REPO

log = logging.getLogger(__name__)

API = "https://api.github.com"
READ_WRITE = {"contents": "write", "pull_requests": "write", "metadata": "read"}
READ_ONLY = {"contents": "read", "pull_requests": "read", "metadata": "read"}
PULL_REQUESTS_READ = {"pull_requests": "read"}
LABEL = {"name": "product-upgrade", "color": "0E8A16", "description": "Automated product version upgrade"}


def load_private_key(private_key_b64: str) -> str:
    try:
        pem = base64.b64decode(private_key_b64, validate=True)
        load_pem_private_key(pem, password=None)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise ValueError("GITHUB_APP_PRIVATE_KEY is not base64 of a PEM private key") from exc
    return pem.decode()


def client() -> httpx.Client:
    return httpx.Client(
        base_url=API,
        timeout=30,
        headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
    )


@dataclass(frozen=True)
class Token:
    value: str
    expires_at: datetime


class App:
    def __init__(self, app_id: str, private_key_b64: str, http: httpx.Client | None = None,
                 repo: str = REPO):
        self.app_id = app_id
        self.pem = load_private_key(private_key_b64)
        self.http = http or client()
        self.repo = repo
        self._installation: int | None = None

    def _jwt(self) -> str:
        issued = int(time.time())
        claims = {"iat": issued - 60, "exp": issued + 540, "iss": str(self.app_id)}
        return jwt.encode(claims, self.pem, algorithm="RS256")

    def _as_app(self, method: str, path: str, **kwargs) -> dict:
        response = self.http.request(method, path, headers={"Authorization": f"Bearer {self._jwt()}"},
                                     **kwargs)
        response.raise_for_status()
        return response.json()

    def installation_id(self) -> int:
        if self._installation is None:
            self._installation = self._as_app("GET", f"/repos/{self.repo}/installation")["id"]
        return self._installation

    def mint(self, permissions: dict[str, str]) -> Token:
        body = {"repositories": [self.repo.split("/")[1]], "permissions": permissions}
        data = self._as_app("POST", f"/app/installations/{self.installation_id()}/access_tokens",
                            json=body)
        expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        return Token(data["token"], expires)

    def _as_installation(self, token: str, method: str, path: str, **kwargs) -> httpx.Response:
        return self.http.request(method, path, headers={"Authorization": f"token {token}"}, **kwargs)

    def open_pull_request(self, token: str, branch: str, title: str, body: str, draft: bool) -> str:
        """Open the pull request for a pushed branch, labeled, and return its URL (D4)."""
        labels = self._as_installation(token, "POST", f"/repos/{self.repo}/labels", json=LABEL)
        if labels.status_code != 422:  # 422: the label exists
            labels.raise_for_status()
        response = self._as_installation(token, "POST", f"/repos/{self.repo}/pulls", json={
            "title": title, "head": branch, "base": "master", "body": body, "draft": draft})
        response.raise_for_status()
        pull = response.json()
        try:
            self._as_installation(token, "POST", f"/repos/{self.repo}/issues/{pull['number']}/labels",
                                  json={"labels": [LABEL["name"]]}).raise_for_status()
        except httpx.HTTPError:
            log.exception("could not label %s", pull["html_url"])
        return pull["html_url"]

    def identity(self) -> tuple[str, str]:
        """The bot user's commit name and noreply address."""
        login = f"{self._as_app('GET', '/app')['slug']}[bot]"
        response = self.http.get(f"/users/{login}")
        response.raise_for_status()
        return login, f"{response.json()['id']}+{login}@users.noreply.github.com"


class TokenFile:
    """The current installation token for one session, replaced before it expires (D8). `share`
    makes the file and its directory readable to the session user, and to no one else."""

    def __init__(self, app: App, path: Path, permissions: dict[str, str],
                 on_mint: Callable[[str], None] = lambda token: None,
                 margin: timedelta = timedelta(minutes=10),
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 share: Callable[[Path, int], None] = lambda path, mode: path.chmod(mode)):
        self.app, self.path, self.permissions = app, path, permissions
        self.on_mint, self.margin, self.clock, self.share = on_mint, margin, clock, share
        self.token: Token | None = None

    def refresh(self) -> None:
        if self.token and self.clock() < self.token.expires_at - self.margin:
            return
        self.token = self.app.mint(self.permissions)
        self.on_mint(self.token.value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.share(self.path.parent, 0o750)
        staged = self.path.with_suffix(".new")
        staged.unlink(missing_ok=True)
        fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(self.token.value)
        self.share(staged, 0o640)
        os.replace(staged, self.path)

    def remove(self) -> None:
        self.path.unlink(missing_ok=True)


PR_URL = re.compile(r"^https://github\.com/([^/]+/[^/]+)/pull/([0-9]+)$")


class PullRequests:
    """PR states for the dashboard, read with a read-only token and cached for five minutes."""

    TTL = 300

    def __init__(self, app: App | None, http: httpx.Client | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.app = app
        self.http = http or (app.http if app else client())
        self.clock = clock
        self._cache: dict[str, tuple[str, float]] = {}
        self._token: Token | None = None
        self._lock = threading.Lock()

    def _headers(self) -> dict[str, str]:
        if not self.app:
            return {}
        if not self._token or datetime.now(UTC) >= self._token.expires_at - timedelta(minutes=5):
            self._token = self.app.mint(PULL_REQUESTS_READ)
        return {"Authorization": f"token {self._token.value}"}

    def state(self, url: str) -> str:
        with self._lock:
            cached = self._cache.get(url)
            if cached and self.clock() - cached[1] < self.TTL:
                return cached[0]
            match = PR_URL.match(url)
            if not match:
                return "unknown"
            try:
                response = self.http.get(f"/repos/{match[1]}/pulls/{match[2]}", headers=self._headers())
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError):
                return "unknown"
            if data.get("merged"):
                state = "merged"
            elif data.get("state") == "closed":
                state = "closed"
            else:
                state = "draft" if data.get("draft") else "open"
            self._cache[url] = (state, self.clock())
            return state
