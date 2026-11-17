"""`freepod status`: what the project's deployment is and what it is doing.

One summary object is built from the deployment read and the two storage
reads; `--json` prints it and the table is rendered from it, so the two forms
cannot disagree. Storage is best-effort: a failed read marks its row
unavailable and never fails the command.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import FreepodError, UsageError
from . import bucket as bucket_module
from . import database as database_module
from .api import ApiClient
from .apply import unapplied_keys
from .config import env_suffix
from .database import STATE_CONSEQUENCE, format_bytes, format_usage
from .delete import address, read_deployment
from .power import (
    MAINTENANCE_END,
    MAINTENANCE_STOP,
    PAYMENT_REMEDY,
    PAYMENT_STOP,
    RUNNING,
    STOPPED,
    power,
)
from .project import PROJECT_FILE, Project, require_project
from .table import format_time, render

_STATUS_STATE = {
    "deleting": "deleting",
    "deleted": "deleting",
    "pending": "pending",
    "provisioning": "provisioning",
    "error": "failed",
}

_POWER_STATE = {
    (RUNNING, RUNNING): "running",
    (STOPPED, RUNNING): "stopping",
    (RUNNING, STOPPED): "starting",
    (STOPPED, STOPPED): "stopped",
}

_STOP_TEXT = {
    "manual": "stopped — `freepod start` runs it",
    "payment": f"{PAYMENT_STOP} — {PAYMENT_REMEDY[0].lower()}{PAYMENT_REMEDY[1:].rstrip('.')}",
    "maintenance": f"{MAINTENANCE_STOP} — {MAINTENANCE_END}",
}

_PAYMENT_NOTE = {
    "arrears": "payment overdue",
    "pending": "awaiting the first payment",
}


def project_deployment(root: Optional[Path], env_name: str) -> Project:
    project = require_project(root)
    if project.deployment_id and project.env != env_name:
        raise UsageError(
            f"{project.path} records deployment {project.deployment_id} on "
            f"'{project.env}', not on '{env_name}'.\n"
            f"  Re-run without --env (or with --env {project.env})."
        )
    if not project.deployment_id:
        raise UsageError(
            f"{project.path} records no deployment, so there is nothing to report.\n"
            f"  Run `freepod init` to create one, or `freepod link` to point this "
            f"project at an existing one."
        )
    return project


def _best_effort(read: Callable[[], Optional[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    try:
        return read()
    except FreepodError as exc:
        return {"error": str(exc)}


def collect(api: ApiClient, env_name: str, *, root: Optional[Path] = None) -> Dict[str, Any]:
    """Read everything the report needs and return its summary."""
    project = project_deployment(root, env_name)
    user_id = api.me()["id"]
    record = read_deployment(api, user_id, project.deployment_id)
    if record is None:
        raise FreepodError(
            f"deployment {project.deployment_id} no longer exists{env_suffix(env_name)}.\n"
            f"  Run `freepod init --force` to create a new one."
        )
    database = _best_effort(lambda: database_module.read(api, user_id, project.deployment_id))
    bucket = _best_effort(lambda: bucket_module.read(api, user_id, project.deployment_id))
    return summarize(record, project, env_name, database=database, bucket=bucket)


def state(record: Dict[str, Any]) -> str:
    status = record.get("status")
    if status in _STATUS_STATE:
        return _STATUS_STATE[status]
    current = power(record)
    return _POWER_STATE.get((current.get("desired"), current.get("applied")), str(status))


def _release(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    release = record.get("applied_release")
    if not release:
        return None
    return {
        "number": release.get("number"),
        "status": release.get("status"),
        "ended_at": release.get("ended_at"),
        "build_id": release.get("build_id"),
    }


def _plan(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    subscription = record.get("subscription")
    if not subscription:
        return None
    template = subscription.get("plan_template") or {}
    return {
        "name": (template.get("plan") or {}).get("name"),
        "price_cents": template.get("price_cents"),
        "billing_interval": template.get("billing_interval"),
        "subscription_status": subscription.get("status"),
        "payment_status": subscription.get("payment_status"),
    }


def _sign_in(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    auth = record.get("auth")
    if not auth:
        return None
    return {
        "enabled": bool(auth.get("enabled")),
        "access": auth.get("access"),
        "listed_count": auth.get("listed_count"),
    }


def _database(details: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if details is None or "error" in details:
        return details
    return {
        "quota_state": details.get("quota_state"),
        "size_bytes": details.get("size_bytes"),
        "allowance_bytes": details.get("allowance_bytes"),
        "measured_at": details.get("measured_at"),
    }


def _bucket(details: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if details is None or "error" in details:
        return details
    usage = details.get("usage") or {}
    return {
        "bytes": usage.get("bytes"),
        "objects": usage.get("objects"),
        "max_size_bytes": usage.get("max_size_bytes"),
        "max_objects": usage.get("max_objects"),
    }


def summarize(
    record: Dict[str, Any],
    project: Project,
    env_name: str,
    *,
    database: Optional[Dict[str, Any]] = None,
    bucket: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The report as one JSON-ready object; its keys are a contract."""
    template = record.get("applied_template") or record.get("desired_template") or {}
    product = template.get("product") or {}
    applied = (record.get("applied_template") or {}).get("id")
    current = power(record)
    return {
        "id": record.get("id"),
        "name": record.get("name"),
        "description": record.get("description"),
        "product": {
            "name": product.get("name"),
            "slug": product.get("slug"),
            "chart_version": template.get("chart_version"),
        },
        "url": address(record),
        "environment": env_name,
        "created_at": record.get("created_at"),
        "status": record.get("status"),
        "last_error": record.get("last_error"),
        "last_reconcile_at": record.get("last_reconcile_at"),
        "power": {
            "desired": current.get("desired"),
            "applied": current.get("applied"),
            "reason": current.get("reason"),
        },
        "state": state(record),
        "release": _release(record),
        "plan": _plan(record),
        "sign_in": _sign_in(record),
        "drift": {
            "pending_vars": bool(record.get("pending")),
            "unapplied_keys": unapplied_keys(project, record),
            "template_update": applied is not None
            and applied != record.get("desired_template_id"),
        },
        "database": _database(database),
        "bucket": _bucket(bucket),
    }


