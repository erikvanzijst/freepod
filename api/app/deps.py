from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Path, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.config import get_settings
from app.db import get_session
from app.models import UserORM
from app.services.errors import UserResolutionConflictException
from app.services.mollie import MolliePaymentProvider, PaymentProvider


def _active_user_by_subject(session: Session, subject: str) -> UserORM | None:
    return session.exec(
        select(UserORM).where(
            UserORM.keycloak_subject == subject,
            UserORM.deleted_at.is_(None),  # type: ignore[union-attr]
        )
    ).one_or_none()


def _active_adoptable_user_by_email(session: Session, email: str) -> UserORM | None:
    # A record carrying a subject is never reached by email: once a record is
    # bound to an identity, no other identity may reach it by presenting an
    # address (the whole of the protection, see caller-identity-resolution).
    return session.exec(
        select(UserORM).where(
            func.lower(UserORM.email) == email,
            UserORM.keycloak_subject.is_(None),
            UserORM.deleted_at.is_(None),  # type: ignore[union-attr]
        )
    ).one_or_none()


def _active_user_by_email(session: Session, email: str) -> UserORM | None:
    # The subject-less path (D6) resolves by email alone, bound or not: it must
    # reach an already-bound record too, or a dev/test session whose record is
    # bound would be orphaned. It never writes, so reaching a bound record is
    # safe — there is no identity to bind it to.
    return session.exec(
        select(UserORM).where(
            func.lower(UserORM.email) == email,
            UserORM.deleted_at.is_(None),  # type: ignore[union-attr]
        )
    ).one_or_none()


def get_current_user(
    x_auth_request_email: str | None = Header(None),
    x_auth_request_user: str | None = Header(None),
    session: Session = Depends(get_session),
) -> UserORM:
    if not x_auth_request_email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not authenticated")

    email = x_auth_request_email.strip().lower()
    subject = x_auth_request_user.strip() if x_auth_request_user else None

    if subject is None:
        # D6: a subject-less request resolves by email alone and neither stamps
        # a record nor unbinds one. Unreachable on an edge-authenticated route,
        # where the subject header is always present.
        user = _active_user_by_email(session, email)
        if user is None:
            user = UserORM(email=email)
            session.add(user)
            session.commit()
            session.refresh(user)
        return user

    # 1. The subject is the join key. A record carrying it is reached by it
    #    alone, and a changed email updates that record in place rather than
    #    creating a second account.
    user = _active_user_by_subject(session, subject)
    if user is not None:
        if user.email.lower() != email:
            user.email = email
            session.add(user)
            try:
                session.commit()
            except IntegrityError as exc:
                # D7: a stale record still holds an address this identity now
                # owns, so the update would leave two active records on one
                # address. Fail loudly; neither row is mutated.
                session.rollback()
                raise UserResolutionConflictException(
                    f"cannot set user email to {email!r}: another active "
                    "user already holds it"
                ) from exc
            session.refresh(user)
        return user

    # 2. A record carrying no subject is adopted by a matching email, stamping
    #    the presented subject onto it.
    user = _active_adoptable_user_by_email(session, email)
    if user is not None:
        user.keycloak_subject = subject
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    # 3. No record: create one carrying both identifiers, so it is bound from
    #    its first request and never enters the adoptable state.
    user = UserORM(email=email, keycloak_subject=subject)
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        # D7: a stale record still holds this address, so a new record for it
        # would leave two active records on one address. Fail loudly.
        session.rollback()
        raise UserResolutionConflictException(
            f"cannot create user for {email!r}: another active user already "
            "holds it"
        ) from exc
    session.refresh(user)
    return user


def get_optional_user(
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
    return get_current_user(x_auth_request_email, x_auth_request_user, session)


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
