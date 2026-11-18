"""A deployment's own name, description and icon, and the fields a project
file manages (deployment-identity, deployment-project-file)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable
from uuid import UUID

from PIL import Image
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import DeploymentORM, ProductTemplateVersionORM
from app.services.errors import ConflictException, ValidationException
from app.services.images import IMAGE_FORMATS, generate_icon_filename, process_icon, save_icon
from app.services.reconcile_constants import DEPLOYMENT_STATUS_DELETED
from app.services.template_values import derive_projections

NAME_MAX = 100
DESCRIPTION_MAX = 500
ICON_MAX_BYTES = 256 * 1024
IDENTITY_KEYS = ("name", "description", "icon")
NAME_INDEX = "uq_deployment_display_name"


class InvalidIdentity(ValidationException):
    def __init__(self, message: str, *, code: str):
        self.code = code
        super().__init__(message)


class NameInUse(ConflictException):
    def __init__(self, name: str):
        super().__init__(f"You already have a deployment named '{name}'", code="name_in_use")


class ManagedByProjectFile(ConflictException):
    def __init__(self, key: str):
        self.field = key
        super().__init__(
            f"'{key}' is managed by the project file (.freepod.json): change it "
            "there, or take it over first",
            code="managed_by_project_file",
        )


def normalize_name(raw: str | None) -> str:
    if raw is None:
        raise InvalidIdentity("A deployment's name cannot be null", code="invalid_name")
    name = raw.strip()
    if not 1 <= len(name) <= NAME_MAX:
        raise InvalidIdentity(
            f"A deployment's name must be 1 to {NAME_MAX} characters", code="invalid_name"
        )
    if any(unicodedata.category(c) == "Cc" for c in name):
        raise InvalidIdentity(
            "A deployment's name cannot contain control characters", code="invalid_name"
        )
    return name


def normalize_description(raw: str | None) -> str | None:
    if raw is None:
        return None
    description = raw.strip()
    if len(description) > DESCRIPTION_MAX:
        raise InvalidIdentity(
            f"A deployment's description must be at most {DESCRIPTION_MAX} characters",
            code="invalid_description",
        )
    return description or None


def _taken_names(session: Session, *, user_id: int, exclude_id: UUID | None) -> set[str]:
    stmt = select(func.lower(DeploymentORM.display_name)).where(
        DeploymentORM.user_id == user_id,
        DeploymentORM.status != DEPLOYMENT_STATUS_DELETED,
    )
    if exclude_id is not None:
        stmt = stmt.where(DeploymentORM.id != exclude_id)
    return set(session.exec(stmt).all())


def require_name_free(
    session: Session, *, user_id: int, name: str, exclude_id: UUID | None = None
) -> None:
    if name.lower() in _taken_names(session, user_id=user_id, exclude_id=exclude_id):
        raise NameInUse(name)


def default_name(session: Session, *, user_id: int, base: str) -> str:
    """*base*, or the first of `base 2`, `base 3`... the owner has free."""
    base = base.strip()[:NAME_MAX] or "Deployment"
    taken = _taken_names(session, user_id=user_id, exclude_id=None)
    candidate, n = base, 1
    while candidate.lower() in taken:
        n += 1
        suffix = f" {n}"
        candidate = base[: NAME_MAX - len(suffix)] + suffix
    return candidate


def is_name_conflict(exc: IntegrityError) -> bool:
    return NAME_INDEX in str(exc.orig)


@dataclass(frozen=True)
class IconChange:
    """A new icon to record, or both fields `None` to clear it."""

    rel_icon_path: str | None
    source_sha256: str | None


def prepare_icon(encoded: str | None, *, current_sha256: str | None) -> IconChange | None:
    """The icon change *encoded* asks for, or `None` when it changes nothing.

    Bytes whose hash is the recorded one are not decoded again.
    """
    if encoded is None:
        return IconChange(None, None) if current_sha256 is not None else None
    if len(encoded) > (ICON_MAX_BYTES * 4) // 3 + 4:
        raise _icon_too_large()
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidIdentity("The icon must be base64-encoded", code="invalid_icon") from exc
    if len(data) > ICON_MAX_BYTES:
        raise _icon_too_large()
    digest = hashlib.sha256(data).hexdigest()
    if digest == current_sha256:
        return None
    try:
        Image.open(io.BytesIO(data), formats=IMAGE_FORMATS).close()
    except Exception as exc:
        raise _icon_wrong_format() from exc
    try:
        processed = process_icon(data)
    except ValueError as exc:
        raise InvalidIdentity(f"The icon could not be read: {exc}", code="invalid_icon") from exc
    rel_path = generate_icon_filename(processed)
    save_icon(processed, rel_path)
    return IconChange(rel_path, digest)


def _icon_too_large() -> InvalidIdentity:
    return InvalidIdentity(
        f"The icon must be at most {ICON_MAX_BYTES // 1024} KiB", code="invalid_icon"
    )


def _icon_wrong_format() -> InvalidIdentity:
    return InvalidIdentity("The icon must be a PNG, JPEG or WebP image", code="invalid_icon")


def icon_differs(encoded: str | None, *, current_sha256: str | None) -> bool:
    """Whether writing *encoded* would change the icon, without decoding an image."""
    if encoded is None:
        return current_sha256 is not None
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return True
    return hashlib.sha256(data).hexdigest() != current_sha256


def chart_keys(template: ProductTemplateVersionORM) -> set[str]:
    chart = derive_projections(template.values_schema_json).chart
    properties = (chart or {}).get("properties") or {}
    return set(properties)


def validate_managed_fields(keys: Iterable[str], template: ProductTemplateVersionORM) -> list[str]:
    allowed = set(IDENTITY_KEYS) | chart_keys(template)
    result: list[str] = []
    for key in keys:
        if key not in allowed:
            raise InvalidIdentity(
                f"'{key}' cannot be managed: it is neither name, description, icon "
                "nor a top-level property of this deployment's template",
                code="invalid_managed_fields",
            )
        if key not in result:
            result.append(key)
    return result


_MISSING = object()


def changed_chart_keys(old: dict[str, Any] | None, new: dict[str, Any] | None) -> set[str]:
    old, new = old or {}, new or {}
    return {k for k in set(old) | set(new) if old.get(k, _MISSING) != new.get(k, _MISSING)}


def refuse_managed_changes(managed: Iterable[str], changed: set[str]) -> None:
    for key in managed:
        if key in changed:
            raise ManagedByProjectFile(key)
