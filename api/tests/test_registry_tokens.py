from __future__ import annotations

import base64
import json

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from typer.testing import CliRunner

from app.cli import app
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


def test_a_key_on_another_curve_is_refused():
    other = registry_tokens.private_key_pem(ec.generate_private_key(ec.SECP384R1()))
    with pytest.raises(RegistryKeyException, match="P-256"):
        registry_tokens.load_private_key(other)
