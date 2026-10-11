"""OAuth2 flows, flow selection, and the token cache."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import threading
import urllib.parse
import urllib.request

import pytest

from freepod import AuthenticationError, FreepodError
from freepod.auth import (
    OAuthError,
    Session,
    b64url,
    decode_claims,
    detect_browser,
    forget_environment,
    format_claims,
    load_refresh_token,
    pkce_pair,
    store_refresh_token,
)
from freepod.config import ENVIRONMENTS, token_cache_path

PROD = ENVIRONMENTS["prod"]
DEV = ENVIRONMENTS["dev"]


def make_jwt(claims: dict) -> str:
    """A structurally valid JWT with a bogus signature — nothing verifies it."""
    header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = b64url(json.dumps(claims).encode())
    return f"{header}.{payload}.c2lnbmF0dXJl"


# --------------------------------------------------------------------------
# PKCE
# --------------------------------------------------------------------------


def test_pkce_challenge_is_the_s256_of_the_verifier():
    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128  # RFC 7636 section 4.1
    expected = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    assert challenge == expected
    assert "=" not in challenge  # base64url, unpadded


def test_pkce_pairs_are_not_reused():
    assert pkce_pair()[0] != pkce_pair()[0]


# --------------------------------------------------------------------------
# Loopback flow (task 3.1)
# --------------------------------------------------------------------------


def drive_callback(monkeypatch, params_for):
    """Patch `webbrowser.open` to act as the browser Keycloak would redirect.

    The callback is fired from a thread: `loopback_flow` calls `open()` before
    it starts serving, so a blocking request here would deadlock.
    """
    fired = {}

    def opener(url: str) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        redirect_uri = query["redirect_uri"][0]
        state = query["state"][0]
        fired["authorization_url"] = url
        fired["query"] = {key: values[0] for key, values in query.items()}

        params = params_for(state)

        def fire():
            target = redirect_uri + "?" + urllib.parse.urlencode(params)
            try:
                urllib.request.urlopen(target, timeout=5).read()
            except Exception:  # pragma: no cover - the assertion is on the flow
                pass

        threading.Thread(target=fire, daemon=True).start()
        return True

    monkeypatch.setattr("freepod.auth.webbrowser.open", opener)
    return fired


def test_a_browser_login_yields_a_credential(monkeypatch):
    from freepod import auth

    fired = drive_callback(monkeypatch, lambda state: {"code": "the-code", "state": state})
    exchanged = {}

    def fake_post_form(url, fields, timeout=30):
        exchanged.update(fields)
        exchanged["url"] = url
        return {"access_token": "at", "refresh_token": "rt"}

    monkeypatch.setattr(auth, "post_form", fake_post_form)

    tokens = auth.loopback_flow(PROD, timeout=10)

    assert tokens["access_token"] == "at"
    assert exchanged["grant_type"] == "authorization_code"
    assert exchanged["code"] == "the-code"
    # The verifier accompanies the exchange, and matches the challenge sent.
    challenge = b64url(hashlib.sha256(exchanged["code_verifier"].encode()).digest())
    assert fired["query"]["code_challenge"] == challenge
    assert fired["query"]["code_challenge_method"] == "S256"
    # The redirect must land on exactly /callback: Keycloak relaxes port
    # matching for loopback hosts but matches the path exactly.
    assert exchanged["redirect_uri"].startswith("http://127.0.0.1:")
    assert exchanged["redirect_uri"].endswith("/callback")


def test_a_mismatched_state_is_refused(monkeypatch):
    from freepod import auth

    drive_callback(monkeypatch, lambda _state: {"code": "the-code", "state": "not-ours"})
    monkeypatch.setattr(
        auth,
        "post_form",
        lambda *a, **k: pytest.fail("the code must not be exchanged after a state mismatch"),
    )

    with pytest.raises(FreepodError, match="state mismatch"):
        auth.loopback_flow(PROD, timeout=10)


def test_an_authorization_error_on_the_redirect_is_reported(monkeypatch):
    from freepod import auth

    drive_callback(
        monkeypatch,
        lambda _state: {"error": "access_denied", "error_description": "User said no"},
    )

    with pytest.raises(OAuthError, match="User said no"):
        auth.loopback_flow(PROD, timeout=10)


def test_the_loopback_wait_is_bounded(monkeypatch):
    """The listener stops and the command fails rather than hanging."""
    from freepod import auth

    monkeypatch.setattr("freepod.auth.webbrowser.open", lambda _url: False)

    with pytest.raises(FreepodError, match="timed out"):
        auth.loopback_flow(PROD, timeout=0)


def test_a_non_callback_path_is_not_mistaken_for_the_redirect(monkeypatch):
    """Browsers speculatively fetch /favicon.ico; it must not end the wait."""
    from freepod import auth

    def opener(url: str) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        redirect_uri = query["redirect_uri"][0]
        state = query["state"][0]
        root = redirect_uri.rsplit("/callback", 1)[0]

        def fire():
            try:
                urllib.request.urlopen(f"{root}/favicon.ico", timeout=5).read()
            except Exception:
                pass  # a 404 is the point
            try:
                target = redirect_uri + "?" + urllib.parse.urlencode(
                    {"code": "the-code", "state": state}
                )
                urllib.request.urlopen(target, timeout=5).read()
            except Exception:  # pragma: no cover
                pass

        threading.Thread(target=fire, daemon=True).start()
        return True

    monkeypatch.setattr("freepod.auth.webbrowser.open", opener)
    monkeypatch.setattr(
        auth, "post_form", lambda *a, **k: {"access_token": "at", "refresh_token": "rt"}
    )

    assert auth.loopback_flow(PROD, timeout=10)["access_token"] == "at"


# --------------------------------------------------------------------------
# Device flow (task 3.2)
# --------------------------------------------------------------------------


DEVICE_AUTHORIZATION = {
    "device_code": "dc",
    "user_code": "ABCD-EFGH",
    "verification_uri": "https://keycloak.freepod.eu/realms/freepod/device",
    "verification_uri_complete": (
        "https://keycloak.freepod.eu/realms/freepod/device?user_code=ABCD-EFGH"
    ),
    "interval": 5,
    "expires_in": 600,
}


def device_post_form(monkeypatch, poll_results):
    """Patch `post_form` for a device run: one authorization, then polls."""
    from freepod import auth

    calls = []
    remaining = list(poll_results)

    def fake_post_form(url, fields, timeout=30):
        calls.append(fields)
        if fields.get("scope"):  # the device authorization request
            return dict(DEVICE_AUTHORIZATION)
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(auth, "post_form", fake_post_form)
    return calls


def test_a_headless_host_obtains_a_credential(monkeypatch):
    from freepod import auth

    calls = device_post_form(monkeypatch, [{"access_token": "at", "refresh_token": "rt"}])

    tokens = auth.device_flow(DEV)

    assert tokens["refresh_token"] == "rt"
    # Keycloak enforces PKCE on the device endpoint, which RFC 8628 does not
    # require; omitting the challenge fails with "Missing parameter".
    assert calls[0]["code_challenge_method"] == "S256"
    challenge = calls[0]["code_challenge"]
    # ...and the verifier must accompany every poll, not just the first.
    verifier = calls[1]["code_verifier"]
    assert b64url(hashlib.sha256(verifier.encode()).digest()) == challenge


def test_pending_approval_is_not_an_error(monkeypatch):
    from freepod import auth

    calls = device_post_form(
        monkeypatch,
        [
            OAuthError("pending", code="authorization_pending"),
            OAuthError("pending", code="authorization_pending"),
            {"access_token": "at", "refresh_token": "rt"},
        ],
    )

    assert auth.device_flow(DEV)["access_token"] == "at"
    assert len(calls) == 4  # one authorization + three polls
    # Every poll carries the same verifier.
    verifiers = {call["code_verifier"] for call in calls[1:]}
    assert len(verifiers) == 1


def test_a_slow_down_response_widens_the_interval(monkeypatch, capsys):
    from freepod import auth

    device_post_form(
        monkeypatch,
        [
            OAuthError("slow down", code="slow_down"),
            {"access_token": "at", "refresh_token": "rt"},
        ],
    )

    auth.device_flow(DEV)

    stderr = capsys.readouterr().err
    assert "polling every 5s" in stderr  # the interval it started at
    assert "polling every 10s" in stderr  # widened by the slow_down


def test_an_expired_device_code_is_explained(monkeypatch):
    from freepod import auth

    device_post_form(monkeypatch, [OAuthError("expired", code="expired_token")])

    with pytest.raises(FreepodError, match="expired"):
        auth.device_flow(DEV)


def test_a_denied_authorization_is_explained(monkeypatch):
    from freepod import auth

    device_post_form(monkeypatch, [OAuthError("denied", code="access_denied")])

    with pytest.raises(FreepodError, match="denied"):
        auth.device_flow(DEV)


def test_the_user_code_is_displayed_even_with_a_complete_uri(monkeypatch, capsys):
    """RFC 8628 section 3.3.1 requires it, and Keycloak does not echo it back."""
    from freepod import auth

    device_post_form(monkeypatch, [{"access_token": "at", "refresh_token": "rt"}])
    auth.device_flow(DEV)

    stderr = capsys.readouterr().err
    assert "ABCD-EFGH" in stderr
    assert DEVICE_AUTHORIZATION["verification_uri_complete"] in stderr


# --------------------------------------------------------------------------
# Flow selection (task 3.3)
# --------------------------------------------------------------------------


def test_a_container_selects_the_device_flow(monkeypatch):
    monkeypatch.setattr("freepod.auth.os.path.exists", lambda path: path == "/.dockerenv")
    usable, reason = detect_browser()
    assert usable is False
    assert "container" in reason


def test_a_linux_host_with_no_display_selects_the_device_flow(monkeypatch):
    monkeypatch.setattr("freepod.auth.os.path.exists", lambda _path: False)
    monkeypatch.setattr("freepod.auth.sys.platform", "linux")
    monkeypatch.setattr("builtins.open", _raise_oserror(), raising=False)
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "BROWSER"):
        monkeypatch.delenv(name, raising=False)

    usable, reason = detect_browser()
    assert usable is False
    assert "DISPLAY" in reason


def _raise_oserror():
    def opener(*args, **kwargs):
        raise OSError("no /proc here")

    return opener


@pytest.mark.parametrize("forced", ["loopback", "device"])
def test_the_flow_choice_can_be_forced(forced, monkeypatch):
    monkeypatch.setattr(
        "freepod.auth.detect_browser",
        lambda: pytest.fail("detection must not run when the flow is forced"),
    )
    session = Session(PROD, timeout=10, force_flow=forced)
    flow, reason = session.choose_flow()
    assert flow == forced
    assert "forced" in reason


def test_detection_decides_when_the_flow_is_not_forced(monkeypatch):
    monkeypatch.setattr("freepod.auth.detect_browser", lambda: (True, "browser available (test)"))
    flow, reason = Session(PROD, timeout=10).choose_flow()
    assert flow == "loopback"
    assert "browser available" in reason


# --------------------------------------------------------------------------
# Token cache (task 3.4)
# --------------------------------------------------------------------------


def test_the_cache_is_keyed_by_environment():
    store_refresh_token("prod", "freepod-cli-prod", "prod-refresh")
    store_refresh_token("dev", "freepod-cli-dev", "dev-refresh")

    assert load_refresh_token("prod") == "prod-refresh"
    assert load_refresh_token("dev") == "dev-refresh"


def test_a_credential_for_one_environment_is_never_offered_to_the_other():
    store_refresh_token("dev", "freepod-cli-dev", "dev-refresh")
    assert load_refresh_token("prod") is None


def test_signing_out_of_one_environment_leaves_the_other_untouched():
    store_refresh_token("prod", "freepod-cli-prod", "prod-refresh")
    store_refresh_token("dev", "freepod-cli-dev", "dev-refresh")

    assert forget_environment("dev") is True

    assert load_refresh_token("dev") is None
    assert load_refresh_token("prod") == "prod-refresh"


def test_signing_out_with_nothing_cached_reports_so():
    assert forget_environment("prod") is False


@pytest.mark.posix
def test_the_cache_is_not_world_readable():
    store_refresh_token("prod", "freepod-cli-prod", "prod-refresh")
    path = token_cache_path()

    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700


def test_a_corrupt_cache_is_treated_as_empty():
    from freepod.config import ensure_config_dir

    ensure_config_dir()
    token_cache_path().write_text("{not json", encoding="utf-8")
    assert load_refresh_token("prod") is None


def test_writing_the_cache_leaves_no_temporary_behind():
    store_refresh_token("prod", "freepod-cli-prod", "prod-refresh")
    leftovers = [p.name for p in token_cache_path().parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


# --------------------------------------------------------------------------
# Session: refresh, fallback, and reuse
# --------------------------------------------------------------------------


def test_a_later_command_reuses_the_cached_credential(monkeypatch):
    from freepod import auth

    store_refresh_token("prod", "freepod-cli-prod", "prod-refresh")
    monkeypatch.setattr(
        auth, "post_form", lambda url, fields, timeout=30: {"access_token": "fresh-at"}
    )
    monkeypatch.setattr(
        Session, "login", lambda self: pytest.fail("a cached credential must not prompt a login")
    )

    session = Session(PROD, timeout=10)
    session.authenticate()

    assert session.access_token == "fresh-at"
    assert session.credential_source == "cached refresh token"


def test_a_refresh_response_without_a_new_refresh_token_keeps_the_old_one(monkeypatch):
    """`revokeRefreshToken` is false on this realm, so the response may omit it."""
    from freepod import auth

    store_refresh_token("prod", "freepod-cli-prod", "original-refresh")
    monkeypatch.setattr(
        auth, "post_form", lambda url, fields, timeout=30: {"access_token": "fresh-at"}
    )

    session = Session(PROD, timeout=10)
    session.authenticate()

    assert session.refresh_token == "original-refresh"
    assert load_refresh_token("prod") == "original-refresh"


def test_a_rejected_refresh_falls_back_to_a_full_login(monkeypatch):
    from freepod import auth

    store_refresh_token("prod", "freepod-cli-prod", "stale-refresh")

    def fake_post_form(url, fields, timeout=30):
        raise OAuthError("Token is not active", code="invalid_grant", status=400)

    monkeypatch.setattr(auth, "post_form", fake_post_form)
    logins = []
    monkeypatch.setattr(Session, "login", lambda self: logins.append(True))

    session = Session(PROD, timeout=10)
    session.authenticate()

    assert logins == [True]
    assert session.credential_source == "fresh login"


def test_a_non_interactive_session_refuses_rather_than_logging_in(monkeypatch):
    monkeypatch.setattr(
        Session, "login", lambda self: pytest.fail("whoami must not open a browser")
    )
    session = Session(PROD, timeout=10)

    with pytest.raises(AuthenticationError, match="not authenticated"):
        session.authenticate(interactive=False)


def test_a_non_interactive_session_reports_an_unusable_cached_credential(monkeypatch):
    from freepod import auth

    store_refresh_token("prod", "freepod-cli-prod", "stale-refresh")
    monkeypatch.setattr(
        auth,
        "post_form",
        lambda *a, **k: (_ for _ in ()).throw(OAuthError("nope", code="invalid_grant")),
    )
    monkeypatch.setattr(
        Session, "login", lambda self: pytest.fail("whoami must not open a browser")
    )

    with pytest.raises(AuthenticationError, match="no longer valid"):
        Session(PROD, timeout=10).authenticate(interactive=False)


# --------------------------------------------------------------------------
# Tokens are never displayed (task 3.5)
# --------------------------------------------------------------------------


def test_claims_are_decoded_without_verification():
    token = make_jwt({"email": "erik@example.com", "aud": "freepod-api"})
    assert decode_claims(token)["email"] == "erik@example.com"


def test_an_undecodable_token_yields_no_claims():
    assert decode_claims("not-a-jwt") == {}


def test_the_claims_display_never_contains_the_token():
    token = make_jwt({"email": "erik@example.com", "sub": "abc", "exp": 4102444800})
    rendered = format_claims(token)

    assert "erik@example.com" in rendered
    assert token not in rendered
    for segment in token.split("."):
        assert segment not in rendered


def test_no_token_reaches_the_output_of_a_full_login(monkeypatch, capsys):
    """The strongest form of the rule: run a login and grep both streams."""
    from freepod import auth

    access_token = make_jwt({"email": "erik@example.com", "exp": 4102444800})
    refresh_token = "REFRESH-SECRET-VALUE"

    drive_callback(monkeypatch, lambda state: {"code": "the-code", "state": state})
    monkeypatch.setattr(
        auth,
        "post_form",
        lambda *a, **k: {"access_token": access_token, "refresh_token": refresh_token},
    )
    monkeypatch.setattr(auth, "detect_browser", lambda: (True, "browser available (test)"))

    session = Session(PROD, timeout=10, verbose=True)
    session.authenticate()
    print(format_claims(session.access_token), file=__import__("sys").stderr)

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert access_token not in combined
    assert refresh_token not in combined
    assert "erik@example.com" in combined  # the claims themselves are fine
