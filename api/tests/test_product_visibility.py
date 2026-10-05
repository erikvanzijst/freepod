"""Product visibility: the end-user product list versus the admin listing.

`GET /api/products` returns what the caller may see. Anonymous visitors and
regular users get only products whose ``visibility`` is ``public``;
administrators get every non-deleted product. ``caelus list-products`` mirrors
this, keyed on the acting CLI user.
"""

from __future__ import annotations

import yaml
from sqlmodel import select

from app.db import session_scope
from app.models import UserORM
from tests.conftest import (
    AUTH_HEADER,
    USER_AUTH_HEADER,
    client,
    create_free_plan_template,
    create_user,
    user_client,
)

# An empty auth header is what an unauthenticated visitor sends; it overrides
# the admin header the `client` fixture applies by default.
ANONYMOUS = {"X-Auth-Request-Email": ""}

CLI_USER_EMAIL = "cli-test@example.com"


def _names(response) -> list[str]:
    return [product["name"] for product in response.json()]


def _end_user_names(client) -> list[str]:
    """The listing an anonymous visitor sees."""
    resp = client.get("/api/products", headers=ANONYMOUS)
    assert resp.status_code == 200
    return _names(resp)


def _admin_names(client) -> list[str]:
    """The listing an administrator sees (the `client` fixture is an admin)."""
    resp = client.get("/api/products")
    assert resp.status_code == 200
    return _names(resp)


def _create_product(client, name: str, **payload) -> dict:
    resp = client.post("/api/products", json={"name": name, "description": "desc", **payload})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_new_product_defaults_to_admin_visibility(client):
    """A product being onboarded is not exposed to end users before it is ready."""
    product = _create_product(client, "fresh")
    assert product["visibility"] == "admin"

    assert _end_user_names(client) == []


def test_product_can_be_created_public(client):
    product = _create_product(client, "born-public", visibility="public")
    assert product["visibility"] == "public"
    assert _end_user_names(client) == ["born-public"]


# ---------------------------------------------------------------------------
# End-user listing
# ---------------------------------------------------------------------------


def test_hidden_product_is_excluded_for_anonymous_visitors(client):
    _create_product(client, "shown", visibility="public")
    _create_product(client, "hidden", visibility="admin")

    assert _end_user_names(client) == ["shown"]


def test_hidden_product_is_excluded_for_regular_users(user_client):
    """A signed-in non-admin sees the same catalog as an anonymous visitor."""
    non_admin, _ = user_client
    for name, visibility in (("shown", "public"), ("hidden", "admin")):
        resp = non_admin.post(
            "/api/products",
            json={"name": name, "description": "desc", "visibility": visibility},
            headers=AUTH_HEADER,  # products are admin-created
        )
        assert resp.status_code == 201, resp.text

    resp = non_admin.get("/api/products", headers=USER_AUTH_HEADER)
    assert resp.status_code == 200
    assert _names(resp) == ["shown"]


def test_end_user_listing_needs_no_authentication(client):
    _create_product(client, "shown", visibility="public")

    resp = client.get("/api/products", headers=ANONYMOUS)
    assert resp.status_code == 200
    assert _names(resp) == ["shown"]


def test_get_product_by_id_still_resolves_a_hidden_product(client):
    """Only listings are filtered; a direct read is unchanged."""
    product = _create_product(client, "hidden", visibility="admin")

    resp = client.get(f"/api/products/{product['id']}")
    assert resp.status_code == 200
    assert resp.json()["visibility"] == "admin"


# ---------------------------------------------------------------------------
# Admin listing
# ---------------------------------------------------------------------------


def test_admin_sees_public_and_hidden_products(client):
    _create_product(client, "shown", visibility="public")
    _create_product(client, "hidden", visibility="admin")

    assert sorted(_admin_names(client)) == ["hidden", "shown"]


def test_admin_listing_still_excludes_deleted_products(client):
    _create_product(client, "kept", visibility="public")
    doomed = _create_product(client, "doomed", visibility="admin")

    assert client.delete(f"/api/products/{doomed['id']}").status_code == 204

    assert _admin_names(client) == ["kept"]


# ---------------------------------------------------------------------------
# Changing visibility
# ---------------------------------------------------------------------------


def test_publishing_a_product_adds_it_to_the_end_user_list(client):
    product = _create_product(client, "publishable")
    assert _end_user_names(client) == []

    resp = client.put(f"/api/products/{product['id']}", json={"visibility": "public"})
    assert resp.status_code == 200
    assert resp.json()["visibility"] == "public"

    assert _end_user_names(client) == ["publishable"]


def test_withdrawing_a_product_removes_it_from_the_end_user_list(client):
    product = _create_product(client, "withdrawable", visibility="public")
    assert _end_user_names(client) == ["withdrawable"]

    resp = client.put(f"/api/products/{product['id']}", json={"visibility": "admin"})
    assert resp.status_code == 200

    assert _end_user_names(client) == []
    assert _admin_names(client) == ["withdrawable"]


def test_updating_other_fields_leaves_visibility_untouched(client):
    product = _create_product(client, "partial", visibility="public")

    resp = client.put(f"/api/products/{product['id']}", json={"description": "new"})
    assert resp.status_code == 200
    assert resp.json()["visibility"] == "public"


def test_invalid_visibility_is_rejected(client):
    product = _create_product(client, "picky")

    resp = client.put(f"/api/products/{product['id']}", json={"visibility": "everyone"})
    assert resp.status_code == 422


