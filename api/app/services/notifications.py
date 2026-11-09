"""Queueing notifications for people (notification-outbox).

The API does not deliver mail: it queues a row in the caller's transaction and
`daemons/notifier/` renders and sends it. The body is Markdown, so every value
a producer interpolates goes through `md` first; the producer's own links stay
links.
"""

from __future__ import annotations

import string
from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session

from app.models import NotificationORM

_ESCAPES = str.maketrans({c: "\\" + c for c in string.punctuation})


def md(text: str) -> str:
    """`text` as literal Markdown: CommonMark lets a backslash escape any ASCII
    punctuation, so nothing in it can open a link, emphasis or HTML."""
    return text.translate(_ESCAPES)


@dataclass(frozen=True)
class Action:
    label: str
    url: str


def queue(
    session: Session,
    *,
    kind: str,
    subject: str,
    body: str,
    reason: str,
    user_id: int | None = None,
    email: str | None = None,
    heading: str | None = None,
    action: Action | None = None,
    dedupe_key: str | None = None,
) -> None:
    """Queue one notification for one recipient, a user or an address, in the
    caller's transaction. Never commits.

    With a dedupe key, a second notification of the same kind and key is
    dropped. `ON CONFLICT` names no target, as naming one needs SELECT on its
    columns, which producer roles lack; the only other unique key is the id.
    """
    values = {
        "kind": kind,
        "recipient_user_id": user_id,
        "recipient_email": email,
        "subject": subject,
        "heading": heading,
        "body": body,
        "action_label": action.label if action else None,
        "action_url": action.url if action else None,
        "reason": reason,
        "dedupe_key": dedupe_key,
    }
    session.execute(insert(NotificationORM.__table__).values(**values).on_conflict_do_nothing())
