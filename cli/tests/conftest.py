"""Shared fixtures: an isolated HOME, and a mock HTTP transport.

Every test runs against a throwaway config directory, so a developer's real
`~/.config/freepod/tokens.json` is never read and never written, and no test
can pass because a credential happened to be lying around.
"""

from __future__ import annotations

import json
import sys
from typing import Callable, List, Optional

import httpx
import pytest

from freepod.api import ApiClient
from freepod.config import ENVIRONMENTS, Environment


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "posix: asserts POSIX permission bits or file types Windows does not have"
    )


def pytest_collection_modifyitems(config, items):
    if sys.platform != "win32":
        return
    skip = pytest.mark.skip(reason="POSIX-only behavior; Windows has no such permission bits or file type")
    for item in items:
        if "posix" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point HOME and XDG_CONFIG_HOME at a temp directory, and clear the
    environment variables that would otherwise leak the developer's settings
    into a test."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # Windows resolves `~` and `Path.home()` from USERPROFILE and ignores HOME.
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.delenv("FREEPOD_ENV", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FREEPOD_NO_SKILL", raising=False)
    monkeypatch.delenv("FREEPOD_NO_UPDATE_CHECK", raising=False)
    return home


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Make every backoff and poll interval instantaneous.

    Patched in `time`, which is what both `api` and `auth` call through.
    """
    monkeypatch.setattr("time.sleep", lambda _seconds: None)


class Recorder:
    """A `MockTransport` handler that records what it was asked."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]):
        self._handler = handler
        self.requests: List[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()  # materialize the body so a test can assert on it
        self.requests.append(request)
        return self._handler(request)

    @property
    def calls(self) -> int:
        return len(self.requests)

    def paths(self) -> List[str]:
        return [request.url.path for request in self.requests]

    def auth_headers(self) -> List[Optional[str]]:
        return [request.headers.get("authorization") for request in self.requests]


def json_response(status: int, payload) -> httpx.Response:
    """A response the API would produce: JSON body, JSON content type."""
    return httpx.Response(
        status,
        content=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def text_response(status: int, body: str = "Forbidden\n") -> httpx.Response:
    """A response the *edge* would produce.

    oauth2-proxy refuses with a bare `http.Error`: a plain-text body and no
    JSON anywhere. That difference is the only thing distinguishing an edge
    403 from the API's own.
    """
    return httpx.Response(
        status,
        content=body.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )


def sequence(*responses: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
    """Return the given responses in order, repeating the last one forever."""
    remaining = list(responses)

    def handler(_request: httpx.Request) -> httpx.Response:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return handler


class StubSession:
    """Stands in for `auth.Session` in transport tests.

    Records refreshes and logins so a test can assert the bounded-refresh rule
    without reaching Keycloak.
    """

    def __init__(self, *, access_token: str = "token-1", refresh_succeeds: bool = True):
        self.access_token = access_token
        self.refresh_token = "refresh-1"
        self.credential_source = "stub"
        self.refresh_succeeds = refresh_succeeds
        self.refreshes = 0
        self.logins = 0

    def authenticate(self, force_login: bool = False, interactive: bool = True) -> None:
        """Already holds a credential; commands may call this freely."""
        self.authentications = getattr(self, "authentications", 0) + 1

    def refresh(self) -> bool:
        self.refreshes += 1
        if not self.refresh_succeeds:
            return False
        self.access_token = f"token-{self.refreshes + 1}"
        return True

    def login(self) -> None:
        self.logins += 1
        self.access_token = f"login-token-{self.logins}"


@pytest.fixture
def stub_api(monkeypatch):
    """Replace the command's API client with one on a mock transport.

    Command-level, unlike `make_api`: it patches `Context.client`, so a test
    drives `main([...])` and the command builds its own client as it normally
    would.
    """

    def install(handler):
        from freepod.api import ApiClient
        from freepod.cli import Context

        def client(self, session):
            return ApiClient(
                self.env,
                session,
                client=httpx.Client(transport=httpx.MockTransport(handler)),
                backoff_base=0,
            )

        monkeypatch.setattr(Context, "client", client)

    return install


@pytest.fixture
def cached_credential(monkeypatch):
    """A cached refresh token for `prod`, and a Keycloak that honors it."""
    from freepod import auth
    from freepod.auth import store_refresh_token

    store_refresh_token("prod", "freepod-cli-prod", "prod-refresh")
    monkeypatch.setattr(
        auth, "post_form", lambda url, fields, timeout=30: {"access_token": "fresh-at"}
    )


@pytest.fixture
def env() -> Environment:
    return ENVIRONMENTS["prod"]


@pytest.fixture
def dev_env() -> Environment:
    return ENVIRONMENTS["dev"]


@pytest.fixture
def make_api():
    """Build an `ApiClient` wired to a mock transport.

    Returns `(client, recorder, session)` so a test can assert on both the
    requests that went out and the credential work that happened in between.
    """
    created: List[ApiClient] = []

    def factory(handler, *, environment: Optional[Environment] = None, session=None, **kwargs):
        recorder = Recorder(handler)
        transport = httpx.MockTransport(recorder)
        session = session or StubSession()
        api = ApiClient(
            environment or ENVIRONMENTS["prod"],
            session,
            client=httpx.Client(transport=transport),
            backoff_base=0,
            **kwargs,
        )
        created.append(api)
        return api, recorder, session

    yield factory

    for api in created:
        api._client.close()
