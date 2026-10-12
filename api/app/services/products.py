from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import (
    ProductRead,
    ProductORM,
    ProductCreate,
    ProductUpdate,
    ProductVisibility,
    UserORM,
)
from app.services import templates as template_service
from app.services.errors import NotFoundException, IntegrityException, ValidationException
from app.services.images import process_icon, generate_icon_filename, save_icon, MAX_ICON_SIZE

logger = logging.getLogger(__name__)

# Where a curated product's desired state lives, quoted back to the operator in
# every refusal so the error names the file to edit rather than just the rule.
CATALOG_DIR_LABEL = "products/catalog"


def catalog_file_for(product: ProductORM) -> str:
    """The catalog file that declares ``product``, for use in error messages."""
    return f"{CATALOG_DIR_LABEL}/{product.slug or product.name}.yaml"


def _assert_mutable(
    product: ProductORM,
    *,
    force: bool = False,
    operation: str = "modify",
    actor: UserORM | None = None,
) -> None:
    """Refuse database-authored writes to a catalog-owned product.

    The guard lives here rather than in the UI so that the REST API, the Typer
    CLI, and the React admin are held to the same rule; guarding only the UI
    would leave ``caelus update-product`` as an unguarded back door.

    ``force`` is the break-glass override for urgent intervention. It applies to
    *modifications* only — the caller passes ``force=False`` unconditionally for
    deletions, which are never overridable (see ``delete_product``). A forced
    write is logged at WARNING so the drift it creates is visible until the next
    reconciliation heals it.
    """
    if not product.curated:
        return
    if force:
        logger.warning(
            "Forced write to curated product product_id=%s slug=%s operation=%s actor=%s",
            product.id,
            product.slug,
            operation,
            actor.email if actor else "unknown",
        )
        return
    raise ValidationException(
        f"Product '{product.name}' is managed by the catalog. "
        f"Edit {catalog_file_for(product)} and merge the change instead."
    )


def _assert_deletable(product: ProductORM, *, subject: str = "product") -> None:
    """Refuse deletion of a curated product or its templates, force or not.

    Deletion is excluded from the override because the override cannot achieve
    what the operator intends: the reconciler resolves a curated product by slug
    among non-deleted rows, so a force-deleted product is not found, is not
    adopted, and is recreated under a new id on the next rollout while existing
    deployments keep referencing templates on the old row. Removing the catalog
    file first is the supported path, and is itself a reviewable diff.
    """
    if not product.curated:
        return
    raise ValidationException(
        f"Cannot delete this {subject}: product '{product.name}' is managed by the catalog, "
        f"and deletion cannot be forced because the next reconciliation would recreate it. "
        f"Remove {catalog_file_for(product)}, let the rollout release the product, then delete it."
    )


def create_product(
    session: Session, payload: ProductCreate, icon_data: bytes | None = None
) -> ProductRead:
    """Create a product, optionally with an icon.

    Args:
        session: Database session
        payload: Product create payload
        icon_data: Optional raw icon image bytes

    Returns:
        Created ProductRead with icon_url if icon provided

    Raises:
        IntegrityException: If product name already exists
        ValidationException: If icon processing fails
    """
    if icon_data is not None and len(icon_data) > MAX_ICON_SIZE:
        raise ValidationException(
            f"Image file too large. Maximum size is {MAX_ICON_SIZE // (1024 * 1024)}MB"
        )

    product = ProductORM.model_validate(payload)
    session.add(product)

    try:
        if icon_data is not None:
            processed_icon = process_icon(icon_data)
            rel_icon_path = generate_icon_filename(processed_icon)
            save_icon(processed_icon, rel_icon_path)
            product.rel_icon_path = rel_icon_path

        session.commit()
        session.refresh(product)
        return ProductRead.model_validate(product)
    except IntegrityError as exc:
        session.rollback()
        raise IntegrityException(
            f"A product with this name already exists: {product.name}"
        ) from exc
    except ValueError as exc:
        session.rollback()
        raise ValidationException(str(exc)) from exc


def list_products(session: Session, *, include_hidden: bool = False) -> list[ProductRead]:
    """List non-deleted products.

    Args:
        session: Database session
        include_hidden: When False (the end-user listing) only products with
            ``visibility`` of ``public`` or ``unlisted`` are returned. When
            True (the administrative listing) every non-deleted product is
            returned, filtered on ``deleted_at`` alone, so experimental and
            deprecated products stay discoverable to operators.
    """
    statement = select(ProductORM).where(ProductORM.deleted_at == None)
    if not include_hidden:
        statement = statement.where(
            ProductORM.visibility.in_([ProductVisibility.PUBLIC, ProductVisibility.UNLISTED])
        )
    return [ProductRead.model_validate(p) for p in session.exec(statement).all()]


def get_product(session: Session, product_id: int) -> ProductRead:
    if not (
        product := session.exec(
            select(ProductORM).where(ProductORM.id == product_id, ProductORM.deleted_at == None)
        ).one_or_none()
    ):
        raise NotFoundException("Product not found")
    return ProductRead.model_validate(product)


