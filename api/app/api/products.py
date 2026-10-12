from __future__ import annotations

import json
from typing import TypeVar

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Path,
    Query,
    UploadFile as FastAPIUploadFile,
    status,
)
from fastapi.requests import Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError as PydanticValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from sqlmodel import SQLModel, Session

from app.db import get_session
from app.deps import get_current_user, get_optional_user, require_admin
from app.models import (
    ProductListingRead,
    ProductReleaseRead,
    ProductRead,
    ProductCreate,
    ProductTemplateVersionRead,
    ProductTemplateVersionCreate,
    ProductUpdate,
    UserORM,
)
from app.services import templates as template_service, products as product_service
from app.services import listings as listing_service

T = TypeVar("T", bound=SQLModel)

router = APIRouter(prefix="/products", tags=["products"])

# The break-glass override for curated products. It is a *query* parameter
# rather than a body field because the delete endpoints are 204-with-no-body and
# product update is multipart: force is a property of the request, not of the
# product, and must not appear on the create/update/read schemas.
FORCE_DESCRIPTION = (
    "Break-glass override allowing this modification on a catalog-managed "
    "(curated) product. The catalog is left unchanged, so the next "
    "reconciliation re-asserts it and the drift self-heals."
)
FORCE_DELETE_DESCRIPTION = (
    "Accepted for symmetry with the modifying endpoints, but deletion of a "
    "curated product or its templates is never overridable: the next "
    "reconciliation would simply recreate it. Remove the product's catalog "
    "file instead."
)
CURATED_400 = {
    "description": (
        "The product is managed by the catalog. The error names the catalog "
        "file to edit instead."
    )
}


async def parse_product_request(request: Request, model_cls: type[T] = ProductCreate) -> tuple[T, bytes | None]:
    """Parse a product create/update request body into a model plus optional icon bytes.

    Supports two request content types:

    - **application/json** (or any non-multipart body): the whole body is the
      product JSON, validated into ``model_cls``. An empty body validates an
      empty model. No icon is returned.
    - **multipart/form-data**: a required ``payload`` form part carries the
      product JSON (validated into ``model_cls``) and an optional ``icon`` form
      part carries an image file whose raw bytes are returned alongside the model.

    Returns a ``(model, icon_bytes | None)`` tuple.

    Raises:
        HTTPException 422: the multipart ``payload`` part is missing or is not
            valid JSON, the ``icon`` part is present but is not a file upload,
            or a non-multipart body is not valid JSON.
        HTTPException 400: the ``icon`` file could not be read.
    """
    content_type = request.headers.get("content-type", "")
    body = await request.body()

    if "multipart/form-data" in content_type:
        form = await request.form()
        payload_data = form.get("payload")

        if payload_data is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Product JSON payload is required",
            )

        try:
            payload_dict = json.loads(str(payload_data))
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid product JSON: {e}",
            ) from e

        try:
            payload = model_cls(**payload_dict)
        except PydanticValidationError as e:
            # Includes an attempt to set a reconciler-owned field such as
            # `slug` or `curated`, which the product schemas forbid.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid product payload: {e}",
            ) from e

        icon_data: bytes | None = None
        icon_file = form.get("icon")
        if icon_file is not None and not isinstance(icon_file, UploadFile):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Icon must be a file upload",
            )
        if isinstance(icon_file, UploadFile):
            try:
                icon_data = await icon_file.read()
            except OSError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to read icon upload: {exc}",
                ) from exc

        return payload, icon_data
    else:
        try:
            payload_dict = json.loads(body) if body else {}
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid JSON body",
            ) from e
        try:
            payload = model_cls.model_validate(payload_dict)
        except PydanticValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid product payload: {e}",
            ) from e
        return payload, None


