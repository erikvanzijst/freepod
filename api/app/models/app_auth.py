"""App authentication's own records: per-app consent and single-use sign-in codes.

Written and read only by `app-auth/` (a Go service connecting as its own
least-privilege role); the API never touches them. Declared here because every
table's schema is owned by this package's Alembic history. See the
`app-authentication` design doc, D8.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, LargeBinary, Text, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
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
