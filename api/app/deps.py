from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Path, Request, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.config import get_settings
from app.db import get_session
from app.models import UserORM
from app.services import admin_notices
from app.services.mollie import MolliePaymentProvider, PaymentProvider


def _live_user(session: Session, *where) -> UserORM | None:
    return session.exec(
        select(UserORM).where(*where, UserORM.deleted_at.is_(None))  # type: ignore[union-attr]
    ).one_or_none()


def _address_taken() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="This email address is held by another Freepod account. Contact support to resolve it.",
    )


def _resolve_user(session: Session, email: str, subject: str | None, ip: str | None) -> UserORM:
    """The ladder of caller-identity-resolution: the record bound to the
    subject, then an unbound record holding the email (adopted), then a new
    record. A bound record is never reached by email, and no write may leave
    two live records holding one address (design D3, D7)."""
    if subject:
        user = _live_user(session, UserORM.keycloak_subject == subject)
        if user is not None:
            if user.email.lower() != email:
                if _live_user(session, func.lower(UserORM.email) == email) is not None:
                    raise _address_taken()
                user.email = email
                session.commit()
            return user

    user = _live_user(session, func.lower(UserORM.email) == email)
    if user is not None:
        if subject is None:
            return user
        if user.keycloak_subject is not None:
            raise _address_taken()
        user.keycloak_subject = subject
        session.commit()
        return user

    user = UserORM(email=email, keycloak_subject=subject)
    session.add(user)
    session.flush()
    admin_notices.account_created(session, user, ip=ip)
    session.commit()
    session.refresh(user)
    return user


def get_current_user(
    request: Request,
    x_auth_request_email: str | None = Header(None),
    x_auth_request_user: str | None = Header(None),
    session: Session = Depends(get_session),
) -> UserORM:
    """The caller's user record, resolved by the Keycloak subject the edge
    sends as ``X-Auth-Request-User``. A request without one (local
    development, tests) resolves by email alone and binds nothing."""
    if not x_auth_request_email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not authenticated")

    email = x_auth_request_email.strip().lower()
    subject = (x_auth_request_user or "").strip() or None
    ip = request.client.host if request.client else None
    try:
        return _resolve_user(session, email, subject, ip)
    except IntegrityError:
        # A concurrent first request created or bound the same record.
        session.rollback()
        return _resolve_user(session, email, subject, ip)


def get_optional_user(
    request: Request,
    x_auth_request_email: str | None = Header(None),
    x_auth_request_user: str | None = Header(None),
    session: Session = Depends(get_session),
) -> UserORM | None:
    """The caller when the request carries an identity, else None.

    ``get_current_user`` 404s an anonymous request; endpoints that are public
    but shaped by who is asking need it to be None instead.
    """
    if not x_auth_request_email:
        return None
    return get_current_user(request, x_auth_request_email, x_auth_request_user, session)


def require_admin(
    current_user: UserORM = Depends(get_current_user),
) -> UserORM:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return current_user


def require_self(
    user_id: int = Path(..., description="ID of the user whose resources are being accessed."),
    current_user: UserORM = Depends(get_current_user),
) -> UserORM:
    if current_user.id != user_id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return current_user


def get_payment_provider() -> PaymentProvider | None:
    """Return a MolliePaymentProvider when configured, None otherwise.

    When None, all plans are treated as free regardless of price_cents.
    """
    settings = get_settings()
    if settings.mollie_api_key:
        return MolliePaymentProvider(api_key=settings.mollie_api_key)
    return None
