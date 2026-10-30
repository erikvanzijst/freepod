"""Who may sign in to a deployment: its effective `auth` settings and, for a
`listed` deployment, its access list (app-access-list).

The API owns the list. app-auth reads it to admit people and ties each entry to
the subject that first signs in with it (`daemons/app-auth/access.go`).
Removing a bound entry from an OIDC app signs the person out of it with a
back-channel logout token, in the same request (D8).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Iterable
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import get_settings
from app.models import (
    AccessEntryRead,
    AccessListRead,
    AppAccessEntryORM,
    AppAccessInvitationORM,
    DeploymentAuthRead,
    DeploymentORM,
    ProductTemplateVersionORM,
)
from app.models.core import _utcnow
from app.services import app_auth_oidc, mailer, template_values
from app.services.errors import (
    ConflictException,
    NotFoundException,
    RateLimitedException,
    UpstreamException,
)

logger = logging.getLogger(__name__)

ACCESS_LIST_LIMIT = 500
INVITATION_WINDOW = timedelta(hours=24)
INVITATION_RETENTION = timedelta(days=7)
LOGOUT_TOKEN_TTL_SEC = 120
LOGOUT_TIMEOUT_SEC = 10
BACKCHANNEL_LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"

# Deliberately loose on the local part, which only the address's own domain
# interprets, and strict on the domain, which mail is routed by.
_EMAIL = re.compile(
    r"^[^@\s\x00-\x1f\x7f]+@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool
    protocol: str
    access: str

    @property
    def listed(self) -> bool:
        return self.enabled and self.access == "listed"

    @property
    def oidc(self) -> bool:
        return self.enabled and self.protocol == "oidc"


def auth_settings(system_values: dict[str, Any] | None, user_values: dict[str, Any] | None) -> AuthSettings:
    """The effective `auth` settings, as the chart and app-auth read them (D2).

    A user value overrides the template's, and the contract's defaults fill
    the rest. An unknown protocol is no Sign in with Freepod at all; an unknown
    access is `listed`, which fails closed.
    """
    auth = template_values.merge_values_scoped(system_values, user_values, None).get("auth")
    if not isinstance(auth, dict):
        auth = {}
    protocol = auth.get("protocol")
    protocol = "header" if protocol is None else protocol
    access = "anyone" if auth.get("access") in (None, "anyone") else "listed"
    enabled = auth.get("enabled") is True and protocol in ("header", "oidc")
    return AuthSettings(enabled=enabled, protocol=str(protocol), access=access)


def _serving(
    session: Session, deployment: DeploymentORM
) -> tuple[AuthSettings, ProductTemplateVersionORM] | None:
    release = deployment.applied_release
    if release is None:
        return None
    template = session.get(ProductTemplateVersionORM, release.template_id)
    return auth_settings(template.system_values_json, release.values_json), template


def auth_summaries(session: Session, deployments: Iterable[DeploymentORM]) -> dict[UUID, DeploymentAuthRead]:
    """Each deployment's `auth` read model, in two statements whatever their number."""
    deployments = list(deployments)
    template_ids = {d.applied_release.template_id for d in deployments if d.applied_release is not None}
    if template_ids:
        session.exec(select(ProductTemplateVersionORM).where(ProductTemplateVersionORM.id.in_(template_ids))).all()
    serving = {d.id: s[0] for d in deployments if (s := _serving(session, d)) is not None}
    listed = [deployment_id for deployment_id, s in serving.items() if s.listed]
    counts: dict[UUID, int] = {}
    if listed:
        counts = dict(
            session.exec(
                select(AppAccessEntryORM.deployment_id, func.count())
                .where(AppAccessEntryORM.deployment_id.in_(listed))
                .group_by(AppAccessEntryORM.deployment_id)
            ).all()
        )
    return {
        deployment_id: DeploymentAuthRead(
            enabled=s.enabled,
            protocol=s.protocol,
            access=s.access,
            listed_count=counts.get(deployment_id, 0) if s.listed else None,
        )
        for deployment_id, s in serving.items()
    }


def _entry_read(entry: AppAccessEntryORM) -> AccessEntryRead:
    return AccessEntryRead(
        id=entry.id, email=entry.email, name=entry.name, created_at=entry.created_at, bound_at=entry.bound_at
    )


