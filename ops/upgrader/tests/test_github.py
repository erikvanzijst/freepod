import base64
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from upgrader.github import (
    PULL_REQUESTS_READ,
    READ_ONLY,
    READ_WRITE,
    App,
    PullRequests,
    TokenFile,
    load_private_key,
)

from .fakes import FakeGitHub

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption())
KEY_B64 = base64.b64encode(PEM).decode()


@pytest.fixture
def github():
    return FakeGitHub()


@pytest.fixture
def app(github):
    return App("123", KEY_B64, http=github.client())


def test_app_authenticates_with_a_jwt_it_signs(app, github):
    app.installation_id()
    token = github.requests[0].headers["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(token, KEY.public_key(), algorithms=["RS256"])
    assert claims["iss"] == "123"
    assert claims["exp"] - claims["iat"] <= 600


def test_tokens_are_limited_to_the_repository(app, github):
    app.mint(READ_WRITE)
    assert github.mint_bodies() == [{"repositories": ["freepod"], "permissions": READ_WRITE}]


def test_a_dry_run_session_mints_read_only(app, github, tmp_path):
    TokenFile(app, tmp_path / "token", READ_ONLY).refresh()
    permissions = github.mint_bodies()[0]["permissions"]
    assert set(permissions.values()) == {"read"}


def test_token_file_is_replaced_before_it_expires(app, github, tmp_path):
    clock = [datetime.now(UTC)]
    minted = []
    tokens = TokenFile(app, tmp_path / "token", READ_WRITE, on_mint=minted.append,
                       clock=lambda: clock[0])
    tokens.refresh()
    assert (tmp_path / "token").read_text() == "ghs_minted1"
    clock[0] += timedelta(minutes=45)
    tokens.refresh()
    assert github.minted == 1
    clock[0] += timedelta(minutes=6)
    tokens.refresh()
    assert (tmp_path / "token").read_text() == "ghs_minted2"
    assert minted == ["ghs_minted1", "ghs_minted2"]
    assert (tmp_path / "token").stat().st_mode & 0o077 == 0
    tokens.remove()
    assert not (tmp_path / "token").exists()


def test_identity_is_the_bot_user(app):
    assert app.identity() == (
        "freepod-upgrader[bot]",
        "4242+freepod-upgrader[bot]@users.noreply.github.com",
    )


@pytest.mark.parametrize("value", ["not base64!", base64.b64encode(b"just text").decode(), ""])
def test_a_key_that_is_not_base64_pem_is_named(value):
    with pytest.raises(ValueError, match="GITHUB_APP_PRIVATE_KEY"):
        load_private_key(value)


URL = "https://github.com/erikvanzijst/freepod/pull/{}"


def test_dashboard_reads_pull_requests_read_only(app, github):
    github.pulls[5] = {"state": "open", "draft": False, "merged": False}
    assert PullRequests(app).state(URL.format(5)) == "open"
    assert github.mint_bodies()[0]["permissions"] == PULL_REQUESTS_READ


@pytest.mark.parametrize(
    "pull, state",
    [
        ({"state": "closed", "draft": False, "merged": True}, "merged"),
        ({"state": "closed", "draft": False, "merged": False}, "closed"),
        ({"state": "open", "draft": True, "merged": False}, "draft"),
        ({"state": "open", "draft": False, "merged": False}, "open"),
    ],
)
def test_pr_states(app, github, pull, state):
    github.pulls[7] = pull
    assert PullRequests(app).state(URL.format(7)) == state


def test_a_state_is_reused_for_five_minutes(app, github):
    github.pulls[8] = {"state": "open", "draft": False, "merged": False}
    clock = [1000.0]
    prs = PullRequests(app, clock=lambda: clock[0])
    assert prs.state(URL.format(8)) == "open"
    github.pulls[8] = {"state": "closed", "draft": False, "merged": True}
    clock[0] += 299
    assert prs.state(URL.format(8)) == "open"
    clock[0] += 2
    assert prs.state(URL.format(8)) == "merged"


def test_unreachable_github_is_unknown(app, github):
    prs = PullRequests(app)
    github.down = True
    assert prs.state(URL.format(9)) == "unknown"
