"""add user.keycloak_subject and its partial unique index

The Keycloak subject becomes the join key between a Keycloak identity and a
Freepod user record; email becomes a mutable attribute of that record. This adds
a nullable `keycloak_subject` column to `user` (NULL until the record is bound
to a subject) and a partial unique index over it where `deleted_at IS NULL`,
mirroring `uq_user_active` on the email column.

Additive: existing rows keep a NULL subject and are adopted lazily on their
owner's next authenticated request (see caller-identity-resolution).

Revision ID: f1e2d3c4b5a6
Revises: f3a4b5c6d7e8
Create Date: 2026-09-07 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f1e2d3c4b5a6'
down_revision = 'f3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('user', sa.Column('keycloak_subject', sa.String(), nullable=True))
    op.create_index(
        'uq_user_subject_active',
        'user',
        ['keycloak_subject'],
        unique=True,
        postgresql_where=sa.text('deleted_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_user_subject_active', table_name='user')
    op.drop_column('user', 'keycloak_subject')
