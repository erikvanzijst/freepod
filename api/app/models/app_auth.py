"""App authentication's own records: per-app consent, single-use sign-in codes,
the OpenID Provider's authorization codes, and the access lists of `listed`
deployments.

The consent and code tables are written and read only by `daemons/app-auth/` (a
Go service connecting as its own least-privilege role); the API never touches
them. The access tables are the API's, which app-auth reads and binds.
Declared here because every table's schema is owned by this package's Alembic
history. See the `app-authentication` design doc, D8.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from pydantic import ConfigDict
from sqlmodel import Field, SQLModel

from app.models.core import _utcnow


class AppAuthConsentORM(SQLModel, table=True):
    """A user's agreement to disclose `claims` to one deployment.

    Keyed by the Keycloak subject, with no foreign key to `user`: people who
    sign in to apps need never have opened Freepod itself.
    """

    __tablename__ = "app_auth_consent"

    subject: str = Field(sa_column=Column(Text(), primary_key=True))
    deployment_id: UUID = Field(
        sa_column=Column(Uuid, ForeignKey("deployment.id", ondelete="CASCADE"), primary_key=True)
    )
    claims: list[str] = Field(sa_column=Column(ARRAY(Text()), nullable=False))
    granted_at: datetime = Field(default_factory=_utcnow, sa_column=Column(DateTime(), nullable=False))


class AppAuthCodeORM(SQLModel, table=True):
    """A sign-in code the broker issued and an app host has not yet redeemed.

    Only the SHA-256 of the code is stored, so reading this table yields
    nothing redeemable. Redemption deletes the row, whatever the outcome.
    """

    __tablename__ = "app_auth_code"
    __table_args__ = (
        CheckConstraint("octet_length(code_hash) = 32", name="ck_app_auth_code_code_hash_len"),
        CheckConstraint("octet_length(nonce_hash) = 32", name="ck_app_auth_code_nonce_hash_len"),
        Index("ix_app_auth_code_expires_at", "expires_at"),
    )

    code_hash: bytes = Field(sa_column=Column(LargeBinary(), primary_key=True))
    host: str = Field(sa_column=Column(Text(), nullable=False))
    subject: str = Field(sa_column=Column(Text(), nullable=False))
    email: str = Field(sa_column=Column(Text(), nullable=False))
    name: str = Field(sa_column=Column(Text(), nullable=False))
    return_path: str = Field(sa_column=Column(Text(), nullable=False))
    nonce_hash: bytes = Field(sa_column=Column(LargeBinary(), nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime(), nullable=False))


class AppAuthOIDCCodeORM(SQLModel, table=True):
    """An authorization code the OpenID Provider issued to a deployment's app.

    Hashed and single-use like `app_auth_code`, but redeemed by client and
    redirect URI rather than by host, so the two never share a table.
    """

    __tablename__ = "app_auth_oidc_code"
    __table_args__ = (
        CheckConstraint("octet_length(code_hash) = 32", name="ck_app_auth_oidc_code_code_hash_len"),
        Index("ix_app_auth_oidc_code_expires_at", "expires_at"),
    )

    code_hash: bytes = Field(sa_column=Column(LargeBinary(), primary_key=True))
    deployment_id: UUID = Field(
        sa_column=Column(Uuid, ForeignKey("deployment.id", ondelete="CASCADE"), nullable=False)
    )
    redirect_uri: str = Field(sa_column=Column(Text(), nullable=False))
    subject: str = Field(sa_column=Column(Text(), nullable=False))
    email: str = Field(sa_column=Column(Text(), nullable=False))
    name: str = Field(sa_column=Column(Text(), nullable=False))
    nonce: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
    code_challenge: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
    auth_time: datetime = Field(sa_column=Column(DateTime(), nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime(), nullable=False))


class AppAccessEntryORM(SQLModel, table=True):
    """A person the owner of a `listed` deployment admits (app-access-list).

    Added by email; the first account to sign in with that email binds the
    entry to its subject, which is what matches from then on (D3). The owner
    is never an entry. The API inserts and deletes; app-auth binds.
    """

    __tablename__ = "app_access_entry"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="ck_app_access_entry_email_lower"),
        UniqueConstraint("deployment_id", "email", name="uq_app_access_entry_email"),
        Index(
            "uq_app_access_entry_subject",
            "deployment_id",
            "subject",
            unique=True,
            postgresql_where=text("subject IS NOT NULL"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, sa_column=Column(Uuid, primary_key=True))
    deployment_id: UUID = Field(
        sa_column=Column(Uuid, ForeignKey("deployment.id", ondelete="CASCADE"), nullable=False)
    )
    email: str = Field(sa_column=Column(Text(), nullable=False))
    subject: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
    name: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
    created_at: datetime = Field(default_factory=_utcnow, sa_column=Column(DateTime(), nullable=False))
    bound_at: datetime | None = Field(default=None, sa_column=Column(DateTime(), nullable=True))


class AppAccessInvitationORM(SQLModel, table=True):
    """One invitation email an owner sent, counted against their daily limit.

    Deliberately not tied to the entry, so removing the entry does not hand
    the invitation back (D6).
    """

    __tablename__ = "app_access_invitation"
    __table_args__ = (Index("ix_app_access_invitation_user_sent", "user_id", "sent_at"),)

    id: UUID = Field(default_factory=uuid4, sa_column=Column(Uuid, primary_key=True))
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    )
    sent_at: datetime = Field(default_factory=_utcnow, sa_column=Column(DateTime(), nullable=False))


class AccessEntryCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254, description="The address to admit. Stored in lower case.")


class AccessEntryRead(SQLModel):
    id: UUID
    email: str
    # The display name and time of the first sign-in with this entry, once
    # someone has signed in with it.
    name: str | None = None
    created_at: datetime
    bound_at: datetime | None = None


class AccessListRead(SQLModel):
    """Who may sign in to a deployment, as the serving release configures it.

    The owner is always admitted and is never an entry.
    """

    enabled: bool
    protocol: str
    access: str
    owner_email: str
    limit: int
    entries: list[AccessEntryRead]
