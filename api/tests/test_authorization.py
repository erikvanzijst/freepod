"""Authorization matrix tests.

Tests the authorization rules for all API endpoints using parameterization:
- admin: can access everything
- self: can access own resources, rejected for others'
- other: non-admin accessing another user's resources, rejected
"""
import pytest
from starlette.testclient import TestClient

from tests.conftest import CURRENT_TOS_VERSION, subdomain_for
from tests.conftest import (
    ADMIN_EMAIL,
    AUTH_HEADER,
    OTHER_AUTH_HEADER,
    OTHER_EMAIL,
    USER_AUTH_HEADER,
    USER_EMAIL,
    create_free_plan_template,
)
from app.db import get_session
from app.main import app as fastapi_app
from app.models import UserORM


@pytest.fixture
def authz_setup(db_session):
    """Set up admin, regular, and other users; return their IDs and test clients."""
    def override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_session] = override_get_db

    admin = UserORM(email=ADMIN_EMAIL, is_admin=True,
                    subdomain=subdomain_for(ADMIN_EMAIL),
                    tos_accepted_version=CURRENT_TOS_VERSION)
    user = UserORM(email=USER_EMAIL, is_admin=False,
                   subdomain=subdomain_for(USER_EMAIL),
                   tos_accepted_version=CURRENT_TOS_VERSION)
    other = UserORM(email=OTHER_EMAIL, is_admin=False,
                    subdomain=subdomain_for(OTHER_EMAIL),
                    tos_accepted_version=CURRENT_TOS_VERSION)
    db_session.add_all([admin, user, other])
    db_session.commit()
    db_session.refresh(admin)
    db_session.refresh(user)
    db_session.refresh(other)

    with (
        TestClient(fastapi_app, headers=AUTH_HEADER) as admin_client,
        TestClient(fastapi_app, headers=USER_AUTH_HEADER) as user_client,
        TestClient(fastapi_app, headers=OTHER_AUTH_HEADER) as other_client,
        # A subject-less client (email only) so the subject-less branch of the
        # resolution ladder stays covered alongside the subject-bearing one.
        TestClient(fastapi_app, headers={"X-Auth-Request-Email": USER_EMAIL}) as user_client_subjectless,
    ):
        # Create a product and template (as admin) for deployment tests
        product = admin_client.post(
            "/api/products",
            json={"name": "authz-test-product", "description": "For authz tests"},
        )
        product_id = product.json()["id"]

        template = admin_client.post(
            f"/api/products/{product_id}/templates",
            json={
                "chart_ref": "oci://example/authz-chart",
                "chart_version": "1.0.0",
                "values_schema_json": {
                    "type": "object",
                    "properties": {
                        "user": {
                            "type": "object",
                            "properties": {"host": {"type": "string", "title": "Hostname"}},
                        }
                    },
                },
            },
        )
        template_id = template.json()["id"]

        # Make it the canonical template
        admin_client.put(f"/api/products/{product_id}", json={"template_id": template_id})

        # Create a free plan for this product
        ptv_id = create_free_plan_template(db_session, product_id)

        # Create a deployment for the regular user (as admin)
        deployment = admin_client.post(
            f"/api/users/{user.id}/deployments",
            json={
                "desired_template_id": template_id,
                "plan_template_id": ptv_id,
                "user_values_json": {"user": {"host": "authz.example.com"}},
            },
        )
        deployment_id = deployment.json()["deployment"]["id"]

        yield {
            "admin_client": admin_client,
            "user_client": user_client,
            "other_client": other_client,
            "user_client_subjectless": user_client_subjectless,
            "admin": admin,
            "user": user,
            "other": other,
            "product_id": product_id,
            "template_id": template_id,
            "deployment_id": deployment_id,
            "plan_template_id": ptv_id,
        }

    fastapi_app.dependency_overrides.clear()


# ── Admin-only endpoints: admin gets through, regular users get 403 ──


ADMIN_ONLY_ENDPOINTS = [
    ("GET", "/api/users", None),
]


@pytest.mark.parametrize("method,path,body", ADMIN_ONLY_ENDPOINTS)
def test_admin_can_access_admin_endpoints(authz_setup, method, path, body):
    resp = authz_setup["admin_client"].request(method, path, json=body)
    assert resp.status_code < 400, f"{method} {path}: expected success, got {resp.status_code}"


@pytest.mark.parametrize("method,path,body", ADMIN_ONLY_ENDPOINTS)
def test_regular_user_rejected_from_admin_endpoints(authz_setup, method, path, body):
    resp = authz_setup["user_client"].request(method, path, json=body)
    assert resp.status_code == 403, f"{method} {path}: expected 403, got {resp.status_code}"


# ── Product mutation endpoints: admin-only ───────────────────────────


