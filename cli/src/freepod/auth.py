"""OAuth2 flows, the token cache, and the session that renews a credential.

Lifted from the dependency-free demo client this package replaced, with three
changes: the Keycloak calls go over `httpx` so the package has one HTTP stack,
the loopback listener stays on the standard library's `HTTPServer` because that
is not an `httpx` concern, and the environment default now comes from
`config.py`, where it is `prod`. The demo lived at `cli/freepod_cli.py` and its
history is in git; the reasoning it carried is in the change's design document.

Two flows:

* **loopback** — authorization code + PKCE, with the code arriving on a
  listener bound to an ephemeral port on `127.0.0.1`. Needs a browser on this
  machine that can actually reach that interface.
* **device** — the device authorization grant, approved on any other device.

The flow is auto-detected and overridable. See design D3.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx

from . import AuthenticationError, FreepodError
from .config import (
    DEFAULT_HTTP_TIMEOUT,
    DEVICE_GRANT,
    SCOPES,
    USER_AGENT,
    Environment,
    ensure_config_dir,
    env_suffix,
    login_command,
    token_cache_path,
)

# The registered redirect URIs are the port-less forms http://127.0.0.1/callback
# and http://localhost/callback. Keycloak relaxes *port* matching for loopback
# hosts (RFC 8252 section 7.3), so any ephemeral port matches — but the path is
# matched exactly and the two host strings are distinct. Do not change this.
CALLBACK_PATH = "/callback"
CALLBACK_HOST = "127.0.0.1"

CACHE_VERSION = 1


class OAuthError(FreepodError):
    """An OAuth2 error response, carrying the machine-readable `error` code."""

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        status: Optional[int] = None,
    ):
        super().__init__(message)
        self.code = code
        self.status = status


def log(message: str) -> None:
    """Diagnostics go to stderr so stdout carries only results."""
    print(message, file=sys.stderr)


# --------------------------------------------------------------------------
# PKCE and token inspection
# --------------------------------------------------------------------------


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def pkce_pair() -> Tuple[str, str]:
    """Return (code_verifier, code_challenge) for the S256 method."""
    verifier = b64url(secrets.token_bytes(64))  # 86 chars, within RFC 7636's 43-128
    challenge = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def decode_claims(jwt: str) -> Dict[str, Any]:
    """Decode a JWT payload *without verifying it* — for display only.

    The platform is what verifies tokens; this client never makes a trust
    decision on the strength of these claims.
    """
    try:
        payload = jwt.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except Exception:
        return {}


def format_claims(access_token: str) -> str:
    """Render the interesting claims for `--verbose`.

    Deliberately renders *claims*, never the token itself: no code path in this
    client prints raw token material.
    """
    claims = decode_claims(access_token)
    if not claims:
        return "  (could not decode the access token payload)"

    lines = ["  Access token claims (unverified, for display only):"]
    for name in ("iss", "azp", "aud", "sub", "email", "preferred_username", "groups", "scope"):
        if name in claims:
            lines.append(f"    {name:20} {claims[name]}")
    for name in ("iat", "exp"):
        if name in claims:
            when = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(claims[name]))
            lines.append(f"    {name:20} {claims[name]} ({when})")
    if "exp" in claims:
        lines.append(f"    {'expires in':20} {int(claims['exp'] - time.time())}s")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Keycloak calls
# --------------------------------------------------------------------------


def post_form(url: str, fields: Dict[str, str], timeout: int = DEFAULT_HTTP_TIMEOUT) -> dict:
    """POST an `application/x-www-form-urlencoded` body and parse the reply."""
    try:
        response = httpx.post(
            url,
            data=fields,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise FreepodError(f"cannot reach {url}: {exc}") from None

    raw = response.text
    if response.is_success:
        try:
            return response.json()
        except ValueError:
            raise FreepodError(f"unparseable response from {url}") from None

    try:
        payload = json.loads(raw)
    except ValueError:
        raise OAuthError(
            f"HTTP {response.status_code} from {url}: {raw.strip()[:300]}",
            status=response.status_code,
        ) from None

    code = payload.get("error")
    description = payload.get("error_description") or code or raw.strip()[:300]
    raise OAuthError(description, code=code, status=response.status_code)


# --------------------------------------------------------------------------
# Token cache
# --------------------------------------------------------------------------
#
# Keyed by environment, because an access token is audience-bound to exactly
# one of them: material obtained for dev must never be presented to prod.


def cache_path() -> Path:
    return token_cache_path()


def load_cache() -> dict:
    try:
        with open(cache_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_cache(data: dict) -> None:
    """Write the cache atomically at mode 0600, in a 0700 directory.

    Atomic-replace rather than truncate-and-write: an interrupted write must
    not destroy a working credential.
    """
    ensure_config_dir()
    path = cache_path()
    temporary = f"{path}.{os.getpid()}.tmp"
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)


def load_refresh_token(env: str) -> Optional[str]:
    entry = load_cache().get("environments", {}).get(env) or {}
    token = entry.get("refresh_token")
    return token if isinstance(token, str) and token else None


def store_refresh_token(env: str, client_id: str, refresh_token: Optional[str]) -> None:
    if not refresh_token:
        return
    data = load_cache()
    environments = data.setdefault("environments", {})
    environments[env] = {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "stored_at": int(time.time()),
    }
    data["version"] = CACHE_VERSION
    save_cache(data)


def forget_environment(env: str) -> bool:
    """Drop one environment's cached credential. Others are untouched."""
    data = load_cache()
    environments = data.get("environments", {})
    if env not in environments:
        return False
    del environments[env]
    save_cache(data)
    return True


