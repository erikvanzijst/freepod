"""Signing keys, tokens and pull credentials for the tenant registry.

A key is identified by its RFC 7638 thumbprint -- the same identifier the
registry assigns keys it trusts from a certificate bundle -- so the ``kid`` a
token carries is derived from the key that signed it and cannot drift from the
JWKS the registry was given. Rationale: authenticated-tenant-registry D6, D14.

A pull credential is derived rather than stored (D11): the password for
``pull-{uid}`` is an HMAC over the uid and a version marker, so verifying one
is a recomputation, and changing the marker rotates every credential.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlmodel import Session

from app.config import CaelusSettings
from app.models import UserORM
from app.services.errors import CaelusException, ValidationException

ALGORITHM = "ES256"
_COORDINATE_BYTES = 32

PULL_CREDENTIAL_VERSION = "v1"
PULL_TOKEN_TTL_SECONDS = 300
OPERATOR_TOKEN_MAX_TTL_SECONDS = 3600
_NOT_BEFORE_SKEW_SECONDS = 60
_PULL_USERNAME = re.compile(r"pull-([1-9][0-9]*)")

# Distribution's repository name grammar: lowercase path components joined by
# `/`. Anything else -- a wildcard in particular -- is not an exact name.
_REPOSITORY_COMPONENT = r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
_REPOSITORY_NAME = re.compile(rf"{_REPOSITORY_COMPONENT}(?:/{_REPOSITORY_COMPONENT})*")


class RegistryKeyException(CaelusException):
    """Registry token issuance is not configured, or its signing key is unusable."""


class RegistryCredentialException(CaelusException):
    """A pull credential proved nothing, so no token is issued for it."""


class RegistryServiceException(ValidationException):
    code = "unknown_service"


class RegistryGrantException(ValidationException):
    code = "unsupported_grant_type"


@dataclass(frozen=True)
class IssuedToken:
    token: str
    access: list[dict[str, Any]]
    issued_at: int
    expires_in: int

    @property
    def issued_at_rfc3339(self) -> str:
        return datetime.fromtimestamp(self.issued_at, UTC).isoformat().replace("+00:00", "Z")

    @property
    def scope(self) -> str:
        return " ".join(
            f"{entry['type']}:{entry['name']}:{','.join(entry['actions'])}"
            for entry in self.access
        )


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


def mint(
    private_key: ec.EllipticCurvePrivateKey,
    *,
    issuer: str,
    audience: str,
    subject: str,
    access: list[dict[str, Any]],
    ttl_seconds: int,
    now: int | None = None,
) -> IssuedToken:
    issued_at = int(time.time()) if now is None else now
    claims = {
        "iss": issuer,
        "sub": subject,
        "aud": audience,
        "iat": issued_at,
        "nbf": issued_at - _NOT_BEFORE_SKEW_SECONDS,
        "exp": issued_at + ttl_seconds,
        "jti": uuid.uuid4().hex,
        "access": access,
    }
    return IssuedToken(sign(private_key, claims), access, issued_at, ttl_seconds)


def image_repository(user_id: int) -> str:
    return f"u/{user_id}"


def pull_username(user_id: int) -> str:
    return f"pull-{user_id}"


def pull_password(hmac_key: str, user_id: int, *, version: str = PULL_CREDENTIAL_VERSION) -> str:
    message = f"registry-pull:{version}:{user_id}".encode()
    return hmac.new(hmac_key.encode(), message, hashlib.sha256).hexdigest()


def _verified_owner(session: Session, hmac_key: str, username: str, password: str) -> int:
    match = _PULL_USERNAME.fullmatch(username)
    if match is None:
        raise RegistryCredentialException("unknown registry credential")
    user_id = int(match.group(1))
    if not hmac.compare_digest(pull_password(hmac_key, user_id).encode(), password.encode()):
        raise RegistryCredentialException("unknown registry credential")
    user = session.get(UserORM, user_id)
    if user is None or user.deleted_at is not None:
        raise RegistryCredentialException("unknown registry credential")
    return user_id


def _requested(scopes: Iterable[str]) -> Iterable[tuple[str, str, set[str]]]:
    for value in scopes:
        for scope in value.split():
            resource_type, _, rest = scope.partition(":")
            name, _, actions = rest.rpartition(":")
            if resource_type and name and actions:
                yield resource_type, name, set(actions.split(","))


def pull_access(user_id: int, scopes: Iterable[str]) -> list[dict[str, Any]]:
    """The requested scope narrowed to what a pull credential can hold: pull on
    its owner's image repository, and nothing else, whatever was asked."""
    own = image_repository(user_id)
    for resource_type, name, actions in _requested(scopes):
        if resource_type == "repository" and name == own and actions & {"pull", "*"}:
            return [{"type": "repository", "name": own, "actions": ["pull"]}]
    return []


def signer(settings: CaelusSettings) -> ec.EllipticCurvePrivateKey:
    if not (settings.registry_host and settings.registry_token_issuer):
        raise RegistryKeyException("registry token issuance is not configured")
    return load_private_key(settings.registry_signing_private_key)


def issue_pull_token(
    session: Session,
    settings: CaelusSettings,
    *,
    service: str,
    username: str,
    password: str,
    scopes: Iterable[str],
) -> IssuedToken:
    if not settings.registry_pull_hmac_key:
        raise RegistryKeyException("registry token issuance is not configured")
    key = signer(settings)
    if service != settings.registry_host:
        raise RegistryServiceException(f"tokens are issued only for {settings.registry_host}")
    user_id = _verified_owner(session, settings.registry_pull_hmac_key, username, password)
    return mint(
        key,
        issuer=settings.registry_token_issuer,
        audience=settings.registry_host,
        subject=pull_username(user_id),
        access=pull_access(user_id, scopes),
        ttl_seconds=PULL_TOKEN_TTL_SECONDS,
    )


def operator_token(
    settings: CaelusSettings,
    *,
    push: Iterable[str],
    pull: Iterable[str],
    ttl_seconds: int,
) -> IssuedToken:
    """A short-lived token for exactly the repositories an operator names.

    For seeding the registry from inside the cluster, where nothing else may
    write: the mirrored base images and migrated tenant images (D19). Exact
    names only, never delete, never the catalog.
    """
    push, pull = list(dict.fromkeys(push)), list(dict.fromkeys(pull))
    if not push and not pull:
        raise ValidationException("name at least one repository")
    for name in [*push, *pull]:
        if not _REPOSITORY_NAME.fullmatch(name):
            raise ValidationException(f"not an exact repository name: {name!r}")
    if not 0 < ttl_seconds <= OPERATOR_TOKEN_MAX_TTL_SECONDS:
        raise ValidationException(
            f"a token may live at most {OPERATOR_TOKEN_MAX_TTL_SECONDS} seconds"
        )
    access = [{"type": "repository", "name": n, "actions": ["pull", "push"]} for n in push]
    access += [
        {"type": "repository", "name": n, "actions": ["pull"]} for n in pull if n not in push
    ]
    return mint(
        signer(settings),
        issuer=settings.registry_token_issuer,
        audience=settings.registry_host,
        subject="operator",
        access=access,
        ttl_seconds=ttl_seconds,
    )
