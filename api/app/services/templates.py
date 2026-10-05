from __future__ import annotations

from datetime import UTC, datetime

from typing import Any

from jsonschema import SchemaError
from jsonschema.validators import validator_for
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import (
    ProductORM,
    ProductTemplateVersionORM,
    ProductTemplateVersionRead,
    ProductTemplateVersionCreate,
    UserORM,
)
from app.services.errors import NotFoundException, IntegrityException, ValidationException
from app.services.template_values import check_var_markers, derive_projections
from app.services.products import _assert_deletable, _assert_mutable


def _get_product_orm(session: Session, product_id: int) -> ProductORM:
    """Load a non-deleted product row, for the curated write guard."""
    product = session.exec(
        select(ProductORM).where(
            ProductORM.id == product_id, ProductORM.deleted_at == None  # noqa: E711
        )
    ).one_or_none()
    if not product:
        raise NotFoundException("Product not found")
    return product


def _check_values_schema(schema: dict[str, Any] | None) -> None:
    """Meta-validate a template's `values_schema_json` document.

    `values_schema_json` is optional; `None` means the template takes no user
    values and is always accepted. When present, the document must itself be a
    well-formed JSON Schema. The dialect is selected from the document's own
    `$schema` key via `validator_for`, so templates declaring draft 2020-12
    are checked against 2020-12 rather than a hardcoded draft.

    Without this check a malformed schema is stored happily and only blows up
    later, in `validate_user_values`, for whichever tenant next tries to create
    a deployment. The routing markers are checked for the same reason: an
    illegal one fails here rather than at the next deployment of a template
    that tenants are, by then, already pointing at.

    The chart projection must be closed (`additionalProperties: false`). Its
    values are what a tenant POSTs directly, so an open projection would let one
    submit undeclared keys that flow into the Helm release as chart values --
    securityContext, image, extra hosts. This governs only the user-submitted
    chart values; the platform's own `caelus.*` overrides are merged in after
    validation and are never checked against this schema, so new `caelus.*`
    features need no template change. The vars projection's openness is
    deliberately untouched (it is `x-caelus-vars-additional`'s to decide, which
    is how `custom` accepts arbitrary environment).
    """
    if schema is None:
        return
    try:
        cls = validator_for(schema)
        cls.check_schema(schema)
    except SchemaError as exc:
        raise ValidationException(f"values_schema_json is not a valid JSON Schema: {exc.message}") from exc
    check_var_markers(schema)

    chart = derive_projections(schema).chart
    if chart is not None and chart.get("additionalProperties") is not False:
        raise ValidationException(
            "values_schema_json must set additionalProperties: false at the root: its "
            "chart values are tenant-submitted, so undeclared keys must be rejected rather "
            "than passed through to the Helm release"
        )


def create_template(
    session: Session,
    payload: ProductTemplateVersionCreate,
    *,
    force: bool = False,
    actor: UserORM | None = None,
) -> ProductTemplateVersionORM:
    """Create a template version for a product.

    A curated product's templates come from its catalog file, so creation is
    refused unless ``force`` is given. A forced row leaves ``catalog_commit``
    null — it is never set outside the reconciler — which is what makes
    hand-made drift distinguishable from catalog-produced history.
    """
    _check_values_schema(payload.values_schema_json)
    template = ProductTemplateVersionORM.model_validate(payload)
    # verify that the product exists:
    product = _get_product_orm(session, template.product_id)
    _assert_mutable(product, force=force, operation="create-template", actor=actor)

    session.add(template)
    try:
        session.commit()
        session.refresh(template)
        return template
    except IntegrityError as exc:
        raise IntegrityException(f"A template for this product version already exists") from exc


def list_templates(session: Session, product_id: int) -> list[ProductTemplateVersionRead]:
    # Return templates for the product that are not soft‑deleted
    templates = session.exec(
        select(ProductTemplateVersionORM)
        .where(ProductTemplateVersionORM.product_id == product_id)
        .where(ProductTemplateVersionORM.deleted_at == None)  # noqa: E712
    ).all()
    return [ProductTemplateVersionRead.model_validate(t) for t in templates]


def get_template(session: Session, *, product_id: int, template_id: int) -> ProductTemplateVersionRead:
    template = session.get(ProductTemplateVersionORM, template_id)
    if not template or template.product_id != product_id or template.deleted_at:
        raise NotFoundException("Template not found")
    return ProductTemplateVersionRead.model_validate(template)


def delete_template(
    session: Session,
    *,
    product_id: int,
    template_id: int,
    force: bool = False,
    actor: UserORM | None = None,
) -> ProductTemplateVersionRead:
    """Soft‑delete a template.

    Ensures the template belongs to the specified product and marks it as deleted.
    Raises NotFoundException if not found.
    Raises ValidationException if the product is catalog-managed; as with
    product deletion, ``force`` does not override this, because the reconciler
    reinserts any template whose spec the catalog still declares.
    """
    template = session.get(ProductTemplateVersionORM, template_id)
    if not template or template.product_id != product_id:
        raise NotFoundException("Template not found")
    _assert_deletable(_get_product_orm(session, product_id), subject="template")
    template.deleted_at = datetime.now(UTC)
    session.add(template)
    session.commit()
    return ProductTemplateVersionRead.model_validate(template)