def read_access(session: Session, deployment: DeploymentORM) -> AccessListRead:
    serving = _serving(session, deployment)
    settings = serving[0] if serving else AuthSettings(enabled=False, protocol="header", access="anyone")
    entries = session.exec(
        select(AppAccessEntryORM)
        .where(AppAccessEntryORM.deployment_id == deployment.id)
        .order_by(AppAccessEntryORM.created_at, AppAccessEntryORM.email)
    ).all()
    return AccessListRead(
        enabled=settings.enabled,
        protocol=settings.protocol,
        access=settings.access,
        owner_email=deployment.user.email,
        limit=ACCESS_LIST_LIMIT,
        entries=[_entry_read(e) for e in entries],
    )


def normalize_email(email: str) -> str | None:
    email = email.strip().lower()
    return email if len(email) <= 254 and _EMAIL.match(email) else None


@dataclass(frozen=True)
class Invitation:
    to: str
    owner_email: str
    hostname: str


def add_entry(session: Session, deployment: DeploymentORM, email: str) -> tuple[AccessEntryRead, Invitation]:
    """Add someone to a `listed` deployment's list and record their invitation.

    The deployment row is locked for the transaction, so concurrent additions
    cannot pass the bound together (D5). The caller sends the invitation once
    this has committed (D6). `email` is already normalized.
    """
    session.exec(select(DeploymentORM.id).where(DeploymentORM.id == deployment.id).with_for_update()).one()
    serving = _serving(session, deployment)
    if serving is None or not serving[0].listed:
        raise ConflictException(
            "This deployment's access list does not apply: its serving release does not have "
            "auth.enabled with auth.access: listed",
            code="access_not_listed",
        )
    owner_email = deployment.user.email
    existing = session.exec(
        select(AppAccessEntryORM.id).where(
            AppAccessEntryORM.deployment_id == deployment.id, AppAccessEntryORM.email == email
        )
    ).first()
    if existing is not None or email == owner_email.lower():
        raise ConflictException(f"{email} can already sign in", code="access_duplicate")
    count = session.exec(
        select(func.count()).select_from(AppAccessEntryORM).where(AppAccessEntryORM.deployment_id == deployment.id)
    ).one()
    if count >= ACCESS_LIST_LIMIT:
        raise ConflictException(
            f"The access list is full: it holds {ACCESS_LIST_LIMIT} people", code="access_list_full"
        )
    _check_invitation_limit(session, deployment.user_id)

    entry = AppAccessEntryORM(deployment_id=deployment.id, email=email)
    session.add(entry)
    session.add(AppAccessInvitationORM(user_id=deployment.user_id))
    session.commit()
    session.refresh(entry)
    return _entry_read(entry), Invitation(to=email, owner_email=owner_email, hostname=deployment.hostname or "")


def _check_invitation_limit(session: Session, user_id: int) -> None:
    limit = get_settings().access_invitations_per_day
    since = _utcnow() - INVITATION_WINDOW
    sent = session.exec(
        select(AppAccessInvitationORM.sent_at)
        .where(AppAccessInvitationORM.user_id == user_id, AppAccessInvitationORM.sent_at > since)
        .order_by(AppAccessInvitationORM.sent_at)
    ).all()
    if len(sent) >= limit:
        until = sent[len(sent) - limit] + INVITATION_WINDOW
        raise RateLimitedException(
            f"You have sent {limit} invitations in the past 24 hours. "
            f"You can invite more people after {until.strftime('%Y-%m-%d %H:%M')} UTC.",
            code="access_invitation_limit",
        )


def invitation_text(invitation: Invitation) -> tuple[str, str]:
    """The fixed invitation, which carries nothing the owner wrote (D6)."""
    url = f"https://{invitation.hostname}"
    subject = f"You have been given access to {invitation.hostname}"
    body = (
        f"{invitation.owner_email} gave you access to the app at {url}.\n"
        "\n"
        f"To use it, sign in there with a Freepod account that uses this email address,\n"
        f"{invitation.to}. If you do not have a Freepod account yet, you can create one\n"
        "when you sign in.\n"
    )
    return subject, body


def send_invitation(invitation: Invitation) -> None:
    subject, body = invitation_text(invitation)
    mailer.send_email(to=invitation.to, subject=subject, body=body)


def sweep_invitations(session: Session) -> int:
    """Forget invitations older than the window any limit can still count them in."""
    stale = session.exec(
        select(AppAccessInvitationORM).where(AppAccessInvitationORM.sent_at < _utcnow() - INVITATION_RETENTION)
    ).all()
    for invitation in stale:
        session.delete(invitation)
    session.commit()
    return len(stale)