# --------------------------------------------------------------------------
# Flow selection
# --------------------------------------------------------------------------


def detect_browser() -> Tuple[bool, str]:
    """Decide whether a browser on *this* machine can serve a loopback redirect.

    A container is disqualifying even if a browser binary exists: the redirect
    lands on the container's own 127.0.0.1, which the user's browser cannot
    reach.
    """
    if os.path.exists("/.dockerenv"):
        return False, "running in a container (/.dockerenv present)"

    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8") as handle:
            cgroup = handle.read()
        if any(marker in cgroup for marker in ("docker", "containerd", "kubepods", "libpod")):
            return False, "running in a container (container runtime in /proc/1/cgroup)"
    except OSError:
        pass

    if sys.platform.startswith("linux") and not any(
        os.environ.get(name) for name in ("DISPLAY", "WAYLAND_DISPLAY", "BROWSER")
    ):
        return False, "no DISPLAY, WAYLAND_DISPLAY or BROWSER set on Linux"

    try:
        browser = webbrowser.get()
    except webbrowser.Error:
        return False, "webbrowser found no usable browser"

    name = getattr(browser, "name", None) or type(browser).__name__
    return True, f"browser available ({name})"


# --------------------------------------------------------------------------
# Flow (a): authorization code + PKCE over a loopback listener
# --------------------------------------------------------------------------


class _CallbackHandler(BaseHTTPRequestHandler):
    """Serves the single redirect Keycloak sends the browser to."""

    server_version = "freepod"
    sys_version = ""

    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler's naming
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            # Browsers speculatively fetch /favicon.ico; ignore anything that
            # is not the redirect rather than treating it as the one request.
            self.send_error(404, "Not the callback")
            return

        params = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query).items()}
        self.server.oauth_result = params

        if "error" in params:
            title = "Authorization failed"
            detail = params.get("error_description", params["error"])
        else:
            title = "Signed in to Freepod"
            detail = "You can close this tab and return to your terminal."

        page = (
            "<!doctype html><meta charset='utf-8'>"
            "<title>Freepod CLI</title>"
            "<body style=\"font-family:system-ui,sans-serif;margin:4rem auto;max-width:32rem\">"
            f"<h1 style='font-size:1.25rem'>{title}</h1><p>{detail}</p></body>"
        ).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, fmt, *args):
        """Silence the default stderr access log."""


