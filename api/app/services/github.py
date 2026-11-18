"""The GitHub App: user authorization, the user's tokens, and calls made with them.

The tokens never leave the platform. A user's access token is refreshed under a
row lock, because GitHub invalidates a refresh token, and the access token it
replaced, the moment it is used.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
import jwt
from sqlmodel import Session, select

from app.config import get_settings
from app.models.core import _utcnow
from app.models.git import GitConnectionORM, GitConnectionRead, GitProvider
from app.services import var_crypto
from app.services.errors import (
    CodedNotFoundException,
    ConflictException,
    InvalidInputException,
    PermissionDeniedException,
    UnavailableException,
    UpstreamException,
)

logger = logging.getLogger(__name__)

HOST = "github.com"
WEB_URL = "https://github.com"
API_URL = "https://api.github.com"
CALLBACK_PATH = "/api/git/github/callback"
STATE_TTL = timedelta(minutes=30)
REFRESH_MARGIN = timedelta(minutes=5)
TIMEOUT = httpx.Timeout(15.0)
API_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


class GitNotConnectedException(ConflictException):
    def __init__(self, message: str = "This account is not connected to GitHub."):
        super().__init__(message, code="git_not_connected")


@dataclass(frozen=True)
class AppConfig:
    app_id: int
    slug: str
    client_id: str
    client_secret: str
    private_key: str
    base_url: str

    @property
    def callback_url(self) -> str:
        return self.base_url.rstrip("/") + CALLBACK_PATH


def config() -> AppConfig:
    s = get_settings()
    values = (
        s.github_app_id,
        s.github_app_slug,
        s.github_client_id,
        s.github_client_secret,
        s.github_private_key,
    )
    if not all(values):
        raise UnavailableException(
            "The GitHub integration is not available here.", code="github_unavailable"
        )
    return AppConfig(*values, base_url=s.base_url)  # type: ignore[arg-type]


def http_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT)


def _http(client: Optional[httpx.Client]) -> AbstractContextManager[httpx.Client]:
    """The caller's client, left open, or a new one closed after use."""
    return nullcontext(client) if client is not None else http_client()


def app_jwt(cfg: AppConfig, now: Optional[int] = None) -> str:
    """A token that authenticates as the app itself, valid for nine minutes."""
    now = int(time.time()) if now is None else now
    return jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": cfg.client_id},
        cfg.private_key,
        algorithm="RS256",
    )


# ── State ─────────────────────────────────────────────────────────────