# --------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------


def _state_text(summary: Dict[str, Any]) -> str:
    name = summary["state"]
    if name == "failed":
        error = summary.get("last_error") or "no error message recorded"
        return f"failed: {error} — a successful `freepod deploy` fixes it"
    if name in ("pending", "provisioning"):
        return "rolling out" if summary.get("release") else "being set up"
    if name == "deleting":
        return "being deleted"
    if name == "stopped":
        reason = summary["power"].get("reason")
        return _STOP_TEXT.get(reason, f"stopped ({reason})" if reason else "stopped")
    return name


def _release_text(release: Optional[Dict[str, Any]]) -> str:
    if not release:
        return "nothing released yet"
    text = f"#{release.get('number')}, {release.get('status')}"
    if release.get("ended_at"):
        text += f" {format_time(release['ended_at'])}"
    if release.get("build_id"):
        text += f" (build {str(release['build_id'])[:8]})"
    return text


def _price(cents: Any, interval: Any) -> str:
    if not isinstance(cents, int) or cents == 0:
        return "free"
    amount = f"€{cents // 100}" if cents % 100 == 0 else f"€{cents / 100:.2f}"
    per = {"monthly": "month", "annual": "year"}.get(interval, interval)
    return f"{amount}/{per}" if per else amount


def _plan_text(plan: Dict[str, Any]) -> str:
    name = plan.get("name") or "unnamed plan"
    price = _price(plan.get("price_cents"), plan.get("billing_interval"))
    text = name if price.lower() == name.lower() else f"{name}, {price}"
    if plan.get("subscription_status") == "cancelled":
        return f"{text} — canceled"
    note = _PAYMENT_NOTE.get(plan.get("payment_status"))
    return f"{text} — {note}" if note else text


def _sign_in_text(sign_in: Dict[str, Any]) -> str:
    if not sign_in.get("enabled"):
        return "off"
    if sign_in.get("access") == "listed":
        count = sign_in.get("listed_count") or 0
        people = "person" if count == 1 else "people"
        return f"on — only you and {count} listed {people}"
    return "on — any Freepod account"


def _changes_text(drift: Dict[str, Any]) -> str:
    parts = []
    if drift.get("unapplied_keys"):
        keys = ", ".join(drift["unapplied_keys"])
        parts.append(f"{PROJECT_FILE} not applied ({keys}) — `freepod apply`")
    if drift.get("pending_vars"):
        parts.append("vars staged, not rolled out — `freepod apply`")
    if drift.get("template_update"):
        parts.append("a product update is rolling out")
    return "; ".join(parts) if parts else "up to date"


def _database_text(database: Dict[str, Any]) -> str:
    if "error" in database:
        return f"unavailable ({database['error']})"
    allowance = database.get("allowance_bytes")
    size = database.get("size_bytes")
    if size is None:
        usage = "not yet measured"
    elif isinstance(allowance, int):
        usage = format_usage(size, allowance)
    else:
        usage = format_bytes(size)
    quota = database.get("quota_state")
    return f"{usage}, {STATE_CONSEQUENCE.get(quota, quota)}" if quota else usage


def _bucket_text(bucket: Dict[str, Any]) -> str:
    if "error" in bucket:
        return f"unavailable ({bucket['error']})"
    size, limit, objects = bucket.get("bytes"), bucket.get("max_size_bytes"), bucket.get("objects")
    if not isinstance(size, int):
        usage = "not reported"
    elif isinstance(limit, int):
        usage = format_usage(size, limit)
    else:
        usage = format_bytes(size)
    if isinstance(objects, int):
        usage += f", {objects:,} object{'' if objects == 1 else 's'}"
    return usage


def render_table(summary: Dict[str, Any], *, verbose: bool = False) -> str:
    product = summary["product"]
    product_text = product.get("name") or "unknown product"
    if product.get("chart_version"):
        product_text += f" (chart {product['chart_version']})"

    rows: List[Tuple[str, str]] = [("Name", str(summary.get("name") or ""))]
    if summary.get("description"):
        rows.append(("Description", summary["description"].strip().replace("\n", " ")))
    if summary.get("url"):
        rows.append(("Address", summary["url"]))
    rows += [
        ("Product", product_text),
        ("State", _state_text(summary)),
        ("Release", _release_text(summary.get("release"))),
    ]
    if summary.get("plan"):
        rows.append(("Plan", _plan_text(summary["plan"])))
    if summary.get("sign_in"):
        rows.append(("Sign-in", _sign_in_text(summary["sign_in"])))
    rows.append(("Changes", _changes_text(summary["drift"])))
    if summary.get("database"):
        rows.append(("Database", _database_text(summary["database"])))
    if summary.get("bucket"):
        rows.append(("Bucket", _bucket_text(summary["bucket"])))
    rows.append(("Created", format_time(summary.get("created_at"))))

    if verbose:
        current = summary["power"]
        power_text = f"{current.get('desired')}/{current.get('applied')}"
        if current.get("reason"):
            power_text += f" ({current['reason']})"
        rows += [
            ("Id", str(summary.get("id"))),
            ("Status", str(summary.get("status"))),
            ("Power", power_text),
            ("Reconciled", format_time(summary.get("last_reconcile_at"))),
        ]
    return render(rows)
