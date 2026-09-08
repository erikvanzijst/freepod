from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.config import get_settings
from app.models import (
    SubdomainRead,
    TosAcceptanceRead,
    UserRead,
    UserORM,
    UserCreate,
)
from app.services.errors import (
    HostnameException,
    IntegrityException,
    NotFoundException,
    ValidationException,
)
from app.services.hostnames import (
    SUBDOMAIN_MAX_LENGTH,
    SUBDOMAIN_MIN_LENGTH,
    require_valid_subdomain,
)


def create_user(session: Session, payload: UserCreate) -> UserRead:
    user = UserORM.model_validate(payload)
    session.add(user)
    try:
        session.commit()
        session.refresh(user)
        return UserRead.model_validate(user)
    except IntegrityError as exc:
        raise IntegrityException(f"Email already in use: {user.email}") from exc


def list_users(session: Session) -> list[UserRead]:
    return list(session.exec(select(UserORM).where(UserORM.deleted_at == None)).all())


def get_user(session: Session, *, user_id: int) -> UserRead:
    user = session.exec(select(UserORM).where(UserORM.id == user_id, UserORM.deleted_at == None)).one_or_none()
    if not user:
        raise NotFoundException("User not found")
    return UserRead.model_validate(user)


def get_tos_acceptance(user: UserORM) -> TosAcceptanceRead:
    """Return the user's ToS acceptance status. Always readable; `version` is
    null when the user has not yet accepted.

    `current_version` reports the version the platform currently requires, read
    from settings the same way :func:`record_tos_acceptance` validates against
    it. It is always set and is unrelated to what the user accepted: a user who
    accepted an older version sees the two differ.
    """
    return TosAcceptanceRead(
        version=user.tos_accepted_version,
        accepted_at=user.tos_accepted_at,
        current_version=get_settings().current_tos_version,
    )


def record_tos_acceptance(session: Session, *, user: UserORM, version: str) -> TosAcceptanceRead:
    """Record the current user's acceptance of the Terms of Service.

    The submitted version MUST equal the current ToS version; a mismatch is a
    409 (the terms changed under the user). Recording is idempotent for the
    current version — re-accepting simply re-stamps the acceptance time.
    """
    if version != get_settings().current_tos_version:
        raise IntegrityException(
            "Terms of Service have changed; please re-review and accept the current version"
        )
    user.tos_accepted_version = version
    user.tos_accepted_at = datetime.now(UTC)
    session.add(user)
    session.commit()
    session.refresh(user)
    return get_tos_acceptance(user)


class SubdomainRefused(ValidationException):
    """A candidate this platform will not store, with a stable `code`."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class SubdomainConflict(IntegrityException):
    """A candidate that collides with what is already held, with a stable `code`."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


_CLAIM_REFUSALS = {
    "invalid": (
        SubdomainRefused,
        "subdomain_invalid",
        f"A subdomain is a single DNS label of {SUBDOMAIN_MIN_LENGTH}-"
        f"{SUBDOMAIN_MAX_LENGTH} characters: lowercase letters, digits and "
        f"hyphens, starting and ending with a letter or digit",
    ),
    "reserved": (
        SubdomainRefused,
        "subdomain_reserved",
        "That subdomain is reserved by the platform",
    ),
    "claimed": (
        SubdomainConflict,
        "subdomain_taken",
        "That subdomain is already held by another account",
    ),
}


def get_subdomain(user: UserORM) -> SubdomainRead:
    """Return the subdomain the user holds. Always readable; both fields are
    null when they have not claimed one.

    The fully qualified name is built from `settings.domain` rather than from
    the wildcard domain list, because that is the name the reconciler provisions
    a DNS record and a wildcard certificate for.
    """
    domain = get_settings().domain
    fqdn = f"{user.subdomain}.{domain}" if user.subdomain and domain else None
    return SubdomainRead(subdomain=user.subdomain, fqdn=fqdn)


def claim_subdomain(session: Session, *, user: UserORM, subdomain: str) -> SubdomainRead:
    """Claim the current user's subdomain. Accepted only for an account holding
    none, and never reversible.

    Not idempotent: an account that already holds one is refused even when it
    submits the label it holds, because a repeated claim is far more likely to
    be a client that lost track of its state than a user who meant it (D4).
    """
    if user.subdomain is not None:
        raise SubdomainConflict(
            "subdomain_already_claimed",
            f"This account already holds the subdomain {user.subdomain!r}, and a "
            f"subdomain cannot be changed or released",
        )

    candidate = subdomain.strip().lower()
    try:
        require_valid_subdomain(session, candidate)
    except HostnameException as exc:
        klass, code, message = _CLAIM_REFUSALS[exc.reason]
        raise klass(code, message) from exc

    user.subdomain = candidate
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        # Two accounts were told the same label was free and both submitted.
        # The unique index decides; this is the loser.
        session.rollback()
        klass, code, message = _CLAIM_REFUSALS["claimed"]
        raise klass(code, message) from exc
    session.refresh(user)
    return get_subdomain(user)


def delete_user(session: Session, *, user_id: int) -> UserRead:
    user = session.exec(select(UserORM).where(UserORM.id == user_id, UserORM.deleted_at == None)).one_or_none()
    if not user:
        raise NotFoundException("User not found")
    user.deleted_at = user.created_at
    session.add(user)
    session.commit()
    session.refresh(user)
    return UserRead.model_validate(user)