def loopback_flow(env: Environment, timeout: int, verbose: bool = False) -> dict:
    verifier, challenge = pkce_pair()
    state = secrets.token_hex(32)

    # Bind first: the ephemeral port is part of the redirect_uri registered in
    # the authorization request.
    server = HTTPServer((CALLBACK_HOST, 0), _CallbackHandler)
    server.oauth_result = None
    server.timeout = 1
    port = server.server_address[1]
    redirect_uri = f"http://{CALLBACK_HOST}:{port}{CALLBACK_PATH}"

    authorization_url = (
        env.authorization_endpoint
        + "?"
        + urllib.parse.urlencode(
            {
                "client_id": env.client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": SCOPES,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )

    log(f"Listening on {redirect_uri} for the authorization redirect.")
    if verbose:
        log(f"Authorization URL: {authorization_url}")

    try:
        if webbrowser.open(authorization_url):
            log("Opened your browser to sign in.")
        else:
            log(f"Could not open a browser automatically. Visit this URL:\n  {authorization_url}")

        deadline = time.monotonic() + timeout
        while server.oauth_result is None:
            if time.monotonic() >= deadline:
                raise FreepodError(
                    f"timed out after {timeout}s waiting for the authorization redirect "
                    "(use --device for a browser-less flow)"
                )
            server.handle_request()
        params = server.oauth_result
    finally:
        server.server_close()

    if "error" in params:
        raise OAuthError(params.get("error_description", params["error"]), code=params["error"])
    if params.get("state") != state:
        raise FreepodError(
            "state mismatch on the authorization redirect — possible CSRF, refusing the response"
        )
    if "code" not in params:
        raise FreepodError("authorization redirect carried no code")

    log("Received the authorization code; exchanging it for tokens.")
    return post_form(
        env.token_endpoint,
        {
            "grant_type": "authorization_code",
            "client_id": env.client_id,
            "code": params["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
    )


# --------------------------------------------------------------------------
# Flow (b): device authorization grant
# --------------------------------------------------------------------------


def device_flow(env: Environment, verbose: bool = False) -> dict:
    verifier, challenge = pkce_pair()

    # RFC 8628 has no redirect and therefore no PKCE, but these clients mandate
    # PKCE and Keycloak enforces it on the device endpoint too. Omitting the
    # challenge here fails with "Missing parameter: code_challenge_method".
    authorization = post_form(
        env.device_endpoint,
        {
            "client_id": env.client_id,
            "scope": SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )

    device_code = authorization["device_code"]
    user_code = authorization["user_code"]
    interval = int(authorization.get("interval", 1))
    expires_in = int(authorization.get("expires_in", 600))
    verification_uri = authorization["verification_uri"]
    complete_uri = authorization.get("verification_uri_complete")

    # RFC 8628 section 3.3.1 requires the client to display the user_code even
    # when it offers verification_uri_complete. Keycloak does not echo the code
    # back on the complete-URI path, though — it consumes it from the query
    # string and goes straight to sign-in — so the code is presented here as a
    # manual fallback, not as something to confirm on screen.
    log("\nTo sign in, open this URL in any browser — on this machine or another:\n")
    if complete_uri:
        log(f"    {complete_uri}\n")
        log(f"  That link already carries the code {user_code}, so you will not")
        log("  be asked for it. To type it in by hand instead, open")
        log(f"  {verification_uri} and enter {user_code}\n")
    else:
        log(f"    {verification_uri}\n")
        log(f"  and enter the code:  {user_code}\n")
    log(f"Waiting up to {expires_in}s for approval (polling every {interval}s)...")

    deadline = time.monotonic() + expires_in
    while True:
        time.sleep(interval)
        if time.monotonic() >= deadline:
            raise FreepodError(f"device code expired after {expires_in}s without approval")

        try:
            tokens = post_form(
                env.token_endpoint,
                {
                    "grant_type": DEVICE_GRANT,
                    "client_id": env.client_id,
                    "device_code": device_code,
                    "code_verifier": verifier,
                },
            )
        except OAuthError as exc:
            if exc.code == "authorization_pending":
                if verbose:
                    log("  ...still pending")
                continue
            if exc.code == "slow_down":
                interval += 5
                log(f"  ...server asked us to slow down; polling every {interval}s")
                continue
            if exc.code == "expired_token":
                raise FreepodError(
                    "the device code expired before it was approved — rerun to get a new one"
                ) from None
            if exc.code == "access_denied":
                raise FreepodError("authorization was denied in the browser") from None
            raise

        log("Approved.")
        return tokens


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------


class Session:
    """Holds the credential for one environment and knows how to renew it.

    This class owns token acquisition only. Interpreting the API's responses —
    the 401/403 contract — belongs to `api.py`, which drives `refresh()` and
    `login()` from here.
    """

    def __init__(
        self,
        env: Environment,
        *,
        timeout: int,
        force_flow: Optional[str] = None,
        verbose: bool = False,
    ):
        self.env = env
        self.timeout = timeout
        self.force_flow = force_flow
        self.verbose = verbose
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.credential_source = "none"
        self.flow_used: Optional[str] = None

    # -- acquisition ------------------------------------------------------

    def authenticate(self, *, force_login: bool = False, interactive: bool = True) -> None:
        """Reuse a cached refresh token when possible, else run a full login.

        With `interactive=False` a missing or unusable cached credential is an
        `AuthenticationError` rather than a browser prompt, so commands that
        merely *use* a credential never silently start a login.
        """
        if not force_login:
            cached = load_refresh_token(self.env.name)
            if cached:
                if self.verbose:
                    log(f"Found a cached refresh token{env_suffix(self.env.name, 'for')}; refreshing.")
                self.refresh_token = cached
                if self.refresh():
                    self.credential_source = "cached refresh token"
                    return
                if not interactive:
                    raise AuthenticationError(
                        f"the cached credential{env_suffix(self.env.name, 'for')} is no "
                        f"longer valid — run `{login_command(self.env.name)}`"
                    )
                log("Refresh failed; falling back to a full login.")
            else:
                if not interactive:
                    raise AuthenticationError(
                        f"not authenticated{env_suffix(self.env.name, 'for')} — "
                        f"run `{login_command(self.env.name)}`"
                    )
                log(f"No cached credential{env_suffix(self.env.name, 'for')}.")

        self.login()
        self.credential_source = "fresh login"

    def login(self) -> None:
        flow, reason = self.choose_flow()
        log(f"Using the {flow} flow — {reason}.")
        self.flow_used = flow

        tokens = (
            loopback_flow(self.env, self.timeout, self.verbose)
            if flow == "loopback"
            else device_flow(self.env, self.verbose)
        )
        self.apply(tokens)

    def choose_flow(self) -> Tuple[str, str]:
        if self.force_flow == "loopback":
            return "loopback", "forced with --loopback"
        if self.force_flow == "device":
            return "device", "forced with --device"
        usable, reason = detect_browser()
        return ("loopback", reason) if usable else ("device", reason)

    def refresh(self) -> bool:
        """Exchange the refresh token for a new access token. False on failure."""
        if not self.refresh_token:
            return False
        try:
            tokens = post_form(
                self.env.token_endpoint,
                {
                    "grant_type": "refresh_token",
                    "client_id": self.env.client_id,
                    "refresh_token": self.refresh_token,
                },
            )
        except OAuthError as exc:
            if self.verbose:
                log(f"Refresh rejected: {exc}")
            return False
        self.apply(tokens)
        return True

    def apply(self, tokens: dict) -> None:
        self.access_token = tokens["access_token"]
        # revokeRefreshToken is false on this realm, so a refresh response may
        # omit a new refresh token; keep the one we already hold in that case.
        self.refresh_token = tokens.get("refresh_token") or self.refresh_token
        store_refresh_token(self.env.name, self.env.client_id, self.refresh_token)