@router.post(
    "",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product",
    response_description="The newly created product, including its marketing metadata and icon URL (if an icon was supplied).",
    responses={
        400: {"description": "The uploaded icon file could not be read."},
        403: {"description": "The caller lacks administrator privileges."},
        409: {"description": "A product with this name already exists."},
        422: {"description": "Malformed request body: missing/invalid `payload` JSON, or the `icon` part is not a file upload."},
    },
)
async def create_product(
    request: Request,
    current_user: UserORM = Depends(require_admin),
    session: Session = Depends(get_session),
) -> ProductRead:
    """Create a new product, optionally with an icon.

    ## Authorization
    Requires administrator privileges. Other callers receive `403 Forbidden`.

    ## Request body
    Accepts either of two content types:

    - **application/json** — the body is the product JSON (`ProductCreate`):
      `name` (required), and optional `description`, `template_id`,
      `visibility`, and the marketing-metadata fields `category` and
      `replaces`. No icon.
    - **multipart/form-data** — a required `payload` part holding the same
      product JSON, plus an optional `icon` image file. When an icon is
      supplied, the returned product carries its `icon_url`.

    ## Behavior
    - Product names are unique; a duplicate name yields a 409 conflict.
    - `visibility` defaults to `admin`, so a product being onboarded is not
      offered to end users until it is explicitly published.
    - When an `icon` is supplied it is validated against the maximum size; the
      product's icon is then reachable through
      `GET /api/products/{product_id}/icon`.

    ## Errors
    - **403 Forbidden** — the caller is not an administrator.
    - **409 Conflict** — a product with this name already exists.
    - **400 Bad Request** — the multipart `icon` file could not be read, or the
      icon is too large / fails image processing.
    - **422 Unprocessable Content** — the multipart `payload` is missing or is
      invalid JSON, the `icon` part is not a file upload, or a non-multipart
      body is not valid JSON.
    """
    payload, icon_data = await parse_product_request(request)
    # Wrap the blocking DB/file-I/O service call in run_in_threadpool so it
    # doesn't block the event loop. This endpoint must be async def for the
    # multipart form parsing above, but without this wrapper the sync service
    # call would stall all other concurrent request handling.
    product = await run_in_threadpool(product_service.create_product, session, payload, icon_data)
    return product


@router.get(
    "",
    response_model=list[ProductRead],
    summary="List products",
    response_description="All products the caller may see, with their marketing metadata and icon URLs.",
)
def list_products(
    current_user: UserORM | None = Depends(get_optional_user),
    session: Session = Depends(get_session),
) -> list[ProductRead]:
    """List the products visible to the caller.

    ## Authorization
    Public — no authentication required.

    ## Behavior
    Anonymous visitors and regular users get the end-user listing: only
    non-deleted products whose `visibility` is `public` or `unlisted`.
    Administrators get the administrative listing, which additionally includes
    products whose `visibility` is `admin`. Soft-deleted products are excluded
    either way. Each product reports its `visibility`, so a storefront can
    leave `unlisted` products out.

    Each product includes its marketing metadata (`category`, `replaces`,
    `tagline`) and an `icon_url` when an icon is set. Store-listing content
    (license, features, links, screenshots) is served by
    `GET /api/products/{product_id}/listing` instead.
    """
    return product_service.list_products(
        session, include_hidden=bool(current_user and current_user.is_admin)
    )


@router.get(
    "/{product_id}",
    response_model=ProductRead,
    summary="Get a product",
    response_description="The product's public metadata, including marketing fields and icon URL.",
    responses={404: {"description": "No product exists with this id."}},
)
def get_product(
    product_id: int = Path(..., description="ID of the product to retrieve."),
    session: Session = Depends(get_session),
) -> ProductRead:
    """Fetch a single product by id.

    ## Authorization
    Public — no authentication required.

    ## Parameters
    - **product_id** — the product to retrieve.

    ## Behavior
    The response includes the marketing metadata (`category`, `replaces`) and
    an `icon_url` when set.

    ## Errors
    - **404 Not Found** — no product with this id exists.
    """
    return product_service.get_product(session, product_id=product_id)


@router.get(
    "/{product_id}/listing",
    response_model=ProductListingRead,
    summary="Get a product's store listing",
    response_description="The product's license, features, links, screenshots and current version.",
    responses={404: {"description": "No product exists with this id."}},
)
def get_product_listing(
    product_id: int = Path(..., description="ID of the product whose listing to retrieve."),
    session: Session = Depends(get_session),
) -> ProductListingRead:
    """Fetch the store-listing content of a product, for its public app page.

    ## Authorization
    Public — no authentication required.

    ## Behavior
    Returns `license`, `features`, `links` and `screenshots` in their declared
    order, each screenshot with a `thumbnail_url` for in-page display, a full-size
    `url`, its `caption`, `form` and optional `credit`. `version` is the
    canonical template's upstream version and `version_available_at` the moment
    that version first became available on Freepod (its oldest template row);
    both are null when the version is unknown. Product reads carry none of this
    content, so lists and nested products stay small.

    ## Errors
    - **404 Not Found** — no product with this id exists.
    """
    return listing_service.get_listing(session, product_id=product_id)