def _state_key(cfg: AppConfig) -> bytes:
    return hmac.new(cfg.client_secret.encode(), b"freepod-github-state", hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_state(cfg: AppConfig, user_id: Any, now: Optional[datetime] = None) -> str:
    expires = int(((now or _utcnow()) + STATE_TTL).timestamp())
    payload = _b64(json.dumps({"u": str(user_id), "e": expires, "n": secrets.token_urlsafe(8)}).encode())
    signature = _b64(hmac.new(_state_key(cfg), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify_state(cfg: AppConfig, state: str, user_id: Any, now: Optional[datetime] = None) -> None:
    """Refuse a state this app did not issue, issued to someone else, or expired."""
    payload, _, signature = state.partition(".")
    expected = _b64(hmac.new(_state_key(cfg), payload.encode(), hashlib.sha256).digest())
    if not signature or not hmac.compare_digest(signature, expected):
        raise InvalidInputException("The GitHub sign-in link is not valid.", code="github_state_invalid")
    data = json.loads(_unb64(payload))
    if data["u"] != str(user_id):
        raise InvalidInputException(
            "This GitHub sign-in was started by another Freepod account.",
            code="github_state_other_account",
        )
    if data["e"] < int((now or _utcnow()).timestamp()):
        raise InvalidInputException(
            "The GitHub sign-in link has expired. Start again.", code="github_state_expired"
        )


def connect_urls(user_id: Any) -> dict[str, str]:
    """Where to send the user: to authorize the app, or to install it on an account."""
    cfg = config()
    state = sign_state(cfg, user_id)
    authorize = f"{WEB_URL}/login/oauth/authorize?" + urlencode(
        {"client_id": cfg.client_id, "redirect_uri": cfg.callback_url, "state": state}
    )
    install = f"{WEB_URL}/apps/{cfg.slug}/installations/new?" + urlencode({"state": state})
    return {"authorize_url": authorize, "install_url": install}


# ── Tokens ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: Optional[str]
    access_expires_at: Optional[datetime]
    refresh_expires_at: Optional[datetime]


def _token_request(cfg: AppConfig, client: httpx.Client, data: dict[str, str]) -> Tokens:
    try:
        response = client.post(
            f"{WEB_URL}/login/oauth/access_token",
            data={"client_id": cfg.client_id, "client_secret": cfg.client_secret, **data},
            headers={"Accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        raise UpstreamException(f"GitHub did not answer: {exc}", code="github_unreachable") from exc
    if response.status_code != 200:
        raise UpstreamException(
            f"GitHub refused the token request ({response.status_code}).", code="github_error"
        )
    body = response.json()
    if "error" in body:
        raise _TokenError(body["error"], body.get("error_description") or body["error"])
    now = _utcnow().replace(tzinfo=None)

    def expiry(key: str) -> Optional[datetime]:
        seconds = body.get(key)
        return now + timedelta(seconds=int(seconds)) if seconds else None

    return Tokens(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        access_expires_at=expiry("expires_in"),
        refresh_expires_at=expiry("refresh_token_expires_in"),
    )


class _TokenError(Exception):
    def __init__(self, error: str, description: str):
        self.error = error
        super().__init__(description)


def _store(row: GitConnectionORM, tokens: Tokens) -> None:
    blob = json.dumps({"access_token": tokens.access_token, "refresh_token": tokens.refresh_token})
    row.tokens_encrypted, row.key_id = var_crypto.encrypt(blob)
    row.access_token_expires_at = tokens.access_expires_at
    row.refresh_token_expires_at = tokens.refresh_expires_at
    row.updated_at = _utcnow()


def _load(row: GitConnectionORM) -> dict[str, Optional[str]]:
    return json.loads(var_crypto.decrypt(row.tokens_encrypted, row.key_id))


def _call(
    client: httpx.Client,
    method: str,
    path: str,
    token: str,
    *,
    body: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
) -> httpx.Response:
    try:
        return client.request(
            method,
            f"{API_URL}{path}",
            json=body,
            params=params,
            headers={**API_HEADERS, "Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as exc:
        raise UpstreamException(f"GitHub did not answer: {exc}", code="github_unreachable") from exc


def _refused(path: str, response: httpx.Response) -> UpstreamException:
    return UpstreamException(f"GitHub refused {path} ({response.status_code}).", code="github_error")


def _get(client: httpx.Client, path: str, token: str, **params: Any) -> Any:
    """A read made with a user's token."""
    response = _call(client, "GET", path, token, params=params or None)
    if response.status_code == 401:
        raise GitNotConnectedException("GitHub no longer accepts this connection. Connect again.")
    if response.status_code >= 400:
        raise _refused(path, response)
    return response.json()


# ── Connections ───────────────────────────────────────────────────────


def _connection(session: Session, user_id: Any, *, lock: bool = False) -> Optional[GitConnectionORM]:
    query = select(GitConnectionORM).where(
        GitConnectionORM.user_id == user_id,
        GitConnectionORM.provider == GitProvider.GITHUB,
        GitConnectionORM.host == HOST,
    )
    if lock:
        query = query.with_for_update()
    return session.exec(query).first()


def list_connections(session: Session, user_id: Any) -> list[GitConnectionRead]:
    rows = session.exec(
        select(GitConnectionORM)
        .where(GitConnectionORM.user_id == user_id)
        .order_by(GitConnectionORM.provider, GitConnectionORM.host)
    ).all()
    return [
        GitConnectionRead(
            provider=row.provider,
            host=row.host,
            account_id=row.account_id,
            login=row.login,
            connected_at=row.created_at,
            expires_at=row.refresh_token_expires_at,
        )
        for row in rows
    ]


def complete_authorization(
    session: Session,
    user_id: Any,
    *,
    code: str,
    state: str,
    client: Optional[httpx.Client] = None,
) -> GitConnectionORM:
    """Exchange the code GitHub sent back for the user's tokens, and keep them."""
    cfg = config()
    verify_state(cfg, state, user_id)
    with _http(client) as http:
        try:
            tokens = _token_request(cfg, http, {"code": code, "redirect_uri": cfg.callback_url})
        except _TokenError as exc:
            raise InvalidInputException(
                f"GitHub did not accept the sign-in: {exc}", code="github_code_invalid"
            ) from exc
        account = _get(http, "/user", tokens.access_token)

    account_id = str(account["id"])
    other = session.exec(
        select(GitConnectionORM).where(
            GitConnectionORM.provider == GitProvider.GITHUB,
            GitConnectionORM.host == HOST,
            GitConnectionORM.account_id == account_id,
            GitConnectionORM.user_id != user_id,
        )
    ).first()
    if other is not None:
        raise ConflictException(
            f"GitHub account {account['login']} is already connected to another Freepod account.",
            code="github_account_in_use",
        )

    row = _connection(session, user_id, lock=True)
    if row is None:
        row = GitConnectionORM(
            user_id=user_id, provider=GitProvider.GITHUB, host=HOST, account_id=account_id, login=""
        )
    row.account_id = account_id
    row.login = account["login"]
    _store(row, tokens)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def access_token(session: Session, user_id: Any, *, client: Optional[httpx.Client] = None) -> str:
    """The user's access token, refreshed first when it is about to expire.

    Commits the session: the lock that serializes refreshes is held until then.
    """
    row = _connection(session, user_id, lock=True)
    if row is None:
        raise GitNotConnectedException()
    tokens = _load(row)
    now = _utcnow().replace(tzinfo=None)
    expires = row.access_token_expires_at
    if expires is None or expires - now > REFRESH_MARGIN:
        session.commit()
        return tokens["access_token"]  # type: ignore[return-value]

    refresh_token = tokens.get("refresh_token")
    refresh_expires = row.refresh_token_expires_at
    if not refresh_token or (refresh_expires is not None and refresh_expires <= now):
        session.delete(row)
        session.commit()
        raise GitNotConnectedException("The GitHub connection has expired. Connect again.")

    cfg = config()
    with _http(client) as http:
        try:
            fresh = _token_request(
                cfg, http, {"grant_type": "refresh_token", "refresh_token": refresh_token}
            )
        except _TokenError as exc:
            logger.warning("GitHub refused a refresh for user %s: %s", user_id, exc.error)
            session.delete(row)
            session.commit()
            raise GitNotConnectedException(
                "GitHub no longer accepts this connection. Connect again."
            ) from exc
    _store(row, fresh)
    session.add(row)
    session.commit()
    return fresh.access_token


def _revoke(cfg: AppConfig, http: httpx.Client, row: GitConnectionORM) -> None:
    """Revoke the app's authorization for this connection's user, as best GitHub allows.

    GitHub identifies the grant by a token that still works, so an expired one is
    refreshed first. A refused refresh means the grant is already gone.
    """
    tokens = _load(row)
    token = tokens["access_token"]
    expires = row.access_token_expires_at
    if expires is not None and expires <= _utcnow().replace(tzinfo=None):
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            return
        try:
            token = _token_request(
                cfg, http, {"grant_type": "refresh_token", "refresh_token": refresh_token}
            ).access_token
        except (_TokenError, UpstreamException):
            return
    try:
        response = http.request(
            "DELETE",
            f"{API_URL}/applications/{cfg.client_id}/grant",
            auth=(cfg.client_id, cfg.client_secret),
            json={"access_token": token},
            headers=API_HEADERS,
        )
        if response.status_code not in (204, 404, 422):
            logger.warning("GitHub refused to revoke a grant: %s", response.status_code)
    except httpx.HTTPError as exc:
        logger.warning("Could not reach GitHub to revoke a grant: %s", exc)


def disconnect(session: Session, user_id: Any, *, client: Optional[httpx.Client] = None) -> None:
    """Revoke the app's authorization on GitHub, then forget the connection.

    Installations stay: they belong to GitHub accounts, which manage them there.
    """
    row = _connection(session, user_id, lock=True)
    if row is None:
        raise GitNotConnectedException()
    cfg = config()
    with _http(client) as http:
        _revoke(cfg, http, row)
    session.delete(row)
    session.commit()


def forget_connections(session: Session, user_id: Any, *, client: Optional[httpx.Client] = None) -> None:
    """Revoke and delete every connection of an account that is being deleted.

    Leaves the commit to the caller. A GitHub that cannot be reached, or an
    environment without the app, does not stop the deletion.
    """
    rows = session.exec(
        select(GitConnectionORM).where(GitConnectionORM.user_id == user_id).with_for_update()
    ).all()
    if not rows:
        return
    try:
        cfg: Optional[AppConfig] = config()
    except UnavailableException:
        cfg = None
    with _http(client) as http:
        for row in rows:
            if cfg is not None and row.provider == GitProvider.GITHUB and row.host == HOST:
                _revoke(cfg, http, row)
            session.delete(row)


def _installations(http: httpx.Client, token: str) -> list[dict[str, Any]]:
    installations: list[dict[str, Any]] = []
    page = 1
    while True:
        body = _get(http, "/user/installations", token, per_page=100, page=page)
        for item in body["installations"]:
            installations.append(
                {
                    "id": item["id"],
                    "account": item["account"]["login"],
                    "account_type": item["account"]["type"],
                    "repository_selection": item["repository_selection"],
                    "html_url": item["html_url"],
                }
            )
        if len(installations) >= body["total_count"] or not body["installations"]:
            return installations
        page += 1


def list_installations(
    session: Session, user_id: Any, *, client: Optional[httpx.Client] = None
) -> list[dict[str, Any]]:
    """The app's installations this user can see, on their account and their orgs."""
    token = access_token(session, user_id, client=client)
    with _http(client) as http:
        return _installations(http, token)


# ── Repositories ──────────────────────────────────────────────────────

REPO_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
FULL_NAME = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")


def _not_installed(account: str) -> CodedNotFoundException:
    return CodedNotFoundException(
        f"The Freepod GitHub App is not installed on {account}. Install it from Freepod's "
        "Git settings, then try again.",
        code="github_app_not_installed",
    )


def _repository_read(repo: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": repo["id"],
        "full_name": repo["full_name"],
        "html_url": repo["html_url"],
        "clone_url": repo["clone_url"],
        "private": repo["private"],
        "default_branch": repo.get("default_branch"),
    }


def create_repository(
    session: Session,
    user_id: Any,
    *,
    name: str,
    owner: Optional[str] = None,
    private: bool = True,
    description: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> dict[str, Any]:
    """Create an empty repository on the user's account or one of their organizations.

    The app must already be installed on that account: the repository is useful to
    Freepod only if the app can reach it, and an installation limited to selected
    repositories gets the new one added.
    """
    if not REPO_NAME.match(name) or name in (".", ".."):
        raise InvalidInputException(
            "A repository name is 1 to 100 letters, digits, '.', '-' and '_'.",
            code="github_repo_name_invalid",
        )
    cfg = config()
    token = access_token(session, user_id, client=client)
    row = _connection(session, user_id)
    assert row is not None
    target = owner or row.login

    with _http(client) as http:
        installation = next(
            (i for i in _installations(http, token) if i["account"].lower() == target.lower()),
            None,
        )
        if installation is None:
            raise _not_installed(target)

        personal = installation["account_type"] == "User"
        if personal and target.lower() != row.login.lower():
            raise PermissionDeniedException(
                f"Repositories can be created on your own account or an organization, not on {target}.",
                code="github_repo_owner_invalid",
            )
        path = "/user/repos" if personal else f"/orgs/{installation['account']}/repos"
        payload: dict[str, Any] = {"name": name, "private": private, "auto_init": False}
        if description:
            payload["description"] = description
        response = _call(http, "POST", path, token, body=payload)
        if response.status_code == 422 and "already exists" in response.text:
            raise ConflictException(
                f"{installation['account']}/{name} already exists on GitHub.", code="github_repo_exists"
            )
        if response.status_code in (403, 404):
            raise PermissionDeniedException(
                f"GitHub did not let you create a repository on {installation['account']}.",
                code="github_repo_create_forbidden",
            )
        if response.status_code != 201:
            raise _refused(path, response)
        repo = response.json()

        if installation["repository_selection"] == "selected":
            reachable = _call(http, "GET", f"/repos/{repo['full_name']}/installation", app_jwt(cfg))
            if reachable.status_code == 404:
                added = _call(
                    http,
                    "PUT",
                    f"/user/installations/{installation['id']}/repositories/{repo['id']}",
                    token,
                )
                if added.status_code != 204:
                    logger.warning(
                        "Could not add %s to installation %s: %s",
                        repo["full_name"],
                        installation["id"],
                        added.status_code,
                    )
                    raise ConflictException(
                        f"{repo['full_name']} was created, but the Freepod app cannot reach it. "
                        f"Add it to the app's repositories at {installation['html_url']}.",
                        code="github_repo_not_reachable",
                    )
    return _repository_read(repo)


def mint_credential(
    session: Session,
    user_id: Any,
    *,
    repository: str,
    access: str = "write",
    client: Optional[httpx.Client] = None,
) -> dict[str, Any]:
    """A one-hour token for git over HTTPS, limited to one repository's contents.

    The token carries the app's permissions, so the user's own permission on the
    repository decides first: nobody gets more through Freepod than GitHub gives them.
    """
    if not FULL_NAME.match(repository):
        raise InvalidInputException(
            "A repository is named as owner/name.", code="github_repo_name_invalid"
        )
    if access not in ("read", "write"):
        raise InvalidInputException("access is read or write.", code="git_access_invalid")
    cfg = config()
    token = access_token(session, user_id, client=client)

    with _http(client) as http:
        response = _call(http, "GET", f"/repos/{repository}", token)
        if response.status_code == 401:
            raise GitNotConnectedException("GitHub no longer accepts this connection. Connect again.")
        if response.status_code == 404:
            raise CodedNotFoundException(
                f"GitHub repository {repository} does not exist, or the Freepod app is not "
                "installed on it.",
                code="github_repo_not_found",
            )
        if response.status_code != 200:
            raise _refused(f"/repos/{repository}", response)
        repo = response.json()
        needed = "push" if access == "write" else "pull"
        if not repo.get("permissions", {}).get(needed):
            raise PermissionDeniedException(
                f"Your GitHub account cannot {'push to' if access == 'write' else 'read'} {repo['full_name']}.",
                code="github_repo_forbidden",
            )

        jwt_token = app_jwt(cfg)
        found = _call(http, "GET", f"/repos/{repo['full_name']}/installation", jwt_token)
        if found.status_code == 404:
            raise _not_installed(repo["owner"]["login"])
        if found.status_code != 200:
            raise _refused("/repos/.../installation", found)
        installation_id = found.json()["id"]

        minted = _call(
            http,
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            jwt_token,
            body={"repository_ids": [repo["id"]], "permissions": {"contents": access}},
        )
        if minted.status_code != 201:
            raise _refused("/app/installations/.../access_tokens", minted)
        body = minted.json()

    return {
        "repository": repo["full_name"],
        "username": "x-access-token",
        "password": body["token"],
        "expires_at": body["expires_at"],
    }


def resolve_repository(
    session: Session, user_id: Any, repository: str, *, client: Optional[httpx.Client] = None
) -> dict[str, Any]:
    """A repository the user can see and the app can reach, with the installation that reaches it."""
    if not FULL_NAME.match(repository):
        raise InvalidInputException(
            "A repository is named as owner/name.", code="github_repo_name_invalid"
        )
    cfg = config()
    token = access_token(session, user_id, client=client)
    with _http(client) as http:
        response = _call(http, "GET", f"/repos/{repository}", token)
        if response.status_code == 401:
            raise GitNotConnectedException("GitHub no longer accepts this connection. Connect again.")
        if response.status_code == 404:
            raise CodedNotFoundException(
                f"GitHub repository {repository} does not exist, or the Freepod app is not "
                "installed on it.",
                code="github_repo_not_found",
            )
        if response.status_code != 200:
            raise _refused(f"/repos/{repository}", response)
        repo = response.json()
        found = _call(http, "GET", f"/repos/{repo['full_name']}/installation", app_jwt(cfg))
        if found.status_code == 404:
            raise _not_installed(repo["owner"]["login"])
        if found.status_code != 200:
            raise _refused("/repos/.../installation", found)
    return {
        "id": repo["id"],
        "full_name": repo["full_name"],
        "default_branch": repo.get("default_branch"),
        "html_url": repo["html_url"],
        "installation_id": found.json()["id"],
    }


REPOSITORY_LISTING_LIMIT = 1000


def list_repositories(
    session: Session, user_id: Any, *, client: Optional[httpx.Client] = None
) -> list[dict[str, Any]]:
    """The repositories the app can reach for this user, most recently pushed first."""
    token = access_token(session, user_id, client=client)
    repositories: dict[int, dict[str, Any]] = {}
    with _http(client) as http:
        for installation in _installations(http, token):
            page = 1
            while len(repositories) < REPOSITORY_LISTING_LIMIT:
                body = _get(
                    http,
                    f"/user/installations/{installation['id']}/repositories",
                    token,
                    per_page=100,
                    page=page,
                )
                for repo in body["repositories"]:
                    repositories[repo["id"]] = {
                        "id": repo["id"],
                        "full_name": repo["full_name"],
                        "private": repo["private"],
                        "default_branch": repo.get("default_branch"),
                        "html_url": repo["html_url"],
                        "pushed_at": repo.get("pushed_at"),
                    }
                if page * 100 >= body["total_count"] or not body["repositories"]:
                    break
                page += 1
    return sorted(repositories.values(), key=lambda r: r["pushed_at"] or "", reverse=True)
