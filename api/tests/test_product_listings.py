"""Store-listing reads and writes (product-listing-metadata, product-releases).

Screenshots, template versions and releases are written only by the catalog
reconciler, so these tests set them directly on the rows and exercise the
read side through the API.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import (
    DeploymentRead,
    ProductORM,
    ProductReleaseORM,
    ProductTemplateVersionORM,
    ProductTemplateVersionRead,
)
from tests.conftest import client  # noqa: F401

ANONYMOUS = {"X-Auth-Request-Email": ""}
SUMMARY_FIELDS = {"id", "name", "slug", "icon_url", "tagline", "template_id"}
LISTING_ONLY = {"license", "features", "links", "screenshots"}

FEATURE = {"title": "Sync", "body": "Backs up your phone.", "icon": "sync"}
LINK = {"label": "Website", "href": "https://immich.app", "kind": "website"}


def create_product(client, **payload) -> dict:
    resp = client.post(
        "/api/products", json={"name": "Immich", "visibility": "public", **payload}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def add_template(session, product_id: int, *, version: str | None, created_at: datetime, **kwargs):
    template = ProductTemplateVersionORM(
        product_id=product_id,
        chart_ref="oci://example/immich",
        chart_version=kwargs.pop("chart_version", "1.0.0"),
        system_values_json={},
        version=version,
        created_at=created_at,
        **kwargs,
    )
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


def make_canonical(session, product_id: int, template_id: int) -> None:
    product = session.get(ProductORM, product_id)
    product.template_id = template_id
    session.add(product)
    session.commit()


# ---------------------------------------------------------------------------
# Lean product reads and nested summaries
# ---------------------------------------------------------------------------


def test_product_list_carries_the_tagline_but_no_listing_content(client):
    create_product(client, tagline="Kept private.", license="AGPL-3.0", features=[FEATURE], links=[LINK])

    (product,) = client.get("/api/products", headers=ANONYMOUS).json()

    assert product["tagline"] == "Kept private."
    assert not LISTING_ONLY & product.keys()


def test_templates_nest_only_a_product_summary(client, db_session):
    product = create_product(client, tagline="Kept private.")
    add_template(db_session, product["id"], version="3.3.1", created_at=datetime.now(UTC))

    (template,) = client.get(f"/api/products/{product['id']}/templates").json()

    assert set(template["product"]) == SUMMARY_FIELDS
    assert template["product"]["tagline"] == "Kept private."
    assert template["version"] == "3.3.1"


def test_deployments_nest_templates_with_the_summary():
    desired = DeploymentRead.model_fields["desired_template"].annotation
    assert desired is ProductTemplateVersionRead
    assert set(ProductTemplateVersionRead.model_fields["product"].annotation.model_fields) == SUMMARY_FIELDS


# ---------------------------------------------------------------------------
# Listing endpoint
# ---------------------------------------------------------------------------


def test_anonymous_listing_returns_content_in_declared_order(client, db_session):
    product = create_product(
        client, license="AGPL-3.0", features=[FEATURE, {**FEATURE, "title": "Faces"}], links=[LINK]
    )
    row = db_session.get(ProductORM, product["id"])
    row.screenshots = [
        {"path": "screenshots/a.webp", "caption": "Timeline", "form": "desktop", "credit": None},
        {
            "path": "screenshots/b.webp",
            "caption": "Phone",
            "form": "mobile",
            "credit": {"text": "Immich · MIT", "href": "https://immich.app"},
        },
    ]
    db_session.add(row)
    db_session.commit()

    resp = client.get(f"/api/products/{product['id']}/listing", headers=ANONYMOUS)

    assert resp.status_code == 200, resp.text
    listing = resp.json()
    assert listing["license"] == "AGPL-3.0"
    assert [f["title"] for f in listing["features"]] == ["Sync", "Faces"]
    assert listing["links"] == [LINK]
    assert listing["screenshots"] == [
        {
            "thumbnail_url": "/api/static/screenshots/a-thumb.webp",
            "url": "/api/static/screenshots/a.webp",
            "caption": "Timeline",
            "form": "desktop",
            "credit": None,
        },
        {
            "thumbnail_url": "/api/static/screenshots/b-thumb.webp",
            "url": "/api/static/screenshots/b.webp",
            "caption": "Phone",
            "form": "mobile",
            "credit": {"text": "Immich · MIT", "href": "https://immich.app"},
        },
    ]


def test_empty_listing(client):
    product = create_product(client)

    listing = client.get(f"/api/products/{product['id']}/listing").json()

    assert listing["license"] is None
    assert (listing["features"], listing["links"], listing["screenshots"]) == ([], [], [])
    assert (listing["version"], listing["version_available_at"]) == (None, None)


def test_unknown_product_listing_is_not_found(client):
    assert client.get("/api/products/999999/listing").status_code == 404


def test_chart_bump_keeps_the_version_date(client, db_session):
    product = create_product(client)
    day1 = datetime(2026, 9, 1, tzinfo=UTC)
    add_template(db_session, product["id"], version="3.3.0", created_at=day1 - timedelta(days=30))
    add_template(db_session, product["id"], version="3.3.1", created_at=day1)
    bumped = add_template(
        db_session, product["id"], version="3.3.1", created_at=day1 + timedelta(days=4), chart_version="1.0.1"
    )
    make_canonical(db_session, product["id"], bumped.id)

    listing = client.get(f"/api/products/{product['id']}/listing").json()

    assert listing["version"] == "3.3.1"
    assert listing["version_available_at"].startswith("2026-09-01")


def test_unversioned_canonical_template_reports_no_version(client, db_session):
    product = create_product(client)
    template = add_template(db_session, product["id"], version=None, created_at=datetime.now(UTC))
    make_canonical(db_session, product["id"], template.id)

    listing = client.get(f"/api/products/{product['id']}/listing").json()

    assert (listing["version"], listing["version_available_at"]) == (None, None)


# ---------------------------------------------------------------------------
# Releases endpoint
# ---------------------------------------------------------------------------


def add_release(session, product_id: int, version: str, position: int) -> None:
    session.add(
        ProductReleaseORM(product_id=product_id, version=version, notes=f"Notes {version}", position=position)
    )
    session.commit()


def test_anonymous_releases_are_a_plain_list_newest_first(client, db_session):
    product = create_product(client)
    day1 = datetime(2026, 9, 1, tzinfo=UTC)
    add_template(db_session, product["id"], version="3.3.1", created_at=day1)
    add_template(db_session, product["id"], version="3.3.1", created_at=day1 + timedelta(days=4))
    add_release(db_session, product["id"], "3.3.0", 1)
    add_release(db_session, product["id"], "3.3.1", 0)

    resp = client.get(f"/api/products/{product['id']}/releases", headers=ANONYMOUS)

    assert resp.status_code == 200, resp.text
    releases = resp.json()
    assert isinstance(releases, list)
    assert [(r["version"], r["notes"]) for r in releases] == [
        ("3.3.1", "Notes 3.3.1"),
        ("3.3.0", "Notes 3.3.0"),
    ]
    assert releases[0]["available_at"].startswith("2026-09-01")
    # No template carries 3.3.0, which predates version tracking.
    assert releases[1]["available_at"] is None


def test_product_without_releases_lists_none(client):
    product = create_product(client)
    assert client.get(f"/api/products/{product['id']}/releases").json() == []


def test_releases_of_an_unknown_product_are_not_found(client):
    assert client.get("/api/products/999999/releases").status_code == 404


def test_releases_have_no_write_methods(client):
    product = create_product(client)
    path = f"/api/products/{product['id']}/releases"
    for method in ("post", "put", "delete"):
        assert getattr(client, method)(path).status_code == 405


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def test_create_stores_listing_fields(client, db_session):
    product = create_product(client, tagline="Kept private.", license="AGPL-3.0", features=[FEATURE], links=[LINK])

    row = db_session.get(ProductORM, product["id"])
    assert (row.tagline, row.license) == ("Kept private.", "AGPL-3.0")
    assert row.features == [FEATURE] and row.links == [LINK]


def test_update_changes_only_the_given_listing_field(client):
    product = create_product(client, tagline="First.", license="MIT", features=[FEATURE])

    resp = client.put(f"/api/products/{product['id']}", json={"tagline": "Second."})
    assert resp.status_code == 200, resp.text

    listing = client.get(f"/api/products/{product['id']}/listing").json()
    assert resp.json()["tagline"] == "Second."
    assert listing["license"] == "MIT" and listing["features"] == [FEATURE]


def test_insecure_link_is_rejected(client):
    resp = client.post(
        "/api/products",
        json={"name": "Immich", "links": [{**LINK, "href": "http://immich.app"}]},
    )
    assert resp.status_code == 422
    assert "https://" in resp.text


def test_unknown_link_kind_is_rejected(client):
    resp = client.post("/api/products", json={"name": "Immich", "links": [{**LINK, "kind": "blog"}]})
    assert resp.status_code == 422


def test_screenshots_cannot_be_written_through_the_api(client):
    resp = client.post("/api/products", json={"name": "Immich", "screenshots": []})
    assert resp.status_code == 422
    product = create_product(client)
    resp = client.put(f"/api/products/{product['id']}", json={"screenshots": []})
    assert resp.status_code == 422


def test_curated_product_rejects_listing_writes(client, db_session):
    product = create_product(client)
    row = db_session.get(ProductORM, product["id"])
    row.curated, row.slug = True, "immich"
    db_session.add(row)
    db_session.commit()

    resp = client.put(f"/api/products/{product['id']}", json={"features": [FEATURE]})

    assert resp.status_code == 400
    assert "products/catalog/immich/immich.yaml" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------


def test_static_files_are_cached_immutably(client, tmp_path):
    from app.config import get_settings

    icon = get_settings().static_path / "icons" / "cache-header-test.png"
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_bytes(b"\x89PNG\r\n")
    try:
        resp = client.get("/api/static/icons/cache-header-test.png")
    finally:
        icon.unlink()

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