def _product_mutation_endpoints(product_id, template_id):
    return [
        ("POST", "/api/products", {"name": "new-product", "description": "test"}),
        ("PUT", f"/api/products/{product_id}", {"name": "renamed"}),
        ("DELETE", f"/api/products/{product_id}", None),
        ("POST", f"/api/products/{product_id}/templates", {
            "chart_ref": "oci://example/new",
            "chart_version": "2.0.0",
            "values_schema_json": {"type": "object"},
        }),
        ("DELETE", f"/api/products/{product_id}/templates/{template_id}", None),
    ]


def test_admin_can_mutate_products(authz_setup):
    s = authz_setup
    # Test POST and a template POST (non-destructive first)
    resp = s["admin_client"].post(
        "/api/products", json={"name": "admin-product", "description": "test"}
    )
    assert resp.status_code == 201


def test_regular_user_rejected_from_product_mutations(authz_setup):
    s = authz_setup
    endpoints = _product_mutation_endpoints(s["product_id"], s["template_id"])
    for method, path, body in endpoints:
        resp = s["user_client"].request(method, path, json=body)
        assert resp.status_code == 403, f"{method} {path}: expected 403, got {resp.status_code}"


# ── Product GET endpoints: open to all authenticated users ───────────


def test_regular_user_can_read_products(authz_setup):
    s = authz_setup
    get_endpoints = [
        f"/api/products",
        f"/api/products/{s['product_id']}",
        f"/api/products/{s['product_id']}/templates",
        f"/api/products/{s['product_id']}/templates/{s['template_id']}",
    ]
    for path in get_endpoints:
        resp = s["user_client"].get(path)
        assert resp.status_code == 200, f"GET {path}: expected 200, got {resp.status_code}"


# ── Self-or-admin endpoints ──────────────────────────────────────────


def _self_read_endpoints(user_id, deployment_id):
    """Read-only endpoints scoped to a user_id."""
    return [
        ("GET", f"/api/users/{user_id}", None),
        ("GET", f"/api/users/{user_id}/deployments", None),
        ("GET", f"/api/users/{user_id}/deployments/{deployment_id}", None),
    ]


def test_user_can_access_own_resources(authz_setup):
    s = authz_setup
    for method, path, body in _self_read_endpoints(s["user"].id, s["deployment_id"]):
        resp = s["user_client"].request(method, path, json=body)
        assert resp.status_code == 200, (
            f"{method} {path}: expected 200, got {resp.status_code}"
        )


def test_subject_less_request_resolves_by_email(authz_setup):
    # The subject-less branch (email only) resolves the regular user's own
    # resources, so it stays covered here alongside the subject-bearing client.
    s = authz_setup
    for method, path, body in _self_read_endpoints(s["user"].id, s["deployment_id"]):
        resp = s["user_client_subjectless"].request(method, path, json=body)
        assert resp.status_code == 200, (
            f"{method} {path}: expected 200, got {resp.status_code}"
        )


def test_subject_less_and_subject_bearing_resolve_to_same_user(authz_setup):
    # Both branches of the ladder resolve the regular user to the same record.
    s = authz_setup
    me_bearing = s["user_client"].get("/api/me")
    me_less = s["user_client_subjectless"].get("/api/me")
    assert me_bearing.status_code == 200
    assert me_less.status_code == 200
    assert me_bearing.json()["id"] == me_less.json()["id"] == s["user"].id


def test_other_user_rejected_from_resources(authz_setup):
    s = authz_setup
    endpoints = [
        ("GET", f"/api/users/{s['user'].id}", None),
        ("GET", f"/api/users/{s['user'].id}/deployments", None),
        ("GET", f"/api/users/{s['user'].id}/deployments/{s['deployment_id']}", None),
        ("PUT", f"/api/users/{s['user'].id}/deployments/{s['deployment_id']}", {
            "desired_template_id": s["template_id"],
        }),
        ("DELETE", f"/api/users/{s['user'].id}/deployments/{s['deployment_id']}", None),
        ("POST", f"/api/users/{s['user'].id}/deployments", {
            "desired_template_id": s["template_id"],
            "plan_template_id": s["plan_template_id"],
            "user_values_json": {"user": {"host": "other.example.com"}},
        }),
    ]
    for method, path, body in endpoints:
        resp = s["other_client"].request(method, path, json=body)
        assert resp.status_code == 403, (
            f"{method} {path}: expected 403, got {resp.status_code}"
        )


def test_admin_can_access_other_users_resources(authz_setup):
    s = authz_setup
    for method, path, body in _self_read_endpoints(s["user"].id, s["deployment_id"]):
        resp = s["admin_client"].request(method, path, json=body)
        assert resp.status_code == 200, (
            f"{method} {path}: expected 200, got {resp.status_code}"
        )


# ── User deletion returns 501 for everyone ───────────────────────────


@pytest.mark.parametrize("client_key", ["admin_client", "user_client", "other_client"])
def test_user_deletion_returns_501(authz_setup, client_key):
    s = authz_setup
    resp = s[client_key].delete(f"/api/users/{s['user'].id}")
    assert resp.status_code == 501
    assert resp.json()["detail"] == "User deletion is not yet implemented"