@router.get(
    "/{product_id}/releases",
    response_model=list[ProductReleaseRead],
    summary="List a product's releases",
    response_description="The product's release notes, newest first.",
    responses={404: {"description": "No product exists with this id."}},
)
def list_product_releases(
    product_id: int = Path(..., description="ID of the product whose releases to list."),
    session: Session = Depends(get_session),
) -> list[ProductReleaseRead]:
    """List a product's user-facing release notes, newest first.

    ## Authorization
    Public — no authentication required.

    ## Behavior
    A plain, unpaginated array with one entry per version Freepod onboarded:
    `version`, Markdown `notes`, and `available_at`, the moment that version
    first became available on Freepod, or null when no template carries it.
    Releases come from the product's catalog folder and have no write endpoint.

    ## Errors
    - **404 Not Found** — no product with this id exists.
    """
    return listing_service.list_releases(session, product_id=product_id)


@router.put(
    "/{product_id}",
    response_model=ProductRead,
    summary="Update a product",
    response_description="The updated product with its current marketing metadata and icon URL.",
    responses={
        400: {
            "description": (
                "The uploaded icon could not be read, is too large, or failed image "
                "processing; or the product is managed by the catalog and `force` was "
                "not supplied. A catalog refusal names the catalog file to edit instead."
            )
        },
        403: {"description": "The caller lacks administrator privileges."},
        404: {"description": "No product exists with this id, or the referenced template does not belong to this product."},
        422: {"description": "Malformed request body: missing/invalid `payload` JSON, an unknown field such as `slug` or `curated`, or the `icon` part is not a file upload."},
    },
)
async def update_product(
    product_id: int = Path(..., description="ID of the product to update. Overrides any `id` in the payload."),
    force: bool = Query(False, description=FORCE_DESCRIPTION),
    request: Request = None,
    current_user: UserORM = Depends(require_admin),
    session: Session = Depends(get_session),
) -> ProductRead:
    """Partially update a product's fields and/or replace its icon.

    ## Authorization
    Requires administrator privileges. Other callers receive `403 Forbidden`.

    ## Request body
    Accepts either of two content types (same shapes as create):

    - **application/json** — the body is the product JSON (`ProductUpdate`).
      Every field is optional; only the provided fields are changed, leaving
      the rest untouched (partial update). Fields: `name`, `description`,
      `template_id`, `category`, `replaces`, `visibility`.
    - **multipart/form-data** — a required `payload` part holding the same
      `ProductUpdate` JSON, plus an optional `icon` image file that replaces
      the product's existing icon.

    ## Parameters
    - **product_id** — the product to update. The server forces the payload's
      `id` to this path value, so any `id` in the body is ignored.

    ## Behavior
    - Only fields present in the payload are applied; omitted fields are
      preserved.
    - Setting `template_id` selects the product's current template version; the
      referenced template must belong to this product or a 404 is raised.
    - Setting `visibility` to `public` offers the product in the end-user
      product list; `unlisted` offers it there too but marks it to be left
      out of the storefront; `admin` withdraws it, leaving existing
      deployments untouched.
    - A supplied `icon` replaces the product's existing icon; the returned
      product carries the new `icon_url`.
    - For a **curated** (catalog-managed) product every field except
      `visibility` is owned by `products/catalog/<slug>/<slug>.yaml` and is refused
      with a 400 unless `?force=true` is supplied. `visibility` is runtime
      state and stays editable without `force`. `slug` and `curated`
      themselves are written only by the reconciler and are not accepted here.

    ## Errors
    - **404 Not Found** — the product does not exist, or the referenced
      `template_id` does not belong to this product.
    - **403 Forbidden** — the caller is not an administrator.
    - **400 Bad Request** — the multipart `icon` file could not be read, is too
      large, or fails image processing; or the product is catalog-managed and
      `force` was not supplied.
    - **422 Unprocessable Content** — the multipart `payload` is missing or is
      invalid JSON, carries an unknown field, the `icon` part is not a file
      upload, or a non-multipart body is not valid JSON.
    """
    payload, icon_data = await parse_product_request(request, ProductUpdate)
    payload.id = product_id
    return await run_in_threadpool(
        product_service.update_product,
        session,
        product=payload,
        icon_data=icon_data,
        actor=current_user,
        force=force,
    )


