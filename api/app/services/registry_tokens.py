"""Signing keys and tokens for the tenant registry.

A key is identified by its RFC 7638 thumbprint -- the same identifier the
registry assigns keys it trusts from a certificate bundle -- so the ``kid`` a
token carries is derived from the key that signed it and cannot drift from the
JWKS the registry was given. Rationale: authenticated-tenant-registry D6, D14.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.services.errors import CaelusException

ALGORITHM = "ES256"
_COORDINATE_BYTES = 32


class RegistryKeyException(CaelusException):
    """The registry signing key is missing or unusable."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_private_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def private_key_pem(key: ec.EllipticCurvePrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


def load_private_key(pem: str) -> ec.EllipticCurvePrivateKey:
    if not pem.strip():
        raise RegistryKeyException("no registry signing key is configured")
    try:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
    except ValueError as exc:
        raise RegistryKeyException(f"not a PEM private key: {exc}") from exc
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise RegistryKeyException("the registry signing key must be an EC P-256 key")
    return key


def _required_members(public_key: ec.EllipticCurvePublicKey) -> dict[str, str]:
    # Fixed width: the registry rejects a coordinate shorter than the curve.
    numbers = public_key.public_numbers()
    return {
        "crv": "P-256",
        "kty": "EC",
        "x": _b64url(numbers.x.to_bytes(_COORDINATE_BYTES, "big")),
        "y": _b64url(numbers.y.to_bytes(_COORDINATE_BYTES, "big")),
    }


def key_id(public_key: ec.EllipticCurvePublicKey) -> str:
    canonical = json.dumps(_required_members(public_key), sort_keys=True, separators=(",", ":"))
    return _b64url(hashlib.sha256(canonical.encode()).digest())


def public_jwk(public_key: ec.EllipticCurvePublicKey) -> dict[str, str]:
    return {
        **_required_members(public_key),
        "kid": key_id(public_key),
        "use": "sig",
        "alg": ALGORITHM,
    }


def jwks(*public_keys: ec.EllipticCurvePublicKey) -> dict[str, list[dict[str, str]]]:
    return {"keys": [public_jwk(k) for k in public_keys]}


def sign(private_key: ec.EllipticCurvePrivateKey, claims: dict[str, Any]) -> str:
    return jwt.encode(
        claims,
        private_key,
        algorithm=ALGORITHM,
        headers={"kid": key_id(private_key.public_key())},
    )
