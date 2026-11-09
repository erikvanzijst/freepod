"""notification outbox

Adds ``notification_kind`` and ``notification_outbox``, where platform
services queue messages for people, and the trigger that wakes the notifier
whenever a row becomes pending.

Revision ID: 6c56968ccaab
Revises: a4d2e8f1c7b3
Create Date: 2026-11-09

"""
from alembic import op
import sqlalchemy as sa


revision = "6c56968ccaab"
down_revision = "a4d2e8f1c7b3"
branch_labels = None
depends_on = None

STATES = ("pending", "sent", "failed", "suppressed")


def upgrade() -> None:
    op.create_table(
        "notification_kind",
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("unsubscribable", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("kind"),
    )
    op.bulk_insert(
        sa.table("notification_kind", sa.column("kind", sa.Text()), sa.column("unsubscribable", sa.Boolean())),
        [
            {"kind": "access.invitation", "unsubscribable": False},
            {"kind": "database.quota", "unsubscribable": False},
        ],
    )

    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), server_default=sa.text("session_user"), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), nullable=True),
        sa.Column("recipient_email", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("action_label", sa.Text(), nullable=True),
        sa.Column("action_url", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column(
            "state",
            sa.Enum(*STATES, name="notification_state"),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(now() at time zone 'utc')"),
            nullable=False,
        ),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "num_nonnulls(recipient_user_id, recipient_email) = 1",
            name="ck_notification_outbox_one_recipient",
        ),
        sa.CheckConstraint(
            "(action_label IS NULL) = (action_url IS NULL)",
            name="ck_notification_outbox_action_whole",
        ),
        sa.CheckConstraint(
            "action_url IS NULL OR action_url LIKE 'https://%'",
            name="ck_notification_outbox_action_https",
        ),
        sa.ForeignKeyConstraint(["kind"], ["notification_kind.kind"]),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_notification_outbox_dedupe",
        "notification_outbox",
        ["kind", "dedupe_key", "recipient_user_id", "recipient_email"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )
    op.create_index(
        "ix_notification_outbox_pending",
        "notification_outbox",
        ["created_at"],
        postgresql_where=sa.text("state = 'pending'"),
    )

    # Row-level so the WHEN clause can see NEW; Postgres folds identical
    # notifications within one transaction into a single wake-up on commit.
    op.execute(
        """
        CREATE FUNCTION notification_outbox_wake() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_notify('notification_outbox', '');
            RETURN NULL;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER notification_outbox_wake
        AFTER INSERT OR UPDATE OF state ON notification_outbox
        FOR EACH ROW WHEN (NEW.state = 'pending')
        EXECUTE FUNCTION notification_outbox_wake()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER notification_outbox_wake ON notification_outbox")
    op.execute("DROP FUNCTION notification_outbox_wake()")
    op.drop_index("uq_notification_outbox_dedupe", table_name="notification_outbox")
    op.drop_index("ix_notification_outbox_pending", table_name="notification_outbox")
    op.drop_table("notification_outbox")
    sa.Enum(name="notification_state").drop(op.get_bind(), checkfirst=True)
    op.drop_table("notification_kind")
