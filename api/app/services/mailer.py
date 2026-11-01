"""Outbound mail through the shared SMTP relay.

The relay is an in-cluster service that accepts unauthenticated mail from the
platform's own namespaces, so there is no credential here. An unset
``smtp_host`` means "do not send", which is how dev and the test suite run.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import CaelusSettings, get_settings

logger = logging.getLogger(__name__)

SEND_TIMEOUT_SEC = 10


def send_email(
    *,
    to: str,
    subject: str,
    body: str,
    html: str | None = None,
    settings: CaelusSettings | None = None,
) -> bool:
    """Send one message, as plain text with an HTML alternative when `html` is
    given (see `mail_layout`). Returns whether it was sent.

    Never raises: callers are sweeps and reconciles whose work must not fail
    over a relay outage.
    """
    settings = settings or get_settings()
    if not settings.smtp_host or not settings.smtp_from:
        logger.debug("No SMTP relay configured; not sending %r to %s", subject, to)
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if html is not None:
        message.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=SEND_TIMEOUT_SEC
        ) as smtp:
            smtp.send_message(message)
    except Exception:
        logger.exception("Failed to send %r to %s via %s", subject, to, settings.smtp_host)
        return False

    logger.info("Sent %r to %s", subject, to)
    return True
