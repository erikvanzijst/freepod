"""The JSON Schema of a product's project file (deployment-project-file, D9)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlmodel import Session, select

from app.models import ProductORM, ProductTemplateVersionORM, ProductVisibility
from app.services.deployment_identity import DESCRIPTION_MAX, ICON_MAX_BYTES, NAME_MAX
from app.services.errors import NotFoundException
from app.services.template_values import derive_projections

PROJECT_FORMAT = 2

_FILE_KEYS: dict[str, Any] = {
    "$schema": {"type": "string", "description": "This schema's URL."},
    "version": {"const": PROJECT_FORMAT, "description": "The project file format."},
    "env": {"type": "string", "description": "The Freepod environment the project deploys to."},
    "deployment": {
        "type": "string",
        "format": "uuid",
        "description": "The id of the deployment this project is linked to.",
    },
}

_METADATA_KEYS: dict[str, Any] = {
    "name": {
        "type": "string",
        "minLength": 1,
        "maxLength": NAME_MAX,
        "description": "The deployment's name, unique among your deployments.",
    },
    "description": {
        "type": "string",
        "maxLength": DESCRIPTION_MAX,
        "description": "The deployment's description.",
    },
    "icon": {
        "type": "string",
        "minLength": 1,
        "description": (
            "Path to the deployment's icon, relative to this file: a PNG, JPEG or "
            f"WebP image of at most {ICON_MAX_BYTES // 1024} KiB."
        ),
    },
}


def project_schema(session: Session, *, slug: str) -> dict[str, Any]:
    product = session.exec(
        select(ProductORM).where(
            ProductORM.slug == slug,
            ProductORM.deleted_at == None,  # noqa: E711
            ProductORM.visibility.in_([ProductVisibility.PUBLIC, ProductVisibility.UNLISTED]),
        )
    ).one_or_none()
    template = (
        session.get(ProductTemplateVersionORM, product.template_id)
        if product is not None and product.template_id is not None
        else None
    )
    if template is None:
        raise NotFoundException("Product not found")

    chart = derive_projections(template.values_schema_json).chart or {}
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"Freepod project file: {product.name}",
        "type": "object",
        "properties": {
            **deepcopy(_FILE_KEYS),
            **deepcopy(_METADATA_KEYS),
            **deepcopy(chart.get("properties") or {}),
        },
        "additionalProperties": False,
    }
    for defs in ("$defs", "definitions"):
        if defs in chart:
            schema[defs] = deepcopy(chart[defs])
    return schema
