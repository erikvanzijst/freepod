"""The notification outbox's schema contract (notification-outbox): what the
database itself refuses, which role it records, and the wake-up it raises.

Producers and the notifier connect as their own roles, so those are real login
roles here: `origin` is `session_user`, which `SET ROLE` would not change.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import psycopg
import pytest
from psycopg import errors
from sqlalchemy.engine import make_url

from app.models import UserORM

REPO_ROOT = Path(__file__).resolve().parents[2]
NOTIFIER_BOOTSTRAP = REPO_ROOT / "tf/app/caelus/notifier-bootstrap.sql"
PRODUCER = "caelus_test_producer"
PASSWORD = "notification-outbox-test"
PRODUCER_COLUMNS = (
    "kind, recipient_user_id, recipient_email, subject, heading, body, "
    "action_label, action_url, reason, dedupe_key"
)


def _dsn(test_database, user: str | None = None) -> str:
    url = make_url(test_database.engine.url).set(drivername="postgresql")
    if user is not None:
        url = url.set(username=user, password=PASSWORD)
    return url.render_as_string(hide_password=False)


@pytest.fixture
def roles(test_database, db_session):
    """The notifier's role from its bootstrap, and a producer granted the
    producer columns as a platform service's bootstrap would grant them."""
    if shutil.which("psql") is None:
        pytest.skip("psql is not installed; it is how the cluster applies the bootstrap")
    subprocess.run(
        ["psql", _dsn(test_database), "-q", "-v", "ON_ERROR_STOP=1",
         "-v", f"notifier_password={PASSWORD}", "-f", str(NOTIFIER_BOOTSTRAP)],
        check=True, capture_output=True,
    )
    with psycopg.connect(_dsn(test_database), autocommit=True) as conn:
        conn.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{PRODUCER}') "
            f"THEN CREATE ROLE {PRODUCER} LOGIN; END IF; END $$"
        )
        conn.execute(f"ALTER ROLE {PRODUCER} PASSWORD '{PASSWORD}'")
        conn.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {PRODUCER}")
        conn.execute(f"GRANT USAGE ON SCHEMA public TO {PRODUCER}")
        conn.execute(f"GRANT INSERT ({PRODUCER_COLUMNS}) ON notification_outbox TO {PRODUCER}")


@pytest.fixture
def user_id(db_session) -> int:
    user = UserORM(email="ana@example.com")
    db_session.add(user)
    db_session.commit()
    return user.id


def _connect(test_database, user: str | None = None, **kwargs) -> psycopg.Connection:
    return psycopg.connect(_dsn(test_database, user), **kwargs)


def _queue(conn: psycopg.Connection, **values) -> None:
    row = {"kind": "access.invitation", "subject": "s", "body": "b", "reason": "r"} | values
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({c})s" for c in row)
    conn.execute(f"INSERT INTO notification_outbox ({columns}) VALUES ({placeholders})", row)


def _rows(test_database) -> list[tuple]:
    with _connect(test_database) as conn:
        return conn.execute(
            "SELECT kind, dedupe_key, origin, state::text FROM notification_outbox ORDER BY created_at"
        ).fetchall()


# --- recipients and content ---------------------------------------------------------


@pytest.mark.parametrize("recipient", [{}, {"recipient_email": "ana@example.com", "recipient_user_id": "user"}])
def test_neither_or_both_recipients_are_refused(test_database, user_id, recipient):
    if recipient.get("recipient_user_id") == "user":
        recipient["recipient_user_id"] = user_id
    with _connect(test_database) as conn, pytest.raises(errors.CheckViolation):
        _queue(conn, **recipient)


def test_a_user_recipient_alone_is_accepted(test_database, user_id):
    with _connect(test_database) as conn:
        _queue(conn, recipient_user_id=user_id)
    assert len(_rows(test_database)) == 1


def test_notifications_are_deleted_with_their_user(test_database, db_session, user_id):
    with _connect(test_database) as conn:
        _queue(conn, recipient_user_id=user_id)
        conn.execute('DELETE FROM "user" WHERE id = %s', (user_id,))
    assert _rows(test_database) == []


@pytest.mark.parametrize(
    "action",
    [{"action_label": "Open"}, {"action_url": "https://x.example"}, {"action_label": "Open", "action_url": "http://x.example"}],
)
def test_an_incomplete_or_insecure_action_is_refused(test_database, action):
    with _connect(test_database) as conn, pytest.raises(errors.CheckViolation):
        _queue(conn, recipient_email="ana@example.com", **action)


def test_no_heading_is_accepted(test_database):
    with _connect(test_database) as conn:
        _queue(conn, recipient_email="ana@example.com", heading=None)
    assert len(_rows(test_database)) == 1


# --- kinds ------------------------------------------------------------------------------


def test_the_seeded_kinds_exist(test_database, db_session):
    with _connect(test_database) as conn:
        kinds = dict(conn.execute("SELECT kind, unsubscribable FROM notification_kind").fetchall())
    assert kinds["access.invitation"] is False
    assert kinds["database.quota"] is False


def test_an_unknown_kind_is_refused(test_database, db_session):
    with _connect(test_database) as conn, pytest.raises(errors.ForeignKeyViolation):
        _queue(conn, kind="access.invitaton", recipient_email="ana@example.com")


# --- origin -----------------------------------------------------------------------------


def test_the_origin_is_the_role_that_queued(test_database, roles):
    with _connect(test_database, PRODUCER) as conn:
        _queue(conn, recipient_email="ana@example.com")
    assert _rows(test_database)[0][2] == PRODUCER


