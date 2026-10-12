"""Store-listing reads: a product's listing content and its releases.

Kept apart from product reads so that product lists and nested products never
carry listing content (app-store-listings design D11). Each read is a fixed
number of queries, whatever the size of the listing.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import (
    ProductListingRead,
    ProductORM,
    ProductReleaseORM,
    ProductReleaseRead,
    ProductTemplateVersionORM,
    ScreenshotRead,
    StoredScreenshot,
    screenshot_thumbnail_path,
)
from app.services.errors import NotFoundException


def _product(session: Session, product_id: int) -> ProductORM:
    product = session.exec(
        select(ProductORM).where(ProductORM.id == product_id, ProductORM.deleted_at == None)  # noqa: E711
    ).one_or_none()
    if product is None:
        raise NotFoundException("Product not found")
    return product


def _available_at(session: Session, product_id: int, version: str) -> datetime | None:
    """When ``version`` first became available: its oldest template row."""
    return session.exec(
        select(func.min(ProductTemplateVersionORM.created_at)).where(
            ProductTemplateVersionORM.product_id == product_id,
            ProductTemplateVersionORM.version == version,
            ProductTemplateVersionORM.deleted_at == None,  # noqa: E711
        )
    ).one()


def get_listing(session: Session, *, product_id: int) -> ProductListingRead:
    from app.config import get_static_url_base

    product = _product(session, product_id)
    base = get_static_url_base()
    screenshots = []
    for raw in product.screenshots or []:
        stored = StoredScreenshot.model_validate(raw)
        screenshots.append(
            ScreenshotRead(
                thumbnail_url=f"{base}/{screenshot_thumbnail_path(stored.path)}",
                url=f"{base}/{stored.path}",
                caption=stored.caption,
                form=stored.form,
                credit=stored.credit,
            )
        )
    # The canonical template is joined onto the product row, so this costs no query.
    version = product.template.version if product.template is not None else None
    return ProductListingRead(
        product_id=product.id,
        license=product.license,
        features=product.features or [],
        links=product.links or [],
        screenshots=screenshots,
        version=version,
        version_available_at=_available_at(session, product.id, version) if version else None,
    )


def list_releases(session: Session, *, product_id: int) -> list[ProductReleaseRead]:
    """A product's releases, newest first, each with when its version arrived."""
    _product(session, product_id)
    first_seen = (
        select(
            ProductTemplateVersionORM.version.label("version"),
            func.min(ProductTemplateVersionORM.created_at).label("available_at"),
        )
        .where(
            ProductTemplateVersionORM.product_id == product_id,
            ProductTemplateVersionORM.deleted_at == None,  # noqa: E711
            ProductTemplateVersionORM.version != None,  # noqa: E711
        )
        .group_by(ProductTemplateVersionORM.version)
        .subquery()
    )
    rows = session.exec(
        select(ProductReleaseORM.version, ProductReleaseORM.notes, first_seen.c.available_at)
        .join(first_seen, first_seen.c.version == ProductReleaseORM.version, isouter=True)
        .where(ProductReleaseORM.product_id == product_id)
        .order_by(ProductReleaseORM.position)
    ).all()
    return [
        ProductReleaseRead(version=version, notes=notes, available_at=available_at)
        for version, notes, available_at in rows
    ]
