"""claim a permanent subdomain per user

Every application an account deploys is addressed under `<subdomain>.<domain>`,
and the wildcard certificate covering them is issued for it. Nullable, so no
backfill: NULL means the account has not claimed one. Unique among non-deleted
users and case-insensitively, mirroring `uq_user_active` — a deleted account
keeps its label rather than releasing it, because certificate transparency has
already published it.

Revision ID: f3a4b5c6d7e8
Revises: a9b0c1d2e3f4
Create Date: 2026-09-08 09:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f3a4b5c6d7e8'
down_revision = 'a9b0c1d2e3f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('user') as batch_op:
        batch_op.add_column(sa.Column('subdomain', sa.String(), nullable=True))
    op.create_index(
        'uq_user_subdomain_active',
        'user',
        [sa.text('lower(subdomain)')],
        unique=True,
        postgresql_where=sa.text('deleted_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_user_subdomain_active', table_name='user')
    with op.batch_alter_table('user') as batch_op:
        batch_op.drop_column('subdomain')