def test_a_producer_cannot_name_its_origin(test_database, roles):
    with _connect(test_database, PRODUCER) as conn, pytest.raises(errors.InsufficientPrivilege):
        _queue(conn, recipient_email="ana@example.com", origin="caelus")


# --- dedupe keys ------------------------------------------------------------------------


def test_a_dedupe_key_queues_once_without_select(test_database, roles):
    # Without a conflict target: naming one needs SELECT on its columns.
    with _connect(test_database, PRODUCER) as conn:
        for _ in range(2):
            conn.execute(
                "INSERT INTO notification_outbox (kind, recipient_email, subject, body, reason, dedupe_key) "
                "VALUES ('access.invitation', 'ana@example.com', 's', 'b', 'r', 'entry:42') "
                "ON CONFLICT DO NOTHING"
            )
    assert len(_rows(test_database)) == 1


@pytest.mark.parametrize("recipient", ["recipient_email", "recipient_user_id"])
def test_a_dedupe_key_conflicts_without_on_conflict(test_database, user_id, recipient):
    value = user_id if recipient == "recipient_user_id" else "ana@example.com"
    with _connect(test_database) as conn:
        _queue(conn, dedupe_key="entry:42", **{recipient: value})
        with pytest.raises(errors.UniqueViolation):
            _queue(conn, dedupe_key="entry:42", **{recipient: value})


def test_the_same_key_for_another_recipient_is_kept(test_database, user_id):
    with _connect(test_database) as conn:
        _queue(conn, recipient_email="ana@example.com", dedupe_key="entry:42")
        _queue(conn, recipient_email="bo@example.com", dedupe_key="entry:42")
        _queue(conn, recipient_user_id=user_id, dedupe_key="entry:42")
    assert len(_rows(test_database)) == 3


def test_rows_without_a_key_never_conflict(test_database, db_session):
    with _connect(test_database) as conn:
        _queue(conn, recipient_email="ana@example.com")
        _queue(conn, recipient_email="ana@example.com")
    assert len(_rows(test_database)) == 2


def test_the_same_key_under_another_kind_is_kept(test_database, db_session):
    with _connect(test_database) as conn:
        _queue(conn, recipient_email="ana@example.com", dedupe_key="k")
        _queue(conn, kind="database.quota", recipient_email="ana@example.com", dedupe_key="k")
    assert len(_rows(test_database)) == 2


# --- grants -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT id FROM notification_outbox",
        "UPDATE notification_outbox SET state = 'sent'",
        "DELETE FROM notification_outbox",
        "INSERT INTO notification_kind VALUES ('x.y', false)",
    ],
)
def test_a_producer_may_only_queue(test_database, roles, statement):
    with _connect(test_database, PRODUCER) as conn, pytest.raises(errors.InsufficientPrivilege):
        conn.execute(statement)


def test_the_notifier_claims_and_records(test_database, roles, user_id):
    with _connect(test_database) as conn:
        _queue(conn, recipient_user_id=user_id)
    with _connect(test_database, "caelus_notifier") as conn:
        (row_id, email) = conn.execute(
            "SELECT o.id, u.email FROM notification_outbox o JOIN \"user\" u ON u.id = o.recipient_user_id "
            "WHERE o.state = 'pending' FOR UPDATE OF o SKIP LOCKED"
        ).fetchone()
        conn.execute(
            "UPDATE notification_outbox SET state = 'sent', attempts = 1, "
            "last_attempt_at = now(), sent_at = now(), error = NULL WHERE id = %s",
            (row_id,),
        )
    assert email == "ana@example.com"
    assert _rows(test_database)[0][3] == "sent"


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO notification_outbox (kind, recipient_email, subject, body, reason) "
        "VALUES ('access.invitation', 'a@example.com', 's', 'b', 'r')",
        "DELETE FROM notification_outbox",
        "UPDATE notification_outbox SET body = 'x'",
        'SELECT keycloak_subject FROM "user"',
    ],
)
def test_the_notifier_may_do_nothing_else(test_database, roles, statement):
    with _connect(test_database, "caelus_notifier") as conn, pytest.raises(errors.InsufficientPrivilege):
        conn.execute(statement)


# --- wake-up ----------------------------------------------------------------------------


def _wakeups(listener: psycopg.Connection) -> int:
    return sum(1 for _ in listener.notifies(timeout=0.5))


@pytest.fixture
def listener(test_database, db_session):
    with _connect(test_database, autocommit=True) as conn:
        conn.execute("LISTEN notification_outbox")
        yield conn


def test_a_committed_queueing_wakes_listeners(test_database, listener):
    with _connect(test_database) as conn:
        _queue(conn, recipient_email="ana@example.com")
        _queue(conn, recipient_email="noor@example.com")
    assert _wakeups(listener) == 1


def test_a_rolled_back_queueing_wakes_nobody(test_database, listener):
    with _connect(test_database) as conn:
        _queue(conn, recipient_email="ana@example.com")
        conn.rollback()
    assert _wakeups(listener) == 0
    assert _rows(test_database) == []


def test_a_requeue_wakes_listeners_and_a_terminal_update_does_not(test_database, listener):
    with _connect(test_database) as conn:
        _queue(conn, recipient_email="ana@example.com")
    _wakeups(listener)
    with _connect(test_database) as conn:
        conn.execute("UPDATE notification_outbox SET state = 'failed'")
    assert _wakeups(listener) == 0
    with _connect(test_database) as conn:
        conn.execute("UPDATE notification_outbox SET state = 'pending'")
    assert _wakeups(listener) == 1