def test_visibility_change_is_logged_with_the_acting_user(client, caplog):
    product = _create_product(client, "audited")

    with caplog.at_level("INFO", logger="app.services.products"):
        client.put(f"/api/products/{product['id']}", json={"visibility": "public"})

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "visibility changed" in message
        and "from=admin" in message
        and "to=public" in message
        and "test@example.com" in message
        for message in messages
    ), messages


def test_withdrawing_a_product_leaves_existing_deployments_untouched(client, db_session):
    """Withdrawal stops new provisions; it does not disturb what is running."""
    user_id = create_user(client, "vis-deploy@example.com")["id"]
    product = _create_product(client, "deployed", visibility="public")

    template_resp = client.post(
        f"/api/products/{product['id']}/templates",
        json={
            "chart_ref": "oci://example/chart",
            "chart_version": "1.0.0",
            "values_schema_json": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ingress": {
                        "type": "object",
                        "properties": {"host": {"type": "string", "title": "hostname"}},
                    }
                },
            },
        },
    )
    assert template_resp.status_code == 201
    template_id = template_resp.json()["id"]
    client.put(f"/api/products/{product['id']}", json={"template_id": template_id})
    ptv_id = create_free_plan_template(db_session, product["id"])

    deployment_resp = client.post(
        f"/api/users/{user_id}/deployments",
        json={
            "desired_template_id": template_id,
            "user_values_json": {"ingress": {"host": "vis.example.com"}},
            "plan_template_id": ptv_id,
        },
    )
    assert deployment_resp.status_code == 201
    before = deployment_resp.json()["deployment"]

    assert (
        client.put(f"/api/products/{product['id']}", json={"visibility": "admin"}).status_code
        == 200
    )

    after = client.get(f"/api/users/{user_id}/deployments/{before['id']}").json()
    assert after["status"] == before["status"]
    assert after["generation"] == before["generation"]
    assert after["desired_template_id"] == before["desired_template_id"]
    assert after["applied_template"] == before["applied_template"]
    assert after["hostname"] == before["hostname"]


# ---------------------------------------------------------------------------
# CLI / REST parity
# ---------------------------------------------------------------------------


def _yaml(result):
    return yaml.safe_load(getattr(result, "stdout", result.output))


def _cli_names(runner, app) -> list[str]:
    listed = _yaml(runner.invoke(app, ["list-products"])) or []
    return [product["name"] for product in listed]


def _promote_cli_user(runner, app) -> None:
    """Make the acting CLI user an admin (it is created as a regular user)."""
    runner.invoke(app, ["list-users"])  # any command auto-creates the CLI user
    with session_scope() as session:
        user = session.exec(select(UserORM).where(UserORM.email == CLI_USER_EMAIL)).one()
        user.is_admin = True
        session.add(user)
        session.commit()


def test_cli_create_product_defaults_to_admin_visibility(cli_runner):
    runner, app = cli_runner

    result = runner.invoke(app, ["create-product", "cli-fresh", "desc"])
    assert result.exit_code == 0
    assert _yaml(result)["visibility"] == "admin"

    assert _cli_names(runner, app) == []


def test_cli_create_product_accepts_visibility(cli_runner):
    runner, app = cli_runner

    result = runner.invoke(
        app, ["create-product", "cli-public", "desc", "--visibility", "public"]
    )
    assert result.exit_code == 0
    assert _yaml(result)["visibility"] == "public"

    assert _cli_names(runner, app) == ["cli-public"]


def test_cli_list_products_shows_hidden_products_to_an_admin(cli_runner):
    """Parity with REST: the acting user's privileges decide, not a flag."""
    runner, app = cli_runner

    runner.invoke(app, ["create-product", "cli-hidden", "desc"])
    runner.invoke(app, ["create-product", "cli-shown", "desc", "--visibility", "public"])
    assert _cli_names(runner, app) == ["cli-shown"]

    _promote_cli_user(runner, app)
    assert sorted(_cli_names(runner, app)) == ["cli-hidden", "cli-shown"]


def test_cli_update_product_changes_visibility_like_the_api(cli_runner):
    runner, app = cli_runner

    created = _yaml(runner.invoke(app, ["create-product", "cli-updatable", "desc"]))
    product_id = str(created["id"])

    published = runner.invoke(app, ["update-product", product_id, "--visibility", "public"])
    assert published.exit_code == 0
    assert _yaml(published)["visibility"] == "public"
    assert _cli_names(runner, app) == ["cli-updatable"]

    withdrawn = runner.invoke(app, ["update-product", product_id, "--visibility", "admin"])
    assert withdrawn.exit_code == 0
    assert _yaml(withdrawn)["visibility"] == "admin"
    assert _cli_names(runner, app) == []

    # Withdrawn, not deleted: an admin still sees it.
    _promote_cli_user(runner, app)
    assert _cli_names(runner, app) == ["cli-updatable"]


def test_cli_update_product_rejects_invalid_visibility(cli_runner):
    runner, app = cli_runner

    created = _yaml(runner.invoke(app, ["create-product", "cli-picky", "desc"]))
    result = runner.invoke(
        app, ["update-product", str(created["id"]), "--visibility", "everyone"]
    )
    assert result.exit_code != 0


def test_cli_update_product_leaves_visibility_untouched_when_omitted(cli_runner):
    runner, app = cli_runner

    created = _yaml(
        runner.invoke(app, ["create-product", "cli-partial", "desc", "--visibility", "public"])
    )
    result = runner.invoke(
        app, ["update-product", str(created["id"]), "--description", "new"]
    )
    assert result.exit_code == 0
    assert _yaml(result)["visibility"] == "public"
