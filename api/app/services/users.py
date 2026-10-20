from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.config import get_settings
from app.models import (
    HandleRead,
    TosAcceptanceRead,
    UserRead,
    UserORM,
    UserCreate,
)
from app.services.errors import (
    IntegrityException,
    NotFoundException,
    ValidationException,
)
from app.services.hostnames import HANDLE_MAX_LENGTH, HANDLE_MIN_LENGTH, HANDLE_RE


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


class HandleRefused(ValidationException):
    """A candidate this platform will not store, with a stable `code`."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class HandleConflict(IntegrityException):
    """A candidate that collides with what is already held, with a stable `code`."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _handle_taken() -> HandleConflict:
    return HandleConflict("handle_taken", "That handle is already held by another account")


def handle_suffix(handle: str | None) -> str | None:
    """The text that follows an application label in the hostnames of an
    account holding *handle*, or None when it holds none."""
    return f"-{handle}.{get_settings().tenant_domain}" if handle else None


def get_handle(user: UserORM) -> HandleRead:
    """Return the handle the user holds. Always readable; `handle` and `suffix`
    are null when they have not claimed one."""
    return HandleRead(
        handle=user.handle,
        suffix=handle_suffix(user.handle),
        domain=get_settings().tenant_domain,
    )


def _check_handle(session: Session, candidate: str) -> None:
    if not HANDLE_RE.match(candidate):
        raise HandleRefused(
            "handle_invalid",
            f"A handle is {HANDLE_MIN_LENGTH}-{HANDLE_MAX_LENGTH} lowercase letters "
            f"and digits only",
        )
    if candidate in get_settings().reserved_handles:
        raise HandleRefused("handle_reserved", "That handle is reserved by the platform")
    # Deliberately unfiltered by `deleted_at`: a deleted account keeps its
    # handle rather than releasing it back into circulation.
    held = session.exec(select(UserORM.id).where(func.lower(UserORM.handle) == candidate)).first()
    if held is not None:
        raise _handle_taken()


def claim_handle(
    session: Session, *, user: UserORM, handle: str, dry_run: bool = False
) -> HandleRead:
    """Claim the current user's handle. Accepted only for an account holding
    none, and never reversible.

    Re-claiming the handle already held succeeds and writes nothing. With
    *dry_run*, every check runs and the response is the one a real claim would
    get, but nothing is stored.
    """
    candidate = handle.strip().lower()
    if user.handle is not None:
        if candidate == user.handle:
            return get_handle(user)
        raise HandleConflict(
            "handle_already_claimed",
            f"This account already holds the handle {user.handle!r}, and a handle "
            f"cannot be changed or released",
        )

    _check_handle(session, candidate)
    if dry_run:
        return HandleRead(
            handle=candidate,
            suffix=handle_suffix(candidate),
            domain=get_settings().tenant_domain,
        )

    user.handle = candidate
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        # Two accounts were told the same handle was free and both submitted.
        # The unique index decides; this is the loser.
        session.rollback()
        raise _handle_taken() from exc
    session.refresh(user)
    return get_handle(user)


def delete_user(session: Session, *, user_id: int) -> UserRead:
    user = session.exec(select(UserORM).where(UserORM.id == user_id, UserORM.deleted_at == None)).one_or_none()
    if not user:
        raise NotFoundException("User not found")
    user.deleted_at = user.created_at
    session.add(user)
    session.commit()
    session.refresh(user)
    return UserRead.model_validate(user)
