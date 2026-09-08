"""Tests for Plan and Subscription APIs (spec tasks 11.6–11.9).

Covers:
- 11.6: Plan CRUD and plan template version creation
- 11.7: Subscription list, get, cancel, payment status update
- 11.8: Deployment creation with/without plan_template_id
- 11.9: Authorization for plans and subscriptions
"""
import pytest

from tests.conftest import CURRENT_TOS_VERSION, subdomain_for
from tests.conftest import (
    ADMIN_EMAIL,
    AUTH_HEADER,
    USER_AUTH_HEADER,
    USER_EMAIL,
    OTHER_AUTH_HEADER,
    OTHER_EMAIL,
    create_free_plan_template,
    create_user,
)
from app.db import get_session
from app.main import app as fastapi_app
from app.models import UserORM
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_product_and_template(client):
    """Create a product with a canonical template. Returns (product_id, template_id)."""
    product = client.post(
        "/api/products", json={"name": "test-product", "description": "For tests"}
    )
    assert product.status_code == 201
    product_id = product.json()["id"]

    template = client.post(
        f"/api/products/{product_id}/templates",
        json={
            "chart_ref": "oci://example/chart",
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
    assert template.status_code == 201
    template_id = template.json()["id"]

    client.put(f"/api/products/{product_id}", json={"template_id": template_id})
    return product_id, template_id


# ===========================================================================
# 11.6 Plan API tests
# ===========================================================================


class TestPlanAPI:
    def test_create_plan_returns_201(self, client):
        product_id, _ = _setup_product_and_template(client)
        resp = client.post(
            f"/api/products/{product_id}/plans",
            json={"name": "Basic"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Basic"
        assert data["product_id"] == product_id
        assert "id" in data

    def test_list_plans_excludes_deleted(self, client):
        product_id, _ = _setup_product_and_template(client)

        # Create two plans
        r1 = client.post(f"/api/products/{product_id}/plans", json={"name": "Plan A"})
        assert r1.status_code == 201
        plan_a_id = r1.json()["id"]

        r2 = client.post(f"/api/products/{product_id}/plans", json={"name": "Plan B"})
        assert r2.status_code == 201

        # Delete Plan A
        del_resp = client.delete(f"/api/plans/{plan_a_id}")
        assert del_resp.status_code == 204

        # List should only include Plan B
        list_resp = client.get(f"/api/products/{product_id}/plans")
        assert list_resp.status_code == 200
        names = [p["name"] for p in list_resp.json()]
        assert "Plan B" in names
        assert "Plan A" not in names

    def test_get_plan_returns_template_details(self, client, db_session):
        product_id, _ = _setup_product_and_template(client)

        # Create plan
        plan_resp = client.post(
            f"/api/products/{product_id}/plans", json={"name": "Pro"}
        )
        assert plan_resp.status_code == 201
        plan_id = plan_resp.json()["id"]

        # Create a template version for this plan
        tmpl_resp = client.post(
            f"/api/plans/{plan_id}/templates",
            json={"price_cents": 999, "billing_interval": "monthly"},
        )
        assert tmpl_resp.status_code == 201
        tmpl_id = tmpl_resp.json()["id"]

        # Point the plan at this template
        client.put(f"/api/plans/{plan_id}", json={"template_id": tmpl_id})

        # GET plan should include template details
        get_resp = client.get(f"/api/plans/{plan_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["template"] is not None
        assert data["template"]["id"] == tmpl_id
        assert data["template"]["price_cents"] == 999

    def test_update_plan_name_and_template_id(self, client):
        product_id, _ = _setup_product_and_template(client)

        plan_resp = client.post(
            f"/api/products/{product_id}/plans", json={"name": "Old Name"}
        )
        plan_id = plan_resp.json()["id"]

        # Create a template version
        tmpl_resp = client.post(
            f"/api/plans/{plan_id}/templates",
            json={"price_cents": 500, "billing_interval": "monthly"},
        )
        tmpl_id = tmpl_resp.json()["id"]

        # Update both name and template_id
        update_resp = client.put(
            f"/api/plans/{plan_id}",
            json={"name": "New Name", "template_id": tmpl_id},
        )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert data["name"] == "New Name"
        assert data["template_id"] == tmpl_id

    def test_delete_plan_soft_deletes(self, client):
        product_id, _ = _setup_product_and_template(client)

        plan_resp = client.post(
            f"/api/products/{product_id}/plans", json={"name": "Disposable"}
        )
        plan_id = plan_resp.json()["id"]

        del_resp = client.delete(f"/api/plans/{plan_id}")
        assert del_resp.status_code == 204

        # Plan should no longer appear in listing
        list_resp = client.get(f"/api/products/{product_id}/plans")
        ids = [p["id"] for p in list_resp.json()]
        assert plan_id not in ids

    def test_create_plan_template_version_returns_201(self, client):
        product_id, _ = _setup_product_and_template(client)

        plan_resp = client.post(
            f"/api/products/{product_id}/plans", json={"name": "Versioned"}
        )
        plan_id = plan_resp.json()["id"]

        tmpl_resp = client.post(
            f"/api/plans/{plan_id}/templates",
            json={
                "price_cents": 1999,
                "billing_interval": "annual",
                "storage_bytes": 107374182400,
                "database_bytes": 1073741824,
            },
        )
        assert tmpl_resp.status_code == 201
        data = tmpl_resp.json()
        assert data["plan_id"] == plan_id
        assert data["price_cents"] == 1999
        assert data["billing_interval"] == "annual"
        assert data["storage_bytes"] == 107374182400
        assert data["database_bytes"] == 1073741824

        # The allowance survives the read path as well as the create response.
        read_resp = client.get(f"/api/plans/{plan_id}/templates")
        assert read_resp.status_code == 200
        assert [t["database_bytes"] for t in read_resp.json()] == [1073741824]

    def test_plan_template_allowances_are_independent(self, client):
        """A plan may bound one subsystem without bounding the other."""
        product_id, _ = _setup_product_and_template(client)

        plan_id = client.post(
            f"/api/products/{product_id}/plans", json={"name": "Storage only"}
        ).json()["id"]

        data = client.post(
            f"/api/plans/{plan_id}/templates",
            json={
                "price_cents": 0,
                "billing_interval": "monthly",
                "storage_bytes": 1073741824,
            },
        ).json()
        assert data["storage_bytes"] == 1073741824
        assert data["database_bytes"] is None

    def test_get_nonexistent_plan_returns_404(self, client):
        resp = client.get("/api/plans/99999")
        assert resp.status_code == 404


# ===========================================================================
# 11.7 Subscription API tests
# ===========================================================================


class TestSubscriptionAPI:
    def _create_deployment_with_subscription(self, client, db_session):
        """Helper that creates a product, plan, template, user, and deployment.

        Returns (user_id, deployment_data, product_id, ptv_id).
        """
        product_id, template_id = _setup_product_and_template(client)
        ptv_id = create_free_plan_template(db_session, product_id)

        user_id = create_user(client, "sub-user@example.com")["id"]

        dep_resp = client.post(
            f"/api/users/{user_id}/deployments",
            json={
                "desired_template_id": template_id,
                "plan_template_id": ptv_id,
                "user_values_json": {"user": {"host": "sub.example.com"}},
            },
        )
        assert dep_resp.status_code == 201
        return user_id, dep_resp.json()["deployment"], product_id, ptv_id

    def test_list_subscriptions(self, client, db_session):
        user_id, dep_data, _, _ = self._create_deployment_with_subscription(
            client, db_session
        )
        resp = client.get(f"/api/users/{user_id}/subscriptions")
        assert resp.status_code == 200
        subs = resp.json()
        assert len(subs) >= 1
        assert subs[0]["user_id"] == user_id

    def test_get_subscription(self, client, db_session):
        user_id, dep_data, _, _ = self._create_deployment_with_subscription(
            client, db_session
        )
        subscription_id = dep_data["subscription_id"]
        assert subscription_id is not None

        resp = client.get(f"/api/subscriptions/{subscription_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == subscription_id
        assert data["user_id"] == user_id
        assert data["status"] == "active"

    def test_cancel_subscription(self, client, db_session):
        user_id, dep_data, _, _ = self._create_deployment_with_subscription(
            client, db_session
        )
        subscription_id = dep_data["subscription_id"]

        resp = client.put(
            f"/api/subscriptions/{subscription_id}",
            json={"status": "cancelled"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["cancelled_at"] is not None

    def test_update_payment_status_to_arrears(self, client, db_session):
        user_id, dep_data, _, _ = self._create_deployment_with_subscription(
            client, db_session
        )
        subscription_id = dep_data["subscription_id"]

        resp = client.put(
            f"/api/subscriptions/{subscription_id}",
            json={"payment_status": "arrears"},
        )
        assert resp.status_code == 200
        assert resp.json()["payment_status"] == "arrears"

    def test_cancel_is_idempotent(self, client, db_session):
        user_id, dep_data, _, _ = self._create_deployment_with_subscription(
            client, db_session
        )
        subscription_id = dep_data["subscription_id"]

        # Cancel first time
        r1 = client.put(
            f"/api/subscriptions/{subscription_id}",
            json={"status": "cancelled"},
        )
        assert r1.status_code == 200

        # Cancel second time — should still succeed
        r2 = client.put(
            f"/api/subscriptions/{subscription_id}",
            json={"status": "cancelled"},
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "cancelled"


# ===========================================================================
# 11.8 Deployment API tests (plan_template_id)
# ===========================================================================


class TestDeploymentPlanTemplate:
    def test_deployment_without_plan_template_id_returns_422(self, client, db_session):
        product_id, template_id = _setup_product_and_template(client)

        user_id = create_user(client, "noptv@example.com")["id"]

        resp = client.post(
            f"/api/users/{user_id}/deployments",
            json={
                "desired_template_id": template_id,
                "user_values_json": {"user": {"host": "noptv.example.com"}},
            },
        )
        assert resp.status_code == 422

    def test_deployment_with_valid_plan_template_id_succeeds(self, client, db_session):
        product_id, template_id = _setup_product_and_template(client)
        ptv_id = create_free_plan_template(db_session, product_id)

        user_id = create_user(client, "validptv@example.com")["id"]

        resp = client.post(
            f"/api/users/{user_id}/deployments",
            json={
                "desired_template_id": template_id,
                "plan_template_id": ptv_id,
                "user_values_json": {"user": {"host": "validptv.example.com"}},
            },
        )
        assert resp.status_code == 201
        data = resp.json()["deployment"]
        assert "subscription_id" in data
        assert data["subscription_id"] is not None

    def test_deployment_with_invalid_plan_template_id_returns_error(
        self, client, db_session
    ):
        product_id, template_id = _setup_product_and_template(client)

        user_id = create_user(client, "badptv@example.com")["id"]

        resp = client.post(
            f"/api/users/{user_id}/deployments",
            json={
                "desired_template_id": template_id,
                "plan_template_id": 99999,
                "user_values_json": {"user": {"host": "badptv.example.com"}},
            },
        )
        assert resp.status_code in (404, 422, 400)

    def test_deployment_with_non_canonical_plan_template_returns_error(
        self, client, db_session
    ):
        """A plan template that is no longer canonical cannot be used for new deployments."""
        from app.models import PlanORM, PlanTemplateVersionORM, BillingInterval
        from app.models.core import _utcnow

        product_id, template_id = _setup_product_and_template(client)

        # Create a plan with two template versions; only the second is canonical.
        plan = PlanORM(name="Versioned", product_id=product_id, created_at=_utcnow())
        db_session.add(plan)
        db_session.flush()
        old_ptv = PlanTemplateVersionORM(
            plan_id=plan.id, price_cents=500, billing_interval=BillingInterval.MONTHLY,
            storage_bytes=1073741824, created_at=_utcnow(),
        )
        db_session.add(old_ptv)
        db_session.flush()
        new_ptv = PlanTemplateVersionORM(
            plan_id=plan.id, price_cents=999, billing_interval=BillingInterval.MONTHLY,
            storage_bytes=10737418240, created_at=_utcnow(),
        )
        db_session.add(new_ptv)
        db_session.flush()
        plan.template_id = new_ptv.id  # new_ptv is canonical, old_ptv is stale
        db_session.commit()

        user_id = create_user(client, "stale-ptv@example.com")["id"]

        resp = client.post(
            f"/api/users/{user_id}/deployments",
            json={
                "desired_template_id": template_id,
                "plan_template_id": old_ptv.id,
                "user_values_json": {"user": {"host": "stale.example.com"}},
            },
        )
        assert resp.status_code == 400
        assert "canonical" in resp.json()["detail"].lower()

    def test_deployment_with_plan_template_from_different_product_returns_error(
        self, client, db_session
    ):
        """A plan template belonging to a different product cannot be used."""
        product_id, template_id = _setup_product_and_template(client)

        # Create a second product with its own plan template.
        other_product = client.post(
            "/api/products", json={"name": "other-product", "description": "Other"}
        )
        other_product_id = other_product.json()["id"]
        other_ptv_id = create_free_plan_template(db_session, other_product_id)

        user_id = create_user(client, "cross-product@example.com")["id"]

        resp = client.post(
            f"/api/users/{user_id}/deployments",
            json={
                "desired_template_id": template_id,
                "plan_template_id": other_ptv_id,
                "user_values_json": {"user": {"host": "cross.example.com"}},
            },
        )
        assert resp.status_code == 400
        assert "product" in resp.json()["detail"].lower()


# ===========================================================================
# 11.9 Authorization tests
# ===========================================================================


@pytest.fixture
def authz_setup(db_session):
    """Set up admin, regular, and other users with clients for authorization tests."""
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
    ):
        # Create product and template as admin
        product_id, template_id = _setup_product_and_template(admin_client)
        ptv_id = create_free_plan_template(db_session, product_id)

        # Create a plan as admin
        plan_resp = admin_client.post(
            f"/api/products/{product_id}/plans", json={"name": "Auth Plan"}
        )
        plan_id = plan_resp.json()["id"]

        # Create a deployment (and thus subscription) for the regular user
        dep_resp = admin_client.post(
            f"/api/users/{user.id}/deployments",
            json={
                "desired_template_id": template_id,
                "plan_template_id": ptv_id,
                "user_values_json": {"user": {"host": "authz.example.com"}},
            },
        )
        assert dep_resp.status_code == 201
        subscription_id = dep_resp.json()["deployment"]["subscription_id"]

        yield {
            "admin_client": admin_client,
            "user_client": user_client,
            "other_client": other_client,
            "admin": admin,
            "user": user,
            "other": other,
            "product_id": product_id,
            "template_id": template_id,
            "plan_id": plan_id,
            "plan_template_id": ptv_id,
            "subscription_id": subscription_id,
        }

    fastapi_app.dependency_overrides.clear()


class TestPlanAuthorization:
    """Non-admin cannot create, update, or delete plans or plan templates."""

    def test_non_admin_cannot_create_plan(self, authz_setup):
        s = authz_setup
        resp = s["user_client"].post(
            f"/api/products/{s['product_id']}/plans",
            json={"name": "Unauthorized Plan"},
        )
        assert resp.status_code == 403

    def test_non_admin_cannot_update_plan(self, authz_setup):
        s = authz_setup
        resp = s["user_client"].put(
            f"/api/plans/{s['plan_id']}",
            json={"name": "Hacked Name"},
        )
        assert resp.status_code == 403

    def test_non_admin_cannot_delete_plan(self, authz_setup):
        s = authz_setup
        resp = s["user_client"].delete(f"/api/plans/{s['plan_id']}")
        assert resp.status_code == 403

    def test_non_admin_cannot_create_plan_template(self, authz_setup):
        s = authz_setup
        resp = s["user_client"].post(
            f"/api/plans/{s['plan_id']}/templates",
            json={"price_cents": 100, "billing_interval": "monthly"},
        )
        assert resp.status_code == 403


class TestSubscriptionAuthorization:
    """Non-owner cannot access subscriptions; owner and admin can."""

    def test_non_owner_cannot_get_subscription(self, authz_setup):
        s = authz_setup
        resp = s["other_client"].get(
            f"/api/subscriptions/{s['subscription_id']}"
        )
        assert resp.status_code == 403

    def test_non_owner_cannot_update_subscription(self, authz_setup):
        s = authz_setup
        resp = s["other_client"].put(
            f"/api/subscriptions/{s['subscription_id']}",
            json={"status": "cancelled"},
        )
        assert resp.status_code == 403

    def test_owner_can_get_own_subscription(self, authz_setup):
        s = authz_setup
        resp = s["user_client"].get(
            f"/api/subscriptions/{s['subscription_id']}"
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == s["subscription_id"]

    def test_owner_can_cancel_own_subscription(self, authz_setup):
        s = authz_setup
        resp = s["user_client"].put(
            f"/api/subscriptions/{s['subscription_id']}",
            json={"status": "cancelled"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_admin_can_access_any_subscription(self, authz_setup):
        s = authz_setup
        # Admin reading another user's subscription
        resp = s["admin_client"].get(
            f"/api/subscriptions/{s['subscription_id']}"
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == s["subscription_id"]