def delete_product(
    session: Session, *, product_id: int, force: bool = False, actor: UserORM | None = None
) -> ProductRead:
    """Soft‑delete a product by setting its ``deleted`` flag.

    Raises NotFoundException if the product does not exist.
    Raises ValidationException if the product is catalog-managed; ``force`` is
    accepted for interface symmetry but deliberately does not override this.
    """
    # Retrieve the product that is not already deleted
    if not (
        product := session.exec(
            select(ProductORM).where(ProductORM.id == product_id, ProductORM.deleted_at == None)
        ).one_or_none()
    ):
        raise NotFoundException("Product not found")
    _assert_deletable(product)
    product.deleted_at = datetime.now(UTC)
    session.commit()
    return ProductRead.model_validate(product)


def update_product(
    session: Session,
    *,
    product: ProductUpdate,
    icon_data: bytes | None = None,
    actor: UserORM | None = None,
    force: bool = False,
) -> ProductRead:
    """Update a product's fields and/or icon.

    Validates that the product exists and that the template belongs to the product.
    Raises NotFoundException if either is missing.
    Raises ValidationException if icon processing fails, or if the product is
    catalog-managed and the update touches anything the catalog owns.

    ``actor`` is the administrator performing the update, used only to attribute
    visibility changes and forced writes in the log; callers that cannot supply
    one still update normally.

    ``force`` is the break-glass override for a curated product. It leaves the
    catalog unchanged, so the next reconciliation re-asserts it and the drift
    self-heals.
    """
    if not (
        product_orm := session.exec(
            select(ProductORM).where(ProductORM.id == product.id, ProductORM.deleted_at == None)
        ).one_or_none()
    ):
        raise NotFoundException("Product not found")

    # Visibility is runtime state the catalog does not declare, so a change to
    # it alone stays available on a curated product — taking a product off the
    # storefront is often incident response and must not wait for a rollout.
    touches_catalog_state = icon_data is not None or any(
        value is not None
        for value in (
            product.name,
            product.template_id,
            product.description,
            product.category,
            product.replaces,
        )
    )
    if touches_catalog_state:
        _assert_mutable(product_orm, force=force, operation="update-product", actor=actor)

    if product.template_id:
        template_service.get_template(
            session, product_id=product.id, template_id=product.template_id
        )
        product_orm.template_id = product.template_id
    if product.name is not None:
        product_orm.name = product.name
    if product.description is not None:
        product_orm.description = product.description
    if product.category is not None:
        product_orm.category = product.category
    if product.replaces is not None:
        product_orm.replaces = product.replaces

    previous_visibility = product_orm.visibility
    if product.visibility is not None:
        product_orm.visibility = product.visibility

    if icon_data is not None:
        if len(icon_data) > MAX_ICON_SIZE:
            raise ValidationException(
                f"Image file too large. Maximum size is {MAX_ICON_SIZE // (1024 * 1024)}MB"
            )
        try:
            processed_icon = process_icon(icon_data)
            rel_icon_path = generate_icon_filename(processed_icon)
        except ValueError as e:
            raise ValidationException(str(e)) from e
        save_icon(processed_icon, rel_icon_path)
        product_orm.rel_icon_path = rel_icon_path

    session.add(product_orm)
    session.commit()
    session.refresh(product_orm)
    if product.visibility is not None and product.visibility != previous_visibility:
        logger.info(
            "Product visibility changed product_id=%s name=%s from=%s to=%s actor=%s",
            product_orm.id,
            product_orm.name,
            previous_visibility.value,
            product_orm.visibility.value,
            actor.email if actor else "unknown",
        )
    return ProductRead.model_validate(product_orm)


def upload_product_icon(session: Session, product_id: int, icon_data: bytes) -> ProductRead:
    """Upload and process an icon for a product.

    Args:
        session: Database session
        product_id: ID of the product
        icon_data: Raw icon image bytes

    Returns:
        Updated ProductRead with new icon_url

    Raises:
        NotFoundException: If product doesn't exist
        ValidationException: If icon processing fails, or the product is
            catalog-managed. This endpoint carries no force option; the
            break-glass path for a curated product's icon is a forced
            multipart ``update_product``.
    """
    if len(icon_data) > MAX_ICON_SIZE:
        raise ValidationException(
            f"Image file too large. Maximum size is {MAX_ICON_SIZE // (1024 * 1024)}MB"
        )

    if not (
        product_orm := session.exec(
            select(ProductORM).where(ProductORM.id == product_id, ProductORM.deleted_at == None)
        ).one_or_none()
    ):
        raise NotFoundException("Product not found")
    _assert_mutable(product_orm, operation="upload-icon")

    try:
        processed_icon = process_icon(icon_data)
        rel_icon_path = generate_icon_filename(processed_icon)
    except ValueError as e:
        raise ValidationException(str(e)) from e
    save_icon(processed_icon, rel_icon_path)

    product_orm.rel_icon_path = rel_icon_path
    session.add(product_orm)
    session.commit()
    session.refresh(product_orm)
    return ProductRead.model_validate(product_orm)


def get_product_icon_path(session: Session, product_id: int) -> str | None:
    """Get the relative icon path for a product.

    Args:
        session: Database session
        product_id: ID of the product

    Returns:
        Relative icon path or None if no icon

    Raises:
        NotFoundException: If product doesn't exist
    """
    if not (
        product_orm := session.exec(
            select(ProductORM).where(ProductORM.id == product_id, ProductORM.deleted_at == None)
        ).one_or_none()
    ):
        raise NotFoundException("Product not found")
    return product_orm.rel_icon_path