@router.delete(
    "/{product_id}",
    status_code=204,
    summary="Delete a product",
    response_description="The product was deleted; no content is returned.",
    responses={
        204: {"description": "The product was deleted."},
        400: CURATED_400,
        403: {"description": "The caller lacks administrator privileges."},
        404: {"description": "No product exists with this id."},
    },
)
def delete_product_endpoint(
    product_id: int = Path(..., description="ID of the product to delete."),
    force: bool = Query(False, description=FORCE_DELETE_DESCRIPTION),
    current_user: UserORM = Depends(require_admin),
    session: Session = Depends(get_session),
) -> None:
    """Delete a product.

    ## Authorization
    Requires administrator privileges. Other callers receive `403 Forbidden`.

    ## Parameters
    - **product_id** — the product to delete.

    ## Behavior
    Once deleted, the product is treated as absent by subsequent reads, and its
    name is freed for reuse.

    A **curated** product cannot be deleted, with or without `force`: the next
    reconciliation would recreate it under a new id while existing deployments
    kept referencing the old row. Remove its `products/catalog/<slug>/<slug>.yaml`
    file, let the rollout release the product, then delete it normally.

    ## Errors
    - **404 Not Found** — no product exists with this id.
    - **403 Forbidden** — the caller is not an administrator.
    - **400 Bad Request** — the product is managed by the catalog.
    """
    product_service.delete_product(
        session, product_id=product_id, force=force, actor=current_user
    )


