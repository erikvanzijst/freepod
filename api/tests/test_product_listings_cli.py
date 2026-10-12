"""CLI parity for store-listing fields, listings and product releases."""

from __future__ import annotations

import yaml

from app.db import session_scope
from app.models import ProductORM, ProductReleaseORM


def _yaml(result):
    return yaml.safe_load(getattr(result, "stdout", result.output))


def test_create_and_update_listing_fields(cli_runner, tmp_path):
    runner, app = cli_runner
    features = tmp_path / "features.yaml"
    features.write_text(yaml.safe_dump([{"title": "Sync", "body": "Backup.", "icon": "sync"}]))
    links = tmp_path / "links.json"
    links.write_text('[{"label": "Site", "href": "https://immich.app", "kind": "website"}]')

    created = runner.invoke(
        app,
        ["create-product", "Immich", "Long description", "--tagline", "Kept private.",
         "--license", "AGPL-3.0", "--features-file", str(features), "--links-file", str(links)],
    )
    assert created.exit_code == 0, created.output
    product = _yaml(created)
    assert product["tagline"] == "Kept private."

    updated = runner.invoke(app, ["update-product", str(product["id"]), "--tagline", "Second."])
    assert updated.exit_code == 0, updated.output

    listing = _yaml(runner.invoke(app, ["get-product-listing", str(product["id"])]))
    assert _yaml(updated)["tagline"] == "Second."
    assert listing["license"] == "AGPL-3.0"
    assert listing["features"] == [{"title": "Sync", "body": "Backup.", "icon": "sync"}]
    assert listing["links"][0]["kind"] == "website"
    assert listing["screenshots"] == []


def test_invalid_link_file_is_rejected(cli_runner, tmp_path):
    runner, app = cli_runner
    links = tmp_path / "links.yaml"
    links.write_text(yaml.safe_dump([{"label": "Site", "href": "http://immich.app", "kind": "website"}]))

    result = runner.invoke(app, ["create-product", "Immich", "Desc", "--links-file", str(links)])

    assert result.exit_code == 1
    assert "https://" in result.output


def test_list_product_releases_matches_the_api(cli_runner, client):
    runner, app = cli_runner
    product = _yaml(runner.invoke(app, ["create-product", "Immich", "Desc", "--visibility", "public"]))
    with session_scope() as session:
        session.add(ProductReleaseORM(product_id=product["id"], version="3.3.0", notes="Old", position=1))
        session.add(ProductReleaseORM(product_id=product["id"], version="3.3.1", notes="New", position=0))
        session.commit()

    result = runner.invoke(app, ["list-product-releases", str(product["id"])])

    assert result.exit_code == 0, result.output
    assert _yaml(result) == client.get(f"/api/products/{product['id']}/releases").json()
    assert [r["version"] for r in _yaml(result)] == ["3.3.1", "3.3.0"]


def test_curated_product_listing_write_is_refused(cli_runner):
    runner, app = cli_runner
    product = _yaml(runner.invoke(app, ["create-product", "Immich", "Desc"]))
    with session_scope() as session:
        row = session.get(ProductORM, product["id"])
        row.curated, row.slug = True, "immich"
        session.add(row)
        session.commit()

    result = runner.invoke(app, ["update-product", str(product["id"]), "--license", "MIT"])

    assert result.exit_code == 1
    assert "products/catalog/immich/immich.yaml" in result.output
