"""Write guards for catalog-managed (curated) products.

Curation is written only by the reconciler, so these tests set `curated`
directly on the ORM — exactly the state a rolled-out catalog file produces —
and then exercise the guard through both the REST API and the CLI. The two
surfaces share one service-layer guard, so the point of the CLI cases is parity:
`caelus update-product` must not be a back door around the API's refusal.
"""

from __future__ import annotations

import yaml
from sqlmodel import select

from app.db import session_scope
from app.models import ProductORM, ProductTemplateVersionORM, UserORM
from tests.conftest import client, create_free_plan_template, create_user  # noqa: F401

CLI_USER_EMAIL = "cli-test@example.com"

TEMPLATE_PAYLOAD = {
    "chart_ref": "oci://example/chart",
    "chart_version": "1.0.0",
    "system_values_json": {"image": {"tag": "v1"}},
}


# ---------------------------------------------------------------------------
# REST helpers
# ---------------------------------------------------------------------------


def _create_product(client, name: str, **payload) -> dict:
    resp = client.post("/api/products", json={"name": name, "description": "desc", **payload})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_template(client, product_id: int, **overrides) -> dict:
    resp = client.post(
        f"/api/products/{product_id}/templates", json={**TEMPLATE_PAYLOAD, **overrides}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _curate(db_session, product_id: int, slug: str) -> None:
    """Put a product in the state a rolled-out catalog file leaves it in."""
    product = db_session.get(ProductORM, product_id)
    product.slug = slug
    product.curated = True
    db_session.add(product)
    db_session.commit()


def _release(db_session, product_id: int) -> None:
    """The state the reconciler leaves after its catalog file is removed."""
    product = db_session.get(ProductORM, product_id)
    product.slug = None
    product.curated = False
    db_session.add(product)
    db_session.commit()


# ---------------------------------------------------------------------------
# Columns and defaults
# ---------------------------------------------------------------------------


def test_new_products_are_not_curated(client):
    product = _create_product(client, "fresh")
    assert product["curated"] is False
    assert product["slug"] is None


def test_curation_cannot_be_set_out_of_band(client):
    """`slug` and `curated` are reconciler-owned: setting them is rejected."""
    resp = client.post(
        "/api/products", json={"name": "sneaky", "description": "d", "curated": True}
    )
    assert resp.status_code == 422, resp.text

    product = _create_product(client, "honest")
    resp = client.put(f"/api/products/{product['id']}", json={"slug": "honest"})
    assert resp.status_code == 422, resp.text


def test_read_exposes_slug_and_curated(client, db_session):
    product = _create_product(client, "immich")
    _curate(db_session, product["id"], "immich")

    body = client.get(f"/api/products/{product['id']}").json()
    assert body["curated"] is True
    assert body["slug"] == "immich"


# ---------------------------------------------------------------------------
# The guard: modifications
# ---------------------------------------------------------------------------


def test_rest_update_of_a_curated_product_is_rejected(client, db_session):
    product = _create_product(client, "immich")
    _curate(db_session, product["id"], "immich")

    resp = client.put(f"/api/products/{product['id']}", json={"description": "edited"})
    assert resp.status_code == 400
    # The refusal names the file to edit instead of merely stating the rule.
    assert "products/catalog/immich/immich.yaml" in resp.json()["detail"]

    assert client.get(f"/api/products/{product['id']}").json()["description"] == "desc"


def test_rest_template_creation_on_a_curated_product_is_rejected(client, db_session):
    product = _create_product(client, "immich")
    _curate(db_session, product["id"], "immich")

    resp = client.post(f"/api/products/{product['id']}/templates", json=TEMPLATE_PAYLOAD)
    assert resp.status_code == 400
    assert "products/catalog/immich/immich.yaml" in resp.json()["detail"]


def test_rest_icon_upload_on_a_curated_product_is_rejected(client, db_session):
    """The icon is catalog state too, so the dedicated icon endpoint is guarded."""
    product = _create_product(client, "immich")
    _curate(db_session, product["id"], "immich")

    resp = client.put(
        f"/api/products/{product['id']}/icon",
        files={"icon": ("icon.png", b"not-an-image", "image/png")},
    )
    assert resp.status_code == 400
    assert "products/catalog/immich/immich.yaml" in resp.json()["detail"]


def test_non_curated_products_are_unaffected(client):
    product = _create_product(client, "scratch")

    resp = client.put(f"/api/products/{product['id']}", json={"description": "edited"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "edited"

    assert (
        client.post(f"/api/products/{product['id']}/templates", json=TEMPLATE_PAYLOAD).status_code
        == 201
    )


def test_visibility_is_exempt_from_the_guard(client, db_session):
    """The catalog owns what a product is; the database owns whether it is offered."""
    product = _create_product(client, "immich")
    _curate(db_session, product["id"], "immich")

    resp = client.put(f"/api/products/{product['id']}", json={"visibility": "public"})
    assert resp.status_code == 200
    assert resp.json()["visibility"] == "public"


def test_visibility_combined_with_a_catalog_field_is_still_refused(client, db_session):
    """The exemption is for visibility *alone*, not for smuggling a name change."""
    product = _create_product(client, "immich")
    _curate(db_session, product["id"], "immich")

    resp = client.put(
        f"/api/products/{product['id']}", json={"visibility": "public", "name": "renamed"}
    )
    assert resp.status_code == 400
    assert client.get(f"/api/products/{product['id']}").json()["name"] == "immich"


# ---------------------------------------------------------------------------
# Break-glass
# ---------------------------------------------------------------------------


def test_forced_update_succeeds(client, db_session):
    product = _create_product(client, "immich")
    _curate(db_session, product["id"], "immich")

    resp = client.put(
        f"/api/products/{product['id']}?force=true", json={"description": "hotfix"}
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "hotfix"


def test_forced_template_creation_leaves_catalog_commit_null(client, db_session):
    """Hand-made rows stay distinguishable from catalog-produced ones."""
    product = _create_product(client, "immich")
    _curate(db_session, product["id"], "immich")

    resp = client.post(
        f"/api/products/{product['id']}/templates?force=true", json=TEMPLATE_PAYLOAD
    )
    assert resp.status_code == 201

    template = db_session.get(ProductTemplateVersionORM, resp.json()["id"])
    assert template.catalog_commit is None


def test_force_is_a_query_parameter_not_resource_state(client):
    """Force describes the request, so it must not reach the product schemas."""
    from app.models import ProductCreate, ProductRead, ProductUpdate

    for model in (ProductCreate, ProductRead, ProductUpdate):
        assert "force" not in model.model_fields, model.__name__

    paths = client.get("/api/openapi.json").json()["paths"]
    guarded = (
        ("/api/products/{product_id}", "put"),
        ("/api/products/{product_id}", "delete"),
        ("/api/products/{product_id}/templates", "post"),
        ("/api/products/{product_id}/templates/{template_id}", "delete"),
    )
    for path, method in guarded:
        operation = paths[path][method]
        force = [p for p in operation["parameters"] if p["name"] == "force"]
        assert force, (path, method)
        assert force[0]["in"] == "query", (path, method)
        assert force[0]["schema"]["default"] is False, (path, method)
        # The documented 400 tells an operator what a refusal means.
        assert "400" in operation["responses"], (path, method)


def test_forced_write_is_logged_with_the_acting_user(client, db_session, caplog):
    product = _create_product(client, "immich")
    _curate(db_session, product["id"], "immich")

    with caplog.at_level("WARNING", logger="app.services.products"):
        client.put(f"/api/products/{product['id']}?force=true", json={"description": "hotfix"})

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Forced write" in message and "slug=immich" in message and "test@example.com" in message
        for message in messages
    ), messages


# ---------------------------------------------------------------------------
# Deletion is never forceable
# ---------------------------------------------------------------------------


def test_force_deleting_a_curated_product_is_refused(client, db_session):
    product = _create_product(client, "immich")
    _curate(db_session, product["id"], "immich")

    for url in (f"/api/products/{product['id']}", f"/api/products/{product['id']}?force=true"):
        resp = client.delete(url)
        assert resp.status_code == 400, url
        # The refusal points at the supported path rather than the override.
        assert "products/catalog/immich/immich.yaml" in resp.json()["detail"]

    assert client.get(f"/api/products/{product['id']}").status_code == 200


def test_force_deleting_a_curated_products_template_is_refused(client, db_session):
    product = _create_product(client, "immich")
    template = _create_template(client, product["id"])
    _curate(db_session, product["id"], "immich")

    resp = client.delete(
        f"/api/products/{product['id']}/templates/{template['id']}?force=true"
    )
    assert resp.status_code == 400
    assert "products/catalog/immich/immich.yaml" in resp.json()["detail"]

    assert (
        client.get(f"/api/products/{product['id']}/templates/{template['id']}").status_code == 200
    )


def test_deletion_succeeds_once_the_product_is_released(client, db_session):
    """Removing the catalog file and rolling out is the supported path."""
    product = _create_product(client, "immich")
    template = _create_template(client, product["id"])
    _curate(db_session, product["id"], "immich")

    _release(db_session, product["id"])

    assert (
        client.delete(f"/api/products/{product['id']}/templates/{template['id']}").status_code
        == 204
    )
    assert client.delete(f"/api/products/{product['id']}").status_code == 204


def test_non_curated_deletion_is_unaffected(client):
    product = _create_product(client, "scratch")
    template = _create_template(client, product["id"])

    assert (
        client.delete(f"/api/products/{product['id']}/templates/{template['id']}").status_code
        == 204
    )
    assert client.delete(f"/api/products/{product['id']}").status_code == 204


# ---------------------------------------------------------------------------
# CLI / REST parity
# ---------------------------------------------------------------------------


def _yaml(result):
    return yaml.safe_load(getattr(result, "stdout", result.output))


def _cli_curate(product_id: int, slug: str) -> None:
    with session_scope() as session:
        product = session.get(ProductORM, product_id)
        product.slug = slug
        product.curated = True
        session.add(product)
        session.commit()


def _cli_product(runner, app, name: str) -> dict:
    return _yaml(runner.invoke(app, ["create-product", name, "desc"]))


def test_cli_update_of_a_curated_product_is_rejected(cli_runner):
    runner, app = cli_runner
    product = _cli_product(runner, app, "immich")
    _cli_curate(product["id"], "immich")

    result = runner.invoke(app, ["update-product", str(product["id"]), "--description", "edited"])
    assert result.exit_code == 1
    assert "products/catalog/immich/immich.yaml" in result.output


def test_cli_forced_update_succeeds(cli_runner):
    runner, app = cli_runner
    product = _cli_product(runner, app, "immich")
    _cli_curate(product["id"], "immich")

    result = runner.invoke(
        app, ["update-product", str(product["id"]), "--description", "hotfix", "--force"]
    )
    assert result.exit_code == 0
    assert _yaml(result)["description"] == "hotfix"


def test_cli_template_creation_on_a_curated_product_is_rejected(cli_runner):
    runner, app = cli_runner
    product = _cli_product(runner, app, "immich")
    _cli_curate(product["id"], "immich")

    args = [
        "create-template",
        "--product-id",
        str(product["id"]),
        "--chart-ref",
        "oci://example/chart",
        "--chart-version",
        "1.0.0",
    ]
    assert runner.invoke(app, args).exit_code == 1
    forced = runner.invoke(app, [*args, "--force"])
    assert forced.exit_code == 0

    # A forced row is unstamped, exactly as over REST.
    with session_scope() as session:
        template = session.get(ProductTemplateVersionORM, _yaml(forced)["id"])
        assert template.catalog_commit is None


def test_cli_deletion_of_a_curated_product_is_never_forceable(cli_runner):
    runner, app = cli_runner
    product = _cli_product(runner, app, "immich")
    _cli_curate(product["id"], "immich")

    for args in (["delete-product", str(product["id"])], ["delete-product", str(product["id"]), "--force"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 1, args
        assert "products/catalog/immich/immich.yaml" in result.output


def test_cli_non_curated_product_is_unaffected(cli_runner):
    runner, app = cli_runner
    product = _cli_product(runner, app, "scratch")

    updated = runner.invoke(app, ["update-product", str(product["id"]), "--description", "edited"])
    assert updated.exit_code == 0
    assert _yaml(updated)["description"] == "edited"

    assert runner.invoke(app, ["delete-product", str(product["id"])]).exit_code == 0


def test_cli_forced_write_is_logged_with_the_acting_user(cli_runner, caplog):
    runner, app = cli_runner
    product = _cli_product(runner, app, "immich")
    _cli_curate(product["id"], "immich")

    with caplog.at_level("WARNING", logger="app.services.products"):
        runner.invoke(
            app, ["update-product", str(product["id"]), "--description", "hotfix", "--force"]
        )

    assert any(
        "Forced write" in record.getMessage()
        and "slug=immich" in record.getMessage()
        and CLI_USER_EMAIL in record.getMessage()
        for record in caplog.records
    ), [record.getMessage() for record in caplog.records]
