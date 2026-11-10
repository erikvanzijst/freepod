"""Notices to every administrator about new accounts and new deployments."""

from __future__ import annotations

from sqlmodel import Session, select

from app.config import get_settings
from app.models import DeploymentORM, PlanTemplateVersionORM, UserORM
from app.services import notifications

md = notifications.md

_INTERVALS = {"monthly": "a month", "annual": "a year"}


def _notify_admins(
    session: Session, *, kind: str, subject: str, heading: str, body: str, panel: str, actor_id: int
) -> None:
    admins = session.exec(
        select(UserORM.id).where(
            UserORM.is_admin.is_(True),  # type: ignore[attr-defined]
            UserORM.deleted_at.is_(None),  # type: ignore[union-attr]
            UserORM.id != actor_id,
        )
    ).all()
    url = f"{get_settings().base_url.rstrip('/')}/admin/{panel}"
    # Local development serves the dashboard over plain HTTP, which an action may not link.
    action = notifications.Action(f"View {panel}", url) if url.startswith("https://") else None
    for admin_id in admins:
        notifications.queue(
            session,
            kind=kind,
            user_id=admin_id,
            subject=subject,
            heading=heading,
            body=body,
            action=action,
            reason="You received this email because you are a Freepod administrator.",
        )


def _details(rows: list[tuple[str, str | None]]) -> str:
    return "\n".join(f"- **{label}:** {value}" for label, value in rows if value is not None)


def account_created(session: Session, user: UserORM, *, ip: str | None) -> None:
    """Queue the notice for a user record that was just flushed."""
    details = _details([
        ("Email", md(user.email)),
        ("Account", str(user.id)),
        ("Subject", md(user.keycloak_subject) if user.keycloak_subject else None),
        ("IP address", md(ip) if ip else None),
        ("Created", f"{user.created_at:%-d %B %Y, %H:%M} UTC"),
    ])
    _notify_admins(
        session,
        kind="admin.account_created",
        subject=f"New account: {user.email}",
        heading="A new account was created",
        body=f"{md(user.email)} signed in to Freepod for the first time.\n\n{details}",
        panel="users",
        actor_id=user.id,
    )


def deployment_created(
    session: Session,
    deployment: DeploymentORM,
    *,
    owner: UserORM,
    product: str,
    plan_template: PlanTemplateVersionORM,
    awaiting_payment: bool,
) -> None:
    price = f"€{plan_template.price_cents / 100:.2f} {_INTERVALS[plan_template.billing_interval]}"
    at = f" at <https://{deployment.hostname}>" if deployment.hostname else ""
    details = _details([
        ("Product", md(product)),
        ("Plan", f"{md(plan_template.plan.name)}, {price}"),
        ("Status", "awaiting payment" if awaiting_payment else "provisioning"),
        ("Owner", md(owner.email) + (f" ({md(owner.handle)})" if owner.handle else "")),
        ("Deployment", md(deployment.name)),
    ])
    _notify_admins(
        session,
        kind="admin.deployment_created",
        subject=f"New deployment: {product} by {owner.email}",
        heading="A new app was deployed",
        body=f"{md(owner.email)} deployed {md(product)}{at}.\n\n{details}",
        panel="deployments",
        actor_id=owner.id,
    )