@router.post(
    "/{product_id}/templates",
    response_model=ProductTemplateVersionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a template version",
    response_description="The newly created template version for the product.",
    responses={
        400: {
            "description": (
                "`values_schema_json` is not a valid JSON Schema, or the product is "
                "managed by the catalog and `force` was not supplied."
            )
        },
        403: {"description": "The caller lacks administrator privileges."},
        404: {"description": "The parent product does not exist."},
        409: {"description": "A template for this product version already exists."},
    },
)
def create_template(
    product_id: int = Path(..., description="ID of the product to attach the template to. Overrides any `product_id` in the payload."),
    payload: ProductTemplateVersionCreate = ...,
    force: bool = Query(False, description=FORCE_DESCRIPTION),
    current_user: UserORM = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Create a new template version for a product.

    ## Authorization
    Requires administrator privileges. Other callers receive `403 Forbidden`.

    ## Request body
    A `ProductTemplateVersionCreate` JSON body describing the chart binding and
    template payload: `chart_ref`, `chart_version`, and the optional
    `chart_digest`, `system_values_json` (default values for the template),
    and `values_schema_json` (JSON Schema for the user values form).

    ## Parameters
    - **product_id** — the parent product. The server forces the payload's
      `product_id` to this path value, so any `product_id` in the body is
      ignored.

    ## Behavior
    The parent product must exist or a 404 is raised. When `values_schema_json`
    is supplied it is meta-validated as a JSON Schema document (the dialect is
    taken from its own `$schema` key); a malformed schema is rejected with a 400
    rather than being stored and failing later for a tenant. Creating a template
    does not by itself make it the product's current template version; that is
    set via the product's `template_id`.

    A **curated** product's templates come from its catalog file, so creation is
    refused with a 400 unless `?force=true` is supplied. A forced row leaves
    `catalog_commit` null, so hand-made drift stays distinguishable from
    catalog-produced history and is re-asserted on the next rollout.

    ## Errors
    - **400 Bad Request** — `values_schema_json` is not a valid JSON Schema, or
      the product is managed by the catalog and `force` was not supplied.
    - **404 Not Found** — the parent product does not exist.
    - **403 Forbidden** — the caller is not an administrator.
    - **409 Conflict** — a template for this product version already exists.
    """
    payload.product_id = product_id
    return template_service.create_template(
        session, payload, force=force, actor=current_user
    )


@router.get(
    "/{product_id}/templates",
    response_model=list[ProductTemplateVersionRead],
    summary="List a product's template versions",
    response_description="All template versions for the product.",
)
def list_templates(
    product_id: int = Path(..., description="ID of the product whose templates to list."),
    session: Session = Depends(get_session),
) -> list[ProductTemplateVersionRead]:
    """List all template versions for a product.

    ## Authorization
    Public — no authentication required.

    ## Parameters
    - **product_id** — the product whose templates to list.

    ## Behavior
    An unknown `product_id` simply yields an empty array (no 404). Each template
    includes its chart binding, `system_values_json`, and `values_schema_json`.
    """
    return template_service.list_templates(session, product_id=product_id)


@router.get(
    "/{product_id}/templates/{template_id}",
    response_model=ProductTemplateVersionRead,
    summary="Get a template version",
    response_description="The requested template version, including its chart binding, system values, and values schema.",
    responses={404: {"description": "No matching template exists for this product."}},
)
def get_template(
    product_id: int = Path(..., description="ID of the product the template belongs to."),
    template_id: int = Path(..., description="ID of the template version to retrieve."),
    session: Session = Depends(get_session),
) -> ProductTemplateVersionRead:
    """Fetch a single template version by id, scoped to its product.

    ## Authorization
    Public — no authentication required.

    ## Parameters
    - **product_id** — the product the template must belong to.
    - **template_id** — the template version to retrieve.

    ## Behavior
    The template must exist and belong to the given product; otherwise a 404 is
    raised. The response includes `system_values_json` and `values_schema_json`.

    ## Errors
    - **404 Not Found** — no template with this id exists for this product (or
      it belongs to a different product).
    """
    return template_service.get_template(session, product_id=product_id, template_id=template_id)


@router.delete(
    "/{product_id}/templates/{template_id}",
    status_code=204,
    summary="Delete a template version",
    response_description="The template version was deleted; no content is returned.",
    responses={
        204: {"description": "The template version was deleted."},
        400: CURATED_400,
        403: {"description": "The caller lacks administrator privileges."},
        404: {"description": "No matching template exists for this product."},
    },
)
def delete_template_endpoint(
    product_id: int = Path(..., description="ID of the product the template belongs to."),
    template_id: int = Path(..., description="ID of the template version to delete."),
    force: bool = Query(False, description=FORCE_DELETE_DESCRIPTION),
    current_user: UserORM = Depends(require_admin),
    session: Session = Depends(get_session),
) -> None:
    """Delete a template version.

    ## Authorization
    Requires administrator privileges. Other callers receive `403 Forbidden`.

    ## Parameters
    - **product_id** — the product the template must belong to.
    - **template_id** — the template version to delete.

    ## Behavior
    The template must belong to the given product. Once deleted, it is treated
    as absent by subsequent reads.

    Templates of a **curated** product cannot be deleted, with or without
    `force`: the reconciler reinserts any template whose spec the catalog still
    declares. Remove the product's catalog file first.

    ## Errors
    - **404 Not Found** — no template with this id belongs to this product.
    - **403 Forbidden** — the caller is not an administrator.
    - **400 Bad Request** — the product is managed by the catalog.
    """
    template_service.delete_template(
        session,
        product_id=product_id,
        template_id=template_id,
        force=force,
        actor=current_user,
    )


@router.put(
    "/{product_id}/icon",
    response_model=ProductRead,
    summary="Upload or replace a product icon",
    response_description="The updated product with its new `icon_url`.",
    responses={
        400: {"description": "The icon is too large or fails image processing."},
        403: {"description": "The caller lacks administrator privileges."},
        404: {"description": "No product exists with this id."},
    },
)
def upload_icon(
    product_id: int = Path(..., description="ID of the product whose icon to set."),
    icon: FastAPIUploadFile = File(..., description="Image file to store as the product's icon. Replaces any existing icon."),
    current_user: UserORM = Depends(require_admin),
    session: Session = Depends(get_session),
) -> ProductRead:
    """Upload or replace a product's icon via a multipart file upload.

    ## Authorization
    Requires administrator privileges. Other callers receive `403 Forbidden`.

    ## Parameters
    - **product_id** — the product whose icon to set.
    - **icon** — the multipart image file to store; it replaces any existing
      icon for the product.

    ## Behavior
    The uploaded image is validated against the maximum size; the returned
    product carries the new `icon_url`, and the icon is reachable through
    `GET /api/products/{product_id}/icon`.

    ## Errors
    - **404 Not Found** — no product exists with this id.
    - **403 Forbidden** — the caller is not an administrator.
    - **400 Bad Request** — the icon exceeds the maximum size or fails image
      processing.
    """
    icon_data = icon.file.read()
    return product_service.upload_product_icon(session, product_id, icon_data)


@router.get(
    "/{product_id}/icon",
    summary="Redirect to a product's icon",
    response_description="A 302 redirect to the product icon's static URL.",
    responses={
        302: {"description": "Redirect to the icon's static URL under `/api/static`."},
        404: {"description": "The product has no icon, or no product exists with this id."},
    },
)
def get_icon_redirect(
    product_id: int = Path(..., description="ID of the product whose icon to fetch."),
    session: Session = Depends(get_session),
):
    """Redirect to a product's icon image.

    ## Authorization
    Public — no authentication required.

    ## Parameters
    - **product_id** — the product whose icon to fetch.

    ## Behavior
    Issues a **302** redirect to the icon's URL (served under `/api/static`). A
    404 is returned when the product has no icon, or when no product exists with
    this id.

    ## Errors
    - **404 Not Found** — the product has no icon, or no product exists with
      this id.
    """
    rel_path = product_service.get_product_icon_path(session, product_id)
    if rel_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Icon not found")
    from app.config import get_static_url_base

    return RedirectResponse(
        url=f"{get_static_url_base()}/{rel_path}", status_code=status.HTTP_302_FOUND
    )
