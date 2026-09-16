"""Email only when a run has something for the owner (D14, product-upgrade-notifications)."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .config import Settings
from .db import Run

log = logging.getLogger(__name__)

NOTEWORTHY = {"opened", "would_open", "failed", "timed_out"}
SUBJECT_PRODUCTS = 3


def noteworthy(run: Run) -> bool:
    return run.state == "completed" and any(p.outcome in NOTEWORTHY for p in run.products)


def headline(run: Run) -> str:
    """The products the email is about, for scanning in an inbox: each named with its outcome
    and the version it moves to. The products that need nothing from the owner are left out,
    since they are not why the email was sent."""
    parts = []
    for p in run.products:
        if p.outcome not in NOTEWORTHY:
            continue
        name = f"{p.slug} {p.target_version}" if p.target_version else p.slug
        parts.append(f"{name} {p.outcome.replace('_', ' ')}")
    shown, rest = parts[:SUBJECT_PRODUCTS], len(parts) - len(parts[:SUBJECT_PRODUCTS])
    return ", ".join(shown) + (f" +{rest} more" if rest else "")


def compose(run: Run, settings: Settings) -> EmailMessage:
    counts: dict[str, int] = {}
    for product in run.products:
        counts[product.outcome] = counts.get(product.outcome, 0) + 1
    summary = ", ".join(f"{n} {outcome.replace('_', ' ')}" for outcome, n in sorted(counts.items()))
    mode = "Dry run" if run.dry_run else "Run"

    lines = [f"{mode} {run.id} ({run.trigger}) finished: {summary}.", ""]
    for p in run.products:
        versions = p.current_version or "?"
        if p.target_version:
            versions += f" -> {p.target_version}"
        lines.append(f"{p.slug}: {p.outcome.replace('_', ' ')}, {versions}")
        if p.pr_url:
            lines.append(f"  {'Draft pull request' if p.draft else 'Pull request'}: {p.pr_url}")
        elif p.outcome == "would_open":
            lines.append(f"  Would open {'a draft' if p.draft else 'a pull request'} from {p.branch}")
        if p.skip_reason:
            lines.append(f"  Skipped: {p.skip_reason}")
        for decision in p.needs_human or []:
            lines.append(f"  Needs a human: {decision}")
        if p.error:
            lines.append(f"  Error: {p.error}")
    if settings.dashboard_url:
        lines += ["", f"{settings.dashboard_url.rstrip('/')}/runs/{run.id}"]

    message = EmailMessage()
    message["Subject"] = f"[upgrader] {mode} {run.id}: {headline(run) or summary}"
    message["From"] = settings.notify_from
    message["To"] = settings.notify_email
    message.set_content("\n".join(lines) + "\n")
    return message


def send(run: Run, settings: Settings, smtp=smtplib.SMTP) -> bool:
    """Send the run's email if it is noteworthy. A failure is logged and changes nothing else."""
    if not settings.notify_email or not noteworthy(run):
        return False
    try:
        with smtp(settings.smtp_host, 25, timeout=30) as connection:
            connection.send_message(compose(run, settings))
    except (OSError, smtplib.SMTPException):
        log.exception("could not send the email for run %s", run.id)
        return False
    return True
