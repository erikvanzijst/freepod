"""Feedback submissions and their triage (feedback-api, feedback-notification).

REST and the admin UI share these rules; there are no `caelus` commands for
feedback (add-feedback D11).
"""

from __future__ import annotations

import json
import os
import re
from datetime import timedelta
from typing import Any
from urllib.parse import quote, unquote_plus

from sqlalchemy import func
from sqlmodel import Session, select

from app.config import get_settings
from app.models import (
    FEEDBACK_MESSAGE_MAX,
    FEEDBACK_TOPIC_LABELS,
    FeedbackListRead,
    FeedbackORM,
    FeedbackRead,
    FeedbackScreenshotORM,
    FeedbackSummary,
    FeedbackTopic,
    UserORM,
)
from app.models.core import _utcnow
from app.services import notifications
from app.services.errors import CodedNotFoundException, InvalidInputException, RateLimitedException
from app.services.images import process_feedback_screenshot

md = notifications.md

FEEDBACK_WINDOW = timedelta(hours=24)
PAGE_MAX = 2048
DIAGNOSTICS_MAX_ENTRIES = 20
DIAGNOSTICS_MAX_TEXT = 500
DIAGNOSTICS_MAX_BYTES = 32 * 1024
EXCERPT_LENGTH = 140
SUBJECT_EXCERPT = 60
_TEXT_LIMITS = {"user_agent": 512, "viewport": 32, "ui_build": 64}
_SECRET_KEYS = re.compile(r"^(code|state|token|.*_token|.*secret)$", re.IGNORECASE)


def normalize_page(page: str) -> str:
    """The page as a same-site path and query, with its fragment and every
    secret-looking query parameter removed (D7).

    Raises:
        InvalidInputException: `invalid_page` for anything but an absolute path.
    """
    page = (page or "").strip()
    if (
        not page.startswith("/")
        or page.startswith("//")
        or "\\" in page
        or len(page) > PAGE_MAX
        or any(ord(c) < 0x20 or ord(c) == 0x7F for c in page)
    ):
        raise InvalidInputException(
            "The page must be an absolute path on this site, such as /apps.", code="invalid_page"
        )
    path, _, query = page.split("#", 1)[0].partition("?")
    kept = [
        pair
        for pair in query.split("&")
        if pair and not _SECRET_KEYS.match(unquote_plus(pair.split("=", 1)[0]))
    ]
    return f"{path}?{'&'.join(kept)}" if kept else path


