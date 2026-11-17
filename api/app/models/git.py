"""A user's connections to git hosting providers.

A row is a connection; its absence means "not connected". Both OAuth tokens are
encrypted together in one value under the var keyring, because every refresh
replaces both.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import ConfigDict

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Identity, Index, Integer, String, Text
from sqlmodel import Field, SQLModel

from app.models.core import _utcnow


class GitProvider:
    GITHUB = "github"


class GitConnectionORM(SQLModel, table=True):
    __tablename__ = "git_connection"
    __table_args__ = (
        Index("uq_git_connection_user", "user_id", "provider", "host", unique=True),
        Index("uq_git_connection_account", "provider", "host", "account_id", unique=True),
    )

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger(), Identity(always=True), primary_key=True, autoincrement=True),
    )
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    )
    provider: str = Field(sa_column=Column(String(16), nullable=False))
    host: str = Field(sa_column=Column(String(253), nullable=False))
    account_id: str = Field(sa_column=Column(String(64), nullable=False))
    login: str = Field(sa_column=Column(String(255), nullable=False))
    tokens_encrypted: str = Field(sa_column=Column(Text(), nullable=False))
    key_id: str = Field(sa_column=Column(String(8), nullable=False))
    access_token_expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(), nullable=True)
    )
    refresh_token_expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(), nullable=True)
    )
    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)


class GitConnectionRead(SQLModel):
    provider: str
    host: str
    account_id: str
    login: str
    connected_at: datetime
    expires_at: Optional[datetime] = None


class GitHubConnectStart(SQLModel):
    authorize_url: str
    install_url: str


class GitHubInstallationRead(SQLModel):
    id: int
    account: str
    account_type: str
    repository_selection: str
    html_url: str


class GitHubRepositoryCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    owner: Optional[str] = None
    private: bool = True
    description: Optional[str] = None


class GitHubRepositoryRead(SQLModel):
    id: int
    full_name: str
    html_url: str
    clone_url: str
    private: bool
    default_branch: Optional[str] = None


class GitCredentialRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    repository: str
    access: Literal["read", "write"] = "write"


class GitCredentialRead(SQLModel):
    repository: str
    username: str
    password: str
    expires_at: datetime
