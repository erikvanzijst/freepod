from __future__ import annotations

import base64
import json

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from typer.testing import CliRunner

from app.cli import app
from app.config import CaelusSettings
from app.services import registry_tokens
from app.services.registry_tokens import RegistryKeyException

PEM_END = "-----END PRIVATE KEY-----"


def _keygen() -> tuple[str, dict]:
    result = CliRunner().invoke(app, ["registry-keygen"])
    assert result.exit_code == 0, result.output
    pem, sep, rest = result.stdout.partition(PEM_END)
    assert sep, result.stdout
    return pem + PEM_END + "\n", json.loads(rest)


def _sign_probe(pem: str) -> str:
    return registry_tokens.sign(registry_tokens.load_private_key(pem), {"sub": "probe"})


def test_keygen_jwks_names_the_kid_the_signer_puts_in_the_header():
    pem, printed = _keygen()
    [jwk] = printed["keys"]
    assert jwt.get_unverified_header(_sign_probe(pem))["kid"] == jwk["kid"]


def test_a_signed_token_verifies_against_the_printed_jwks():
    pem, printed = _keygen()
    token = _sign_probe(pem)
    key = jwt.PyJWKSet.from_dict(printed)[jwt.get_unverified_header(token)["kid"]]
    assert jwt.decode(token, key, algorithms=["ES256"])["sub"] == "probe"


def test_each_run_generates_a_distinct_key():
    _, first = _keygen()
    _, second = _keygen()
    assert first["keys"][0]["kid"] != second["keys"][0]["kid"]


def test_coordinates_keep_their_full_width():
    key = next(
        k
        for k in (ec.generate_private_key(ec.SECP256R1()) for _ in range(10_000))
        if k.public_key().public_numbers().x < 1 << 248
    )
    jwk = registry_tokens.public_jwk(key.public_key())
    assert len(base64.urlsafe_b64decode(jwk["x"] + "=")) == 32


def test_an_absent_key_is_refused():
    with pytest.raises(RegistryKeyException, match="no registry signing key"):
        registry_tokens.load_private_key("")


def _operator_settings(monkeypatch, key) -> None:
    settings = CaelusSettings(
        _env_file=None,
        registry_host="cr.test.example",
        registry_token_issuer="caelus-test",
        registry_signing_private_key=registry_tokens.private_key_pem(key),
    )
    monkeypatch.setattr("app.cli.get_settings", lambda: settings)


def test_an_operator_token_grants_exactly_what_it_names(monkeypatch):
    key = registry_tokens.generate_private_key()
    _operator_settings(monkeypatch, key)
    result = CliRunner().invoke(
        app,
        ["registry-token", "--push", "railwayapp/railpack-builder", "--push", "docker/dockerfile",
         "--pull", "u/7"],
    )
    assert result.exit_code == 0, result.output
    claims = jwt.decode(
        result.stdout.strip(), key.public_key(), algorithms=["ES256"],
        audience="cr.test.example", issuer="caelus-test",
    )
    assert claims["access"] == [
        {"type": "repository", "name": "railwayapp/railpack-builder", "actions": ["pull", "push"]},
        {"type": "repository", "name": "docker/dockerfile", "actions": ["pull", "push"]},
        {"type": "repository", "name": "u/7", "actions": ["pull"]},
    ]
    assert claims["sub"] == "operator"
    assert claims["exp"] - claims["iat"] == 900


@pytest.mark.parametrize("name", ["*", "railwayapp/*", "u/", "Upper/case", "a//b", ""])
def test_an_operator_token_refuses_anything_but_an_exact_name(monkeypatch, name):
    _operator_settings(monkeypatch, registry_tokens.generate_private_key())
    result = CliRunner().invoke(app, ["registry-token", "--push", name])
    assert result.exit_code == 1
    assert "exact repository name" in result.output


@pytest.mark.parametrize(
    "args,message",
    [
        ([], "at least one repository"),
        (["--push", "u/7", "--ttl-seconds", "3601"], "at most 3600 seconds"),
        (["--push", "u/7", "--ttl-seconds", "0"], "at most 3600 seconds"),
    ],
)
def test_an_operator_token_is_bounded(monkeypatch, args, message):
    _operator_settings(monkeypatch, registry_tokens.generate_private_key())
    result = CliRunner().invoke(app, ["registry-token", *args])
    assert result.exit_code == 1
    assert message in result.output


def test_an_operator_token_needs_a_configured_signer(monkeypatch):
    monkeypatch.setattr("app.cli.get_settings", lambda: CaelusSettings(_env_file=None))
    result = CliRunner().invoke(app, ["registry-token", "--push", "u/7"])
    assert result.exit_code == 1
    assert "not configured" in result.output


def test_a_key_on_another_curve_is_refused():
    other = registry_tokens.private_key_pem(ec.generate_private_key(ec.SECP384R1()))
    with pytest.raises(RegistryKeyException, match="P-256"):
        registry_tokens.load_private_key(other)