def sanitize_diagnostics(raw: str | None) -> list[dict[str, Any]]:
    """The client's recent problems, newest 20, as flat scalar entries of at
    most 500 characters each and 32 KB together (D6). Anything malformed is
    dropped rather than refused: diagnostics are display-only."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in data[-DIAGNOSTICS_MAX_ENTRIES:]:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {}
        for key, value in list(item.items())[:12]:
            if not isinstance(key, str) or len(key) > 32:
                continue
            if isinstance(value, str):
                entry[key] = value[:DIAGNOSTICS_MAX_TEXT]
            elif isinstance(value, bool) or value is None:
                entry[key] = value
            elif isinstance(value, (int, float)):
                entry[key] = value
        if entry:
            entries.append(entry)
    while entries and len(json.dumps(entries)) > DIAGNOSTICS_MAX_BYTES:
        entries.pop(0)
    return entries


def api_build() -> str | None:
    """The commit this API's image was built from, never the request's (D14)."""
    commit = (os.environ.get("GIT_COMMIT") or "").strip()
    return None if not commit or commit == "unknown" else commit


def _clip(value: str | None, limit: int) -> str | None:
    value = (value or "").strip()
    return value[:limit] or None


def _topic(value: str) -> FeedbackTopic:
    try:
        return FeedbackTopic(value)
    except ValueError:
        raise InvalidInputException(
            "Choose a topic: bug, idea or other.", code="invalid_topic"
        ) from None


def _check_message(message: str) -> None:
    if not message.strip():
        raise InvalidInputException("Write a message.", code="message_required")
    if len(message.strip()) > FEEDBACK_MESSAGE_MAX:
        raise InvalidInputException(
            f"The message is longer than {FEEDBACK_MESSAGE_MAX} characters.", code="message_too_long"
        )


def _check_limit(session: Session, user_id: int) -> None:
    limit = get_settings().feedback_per_day
    since = _utcnow() - FEEDBACK_WINDOW
    sent = session.exec(
        select(FeedbackORM.created_at)
        .where(FeedbackORM.user_id == user_id, FeedbackORM.created_at > since)
        .order_by(FeedbackORM.created_at)  # type: ignore[arg-type]
    ).all()
    if len(sent) >= limit:
        until = sent[len(sent) - limit] + FEEDBACK_WINDOW
        raise RateLimitedException(
            f"You have sent feedback {limit} times in the past 24 hours. "
            f"You can send more after {until.strftime('%Y-%m-%d %H:%M')} UTC.",
            code="feedback_limit",
        )


def submit_feedback(
    session: Session,
    *,
    user: UserORM,
    topic: str,
    message: str,
    page: str,
    user_agent: str | None = None,
    viewport: str | None = None,
    ui_build: str | None = None,
    diagnostics: str | None = None,
    screenshot: bytes | None = None,
) -> FeedbackORM:
    """Store one submission from `user`, and queue its email in the same
    transaction when the environment has a feedback address (D12)."""
    chosen = _topic(topic)
    _check_message(message)
    normalized = normalize_page(page)
    _check_limit(session, user.id)

    image: tuple[bytes, int, int] | None = None
    if screenshot:
        try:
            image = process_feedback_screenshot(screenshot)
        except ValueError as e:
            raise InvalidInputException(str(e), code="invalid_screenshot") from None

    row = FeedbackORM(
        user_id=user.id,
        email=user.email,
        topic=chosen,
        message=message.strip(),
        page=normalized,
        user_agent=_clip(user_agent, _TEXT_LIMITS["user_agent"]),
        viewport=_clip(viewport, _TEXT_LIMITS["viewport"]),
        ui_build=_clip(ui_build, _TEXT_LIMITS["ui_build"]),
        api_build=api_build(),
        diagnostics=sanitize_diagnostics(diagnostics),
    )
    session.add(row)
    session.flush()
    if image is not None:
        data, width, height = image
        session.add(
            FeedbackScreenshotORM(
                feedback_id=row.id, media_type="image/webp", width=width, height=height, data=data
            )
        )
    _queue_notification(session, row, user=user, has_screenshot=image is not None)
    session.commit()
    session.refresh(row)
    return row


def _subject(row: FeedbackORM) -> str:
    first = row.message.strip().splitlines()[0].strip()
    if len(first) > SUBJECT_EXCERPT:
        first = first[: SUBJECT_EXCERPT - 1].rstrip() + "…"
    environment = get_settings().environment
    prefix = f"[{environment}] " if environment != "prod" else ""
    return f"{prefix}Feedback · {FEEDBACK_TOPIC_LABELS[row.topic]}: {first}"


def _queue_notification(session: Session, row: FeedbackORM, *, user: UserORM, has_screenshot: bool) -> None:
    settings = get_settings()
    if not settings.feedback_email:
        return
    base = settings.base_url.rstrip("/")
    page_url = base + quote(row.page, safe="/?&=%:@!$'*+,;~-._")
    sender = md(row.email) + (f" ({md(user.handle)})" if user.handle else "")
    details = [
        ("From", sender),
        ("Page", f"[{md(row.page)}]({page_url})"),
        ("Browser", md(row.user_agent) if row.user_agent else None),
        ("Viewport", md(row.viewport) if row.viewport else None),
        ("UI build", md(row.ui_build) if row.ui_build else None),
        ("API build", md(row.api_build) if row.api_build else None),
        ("Screenshot", "attached in Admin" if has_screenshot else "none"),
    ]
    body = "\n\n".join(md(paragraph) for paragraph in row.message.splitlines() if paragraph.strip())
    body += "\n\n" + "\n".join(f"- **{label}:** {value}" for label, value in details if value is not None)
    url = f"{base}/admin/feedback/{row.id}"
    notifications.queue(
        session,
        kind="feedback.submitted",
        email=settings.feedback_email,
        subject=_subject(row),
        heading=FEEDBACK_TOPIC_LABELS[row.topic],
        body=body,
        action=notifications.Action("View in Admin", url) if url.startswith("https://") else None,
        reason="You received this email because this address receives Freepod feedback.",
    )


def _has_screenshot():
    return (
        select(FeedbackScreenshotORM.feedback_id)
        .where(FeedbackScreenshotORM.feedback_id == FeedbackORM.id)
        .exists()
    )


def _excerpt(message: str) -> str:
    flat = " ".join(message.split())
    return flat if len(flat) <= EXCERPT_LENGTH else flat[: EXCERPT_LENGTH - 1].rstrip() + "…"


def list_feedback(
    session: Session,
    *,
    resolved: bool | None = False,
    topic: FeedbackTopic | None = None,
    offset: int = 0,
    limit: int = 50,
) -> FeedbackListRead:
    """Submissions newest first, without screenshot data, and the number of
    unread submissions across all of them."""
    where = []
    if resolved is True:
        where.append(FeedbackORM.resolved_at.is_not(None))  # type: ignore[union-attr]
    elif resolved is False:
        where.append(FeedbackORM.resolved_at.is_(None))  # type: ignore[union-attr]
    if topic is not None:
        where.append(FeedbackORM.topic == topic)
    total = session.exec(select(func.count()).select_from(FeedbackORM).where(*where)).one()
    unread = session.exec(
        select(func.count()).select_from(FeedbackORM).where(FeedbackORM.read_at.is_(None))  # type: ignore[union-attr]
    ).one()
    items: list[FeedbackSummary] = []
    if limit > 0:
        rows = session.exec(
            select(
                FeedbackORM.id,
                FeedbackORM.created_at,
                FeedbackORM.user_id,
                FeedbackORM.email,
                FeedbackORM.topic,
                FeedbackORM.message,
                FeedbackORM.page,
                FeedbackORM.read_at,
                FeedbackORM.resolved_at,
                _has_screenshot().label("has_screenshot"),
            )
            .where(*where)
            .order_by(FeedbackORM.created_at.desc(), FeedbackORM.id.desc())  # type: ignore[attr-defined,union-attr]
            .offset(offset)
            .limit(limit)
        ).all()
        items = [
            FeedbackSummary(
                id=r.id,
                created_at=r.created_at,
                user_id=r.user_id,
                email=r.email,
                topic=r.topic,
                excerpt=_excerpt(r.message),
                page=r.page,
                has_screenshot=r.has_screenshot,
                read=r.read_at is not None,
                resolved=r.resolved_at is not None,
            )
            for r in rows
        ]
    return FeedbackListRead(items=items, total=total, unread=unread)


def _get(session: Session, feedback_id: int) -> FeedbackORM:
    row = session.get(FeedbackORM, feedback_id)
    if row is None:
        raise CodedNotFoundException("No such feedback.", code="feedback_not_found")
    return row


def _read(session: Session, row: FeedbackORM) -> FeedbackRead:
    shot = session.exec(
        select(FeedbackScreenshotORM.width, FeedbackScreenshotORM.height).where(
            FeedbackScreenshotORM.feedback_id == row.id
        )
    ).one_or_none()
    resolver = session.get(UserORM, row.resolved_by) if row.resolved_by else None
    return FeedbackRead(
        **row.model_dump(exclude={"resolved_by"}),
        resolved_by=row.resolved_by,
        has_screenshot=shot is not None,
        screenshot_width=shot.width if shot else None,
        screenshot_height=shot.height if shot else None,
        resolved_by_email=resolver.email if resolver else None,
    )


def get_feedback(session: Session, feedback_id: int) -> FeedbackRead:
    """One whole submission; the first read by any administrator marks it read."""
    row = _get(session, feedback_id)
    if row.read_at is None:
        row.read_at = _utcnow()
        session.add(row)
        session.commit()
        session.refresh(row)
    return _read(session, row)


def get_screenshot(session: Session, feedback_id: int) -> FeedbackScreenshotORM:
    _get(session, feedback_id)
    shot = session.get(FeedbackScreenshotORM, feedback_id)
    if shot is None:
        raise CodedNotFoundException("This feedback has no screenshot.", code="feedback_screenshot_not_found")
    return shot


def set_resolved(session: Session, feedback_id: int, *, resolved: bool, admin: UserORM) -> FeedbackRead:
    """Resolve or reopen; setting the state it is already in changes nothing."""
    row = _get(session, feedback_id)
    if resolved and row.resolved_at is None:
        row.resolved_at = _utcnow()
        row.resolved_by = admin.id
    elif not resolved and row.resolved_at is not None:
        row.resolved_at = None
        row.resolved_by = None
    else:
        return _read(session, row)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _read(session, row)
