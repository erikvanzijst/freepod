"""Queueing notifications from the API (notification-outbox)."""

from __future__ import annotations

import string

import pytest
from sqlmodel import Session, select

from app.models import NotificationORM, NotificationState, UserORM
from app.services import notifications


@pytest.mark.parametrize(
    "text, escaped",
    [
        ("[x](javascript:alert(1))", r"\[x\]\(javascript\:alert\(1\)\)"),
        ("*a*", r"\*a\*"),
        ("<b>", r"\<b\>"),
        ("ana_b@example.com", r"ana\_b\@example\.com"),
        ("plain words", "plain words"),
    ],
)
def test_md_makes_values_literal(text, escaped):
    assert notifications.md(text) == escaped


def test_md_escapes_every_ascii_punctuation_character():
    assert notifications.md(string.punctuation) == "".join("\\" + c for c in string.punctuation)


def test_queue_fills_the_row_and_leaves_delivery_to_the_database(db_session, test_database):
    user = UserORM(email="ana@example.com")
    db_session.add(user)
    db_session.commit()

    notifications.queue(
        db_session,
        kind="database.quota",
        user_id=user.id,
        subject="Subject",
        heading="Heading",
        body="Body",
        reason="Reason",
        action=notifications.Action("Open", "https://freepod.eu"),
    )
    db_session.commit()

    row = db_session.exec(select(NotificationORM)).one()
    assert (row.kind, row.recipient_user_id, row.recipient_email) == ("database.quota", user.id, None)
    assert (row.subject, row.heading, row.body, row.reason) == ("Subject", "Heading", "Body", "Reason")
    assert (row.action_label, row.action_url) == ("Open", "https://freepod.eu")
    assert row.state == NotificationState.PENDING
    assert row.attempts == 0
    assert row.origin == test_database.engine.url.username


def test_queue_does_not_commit(db_session, test_database):
    notifications.queue(db_session, kind="access.invitation", email="ana@example.com", subject="s", body="b", reason="r")
    with Session(test_database.engine) as other:
        assert other.exec(select(NotificationORM)).all() == []
    db_session.rollback()
    assert db_session.exec(select(NotificationORM)).all() == []


def test_a_repeated_dedupe_key_is_dropped(db_session):
    for _ in range(2):
        notifications.queue(
            db_session, kind="access.invitation", email="ana@example.com", subject="s", body="b", reason="r",
            dedupe_key="entry:1",
        )
    db_session.commit()
    assert len(db_session.exec(select(NotificationORM)).all()) == 1