def remove_entry(session: Session, deployment: DeploymentORM, entry_id: UUID) -> None:
    """Remove an entry, first signing its person out of an OIDC app (D8).

    The entry stays when the app does not accept the logout token. The entry
    row is locked meanwhile, so two removals of it send one token.
    """
    entry = session.exec(
        select(AppAccessEntryORM)
        .where(AppAccessEntryORM.id == entry_id, AppAccessEntryORM.deployment_id == deployment.id)
        .with_for_update()
    ).first()
    if entry is None:
        raise NotFoundException("No such entry on this deployment's access list")
    serving = _serving(session, deployment)
    if entry.subject and serving is not None and serving[0].oidc:
        uri = logout_uri(deployment.hostname, _logout_path(serving[1]))
        if uri is not None:
            _send_logout(deployment, entry.subject, uri)
    session.delete(entry)
    session.commit()


def _logout_path(template: ProductTemplateVersionORM) -> Any:
    oidc = ((template.system_values_json or {}).get("auth") or {}).get("oidc")
    return oidc.get("backchannelLogoutPath") if isinstance(oidc, dict) else None


def logout_uri(hostname: str | None, path: Any) -> str | None:
    """`https://<hostname><path>`, or None when the path would leave the host.

    The callback-path rules of `daemons/app-auth/client.go` (redirectURIFor),
    which a template's logout path follows too.
    """
    if not hostname or not isinstance(path, str):
        return None
    hostname = hostname.lower()
    if not path.startswith("/") or path.startswith("//") or any(c in path for c in "?#\\"):
        return None
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in path):
        return None
    uri = f"https://{hostname}{path}"
    try:
        parts = urlsplit(uri)
        port = parts.port
    except ValueError:
        return None
    if parts.username is not None or parts.password is not None or port is not None or parts.netloc != hostname:
        return None
    return uri


def _signing_key() -> tuple[RSAPrivateKey, str]:
    pems = re.findall(
        r"-----BEGIN (?:RSA )?PRIVATE KEY-----.+?-----END (?:RSA )?PRIVATE KEY-----",
        get_settings().app_auth_oidc_signing_keys,
        re.DOTALL,
    )
    if not pems:
        raise UpstreamException(
            "This environment cannot sign people out of apps: no OIDC signing key is configured",
            code="access_logout_unavailable",
        )
    key = load_pem_private_key(pems[0].encode(), password=None)
    if not isinstance(key, RSAPrivateKey):
        raise ValueError("the OIDC signing key is not an RSA key")
    return key, key_id(key)


def key_id(key: RSAPrivateKey) -> str:
    """The key's RFC 7638 thumbprint, which app-auth names it by in its JWKS."""
    numbers = key.public_key().public_numbers()

    def b64(n: int) -> str:
        return base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()

    canonical = json.dumps({"e": b64(numbers.e), "kty": "RSA", "n": b64(numbers.n)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).rstrip(b"=").decode()


def logout_token(deployment_id: UUID, subject: str, *, now: float | None = None) -> str:
    """A back-channel logout token for subject, as app-auth's provider would sign it (D9)."""
    key, kid = _signing_key()
    iat = int(time.time() if now is None else now)
    claims = {
        "iss": get_settings().app_auth_oidc_issuer.strip(),
        "aud": app_auth_oidc.client_id(deployment_id),
        "iat": iat,
        "exp": iat + LOGOUT_TOKEN_TTL_SEC,
        "jti": secrets.token_urlsafe(16),
        "sub": subject,
        "events": {BACKCHANNEL_LOGOUT_EVENT: {}},
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"typ": "logout+jwt", "kid": kid})


def _send_logout(deployment: DeploymentORM, subject: str, uri: str) -> None:
    token = logout_token(deployment.id, subject)
    app = deployment.hostname
    try:
        response = httpx.post(
            uri, data={"logout_token": token}, timeout=LOGOUT_TIMEOUT_SEC, follow_redirects=False
        )
    except httpx.HTTPError as exc:
        logger.warning("Back-channel logout to %s failed: %s", uri, exc)
        raise UpstreamException(
            f"{app} could not be reached to sign this person out. Try again when it is running.",
            code="access_logout_failed",
        ) from exc
    if not response.is_success:
        logger.warning("Back-channel logout to %s answered %s", uri, response.status_code)
        raise UpstreamException(
            f"{app} did not accept signing this person out (it answered {response.status_code}). "
            "Try again when it is running.",
            code="access_logout_failed",
        )
    logger.info("Signed subject out of deployment_id=%s through back-channel logout", deployment.id)

