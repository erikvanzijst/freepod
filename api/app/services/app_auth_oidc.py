"""Credentials for deployments that are OIDC clients of app-auth's OpenID Provider.

A client has no record: its ID is the deployment's, and its secret is derived
from that ID with a keyring app-auth shares (`daemons/app-auth/client.go`), so
the two must derive identically. A test on each side pins the same vector. See
the `app-oidc-provider` design doc, D3 and D10.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from uuid import UUID

from app.config import get_settings

CLIENT_SECRET_PREFIX = "app-oidc-client:v1:"


def parse_keyring(spec: str) -> list[bytes]:
    """Read `id:base64key[,id:base64key...]`, current key first, as app-auth does."""
    keys: list[bytes] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        key_id, sep, encoded = part.partition(":")
        if not sep or not key_id or "." in key_id:
            raise ValueError("keyring entry is not id:base64")
        try:
            secret = base64.b64decode(encoded, validate=True)
        except binascii.Error as exc:
            raise ValueError(f"keyring key {key_id!r} is not base64") from exc
        if len(secret) < 32:
            raise ValueError(f"keyring key {key_id!r} is shorter than 32 bytes")
        keys.append(secret)
    if not keys:
        raise ValueError("keyring has no keys")
    return keys


def derive_client_secret(key: bytes, client_id: str) -> str:
    mac = hmac.new(key, (CLIENT_SECRET_PREFIX + client_id).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


def client_id(deployment_id: UUID) -> str:
    """The client ID is the deployment ID as Postgres prints it, which the broker requires."""
    return str(deployment_id)


def oidc_client_secret(deployment_id: UUID) -> str:
    """The deployment's client secret, derived with the first key of the ring."""
    return derive_client_secret(
        parse_keyring(get_settings().app_auth_oidc_client_keys)[0], client_id(deployment_id)
    )

