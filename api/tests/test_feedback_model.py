"""feedback-data-model."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models import FeedbackORM, FeedbackScreenshotORM, FeedbackTopic, UserORM
from app.models.core import _utcnow


@pytest.fixture
def sender(db_session) -> UserORM:
    user = UserORM(email="ana@example.com")
    db_session.add(user)
    db_session.commit()
    return user


def _feedback(db_session, sender, **kwargs) -> FeedbackORM:
    row = FeedbackORM(
        user_id=sender.id,
        email=sender.email,
        topic=kwargs.pop("topic", FeedbackTopic.BUG),
        message=kwargs.pop("message", "The button is gone"),
        page="/",
        **kwargs,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _insert_raw(db_session, sender, *, topic: str, message: str) -> None:
    db_session.execute(
        text(
            "INSERT INTO feedback (created_at, user_id, email, topic, message, page) "
            "VALUES (now(), :uid, :email, :topic, :message, '/')"
        ),
        {"uid": sender.id, "email": sender.email, "topic": topic, "message": message},
    )
    db_session.commit()


def test_a_new_submission_is_unread_unresolved_with_no_diagnostics(db_session, sender):
    row = _feedback(db_session, sender)
    db_session.refresh(row)
    assert row.read_at is None and row.resolved_at is None and row.resolved_by is None
    assert row.diagnostics == []


def test_an_unknown_topic_is_refused(db_session, sender):
    with pytest.raises(DBAPIError):
        _insert_raw(db_session, sender, topic="praise", message="Lovely")
    db_session.rollback()


@pytest.mark.parametrize("message", ["", "   \n\t "])
def test_a_blank_message_is_refused(db_session, sender, message):
    with pytest.raises(IntegrityError):
        _insert_raw(db_session, sender, topic="bug", message=message)
    db_session.rollback()


def test_a_message_over_5000_characters_is_refused(db_session, sender):
    with pytest.raises(IntegrityError):
        _insert_raw(db_session, sender, topic="bug", message="x" * 5001)
    db_session.rollback()


def _screenshot(feedback_id: int) -> FeedbackScreenshotORM:
    return FeedbackScreenshotORM(feedback_id=feedback_id, media_type="image/webp", width=1, height=1, data=b"x")


def test_a_second_screenshot_is_refused(db_session, sender):
    row = _feedback(db_session, sender)
    db_session.add(_screenshot(row.id))
    db_session.commit()
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO feedback_screenshot (feedback_id, media_type, width, height, data) "
                "VALUES (:id, 'image/webp', 1, 1, 'y')"
            ),
            {"id": row.id},
        )
    db_session.rollback()


def test_the_screenshot_is_deleted_with_its_submission(db_session, sender):
    row = _feedback(db_session, sender)
    db_session.add(_screenshot(row.id))
    db_session.commit()
    db_session.execute(text("DELETE FROM feedback WHERE id = :id"), {"id": row.id})
    db_session.commit()
    assert db_session.execute(text("SELECT count(*) FROM feedback_screenshot")).scalar() == 0


def test_a_soft_deleted_sender_keeps_their_submissions(db_session, sender):
    row = _feedback(db_session, sender)
    sender.deleted_at = _utcnow()
    sender.email = "deleted-1@example.invalid"
    db_session.add(sender)
    db_session.commit()
    db_session.refresh(row)
    assert (row.user_id, row.email) == (sender.id, "ana@example.com")


def test_the_sender_cannot_be_hard_deleted_under_their_feedback(db_session, sender):
    _feedback(db_session, sender)
    with pytest.raises(IntegrityError):
        db_session.execute(text('DELETE FROM "user" WHERE id = :id'), {"id": sender.id})
        db_session.commit()
    db_session.rollback()
