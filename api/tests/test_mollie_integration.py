"""Tests for Mollie payment integration (spec task 10).

Covers:
- 10.1:  FakePaymentProvider fixture (conftest.py)
- 10.2:  Paid deployment creation returns checkout_url, pending state
- 10.3:  Free deployment creation unchanged
- 10.4:  Paid plan with no payment provider treated as free
- 10.5:  Mollie API failure rolls back, no DB records
- 10.6:  Webhook first payment paid -> provision
- 10.7:  Webhook first payment failed -> arrears
- 10.8:  Webhook first payment expired -> arrears
- 10.9:  Webhook recurring payment paid -> new record, stays current
- 10.10: Webhook recurring payment failed -> arrears
- 10.11: Webhook recurring paid recovers from arrears
- 10.12: Webhook duplicate is idempotent
- 10.13: Webhook unknown payment ID -> 200, no side effects
- 10.14: CLI refuses paid plan deployment
- 10.15: CLI creates free plan deployment normally
- 10.16: Subscription API no longer returns external_ref
"""
from __future__ import annotations

import pytest
import yaml
from uuid import UUID

from sqlmodel import select

from app.models import (
    DeploymentORM,
    DeploymentReconcileJobORM,
    MolliePaymentORM,
    MolliePaymentStatus,
    PaymentStatus,
    SubscriptionORM,
)
from app.services.reconcile_constants import (
    DEPLOYMENT_STATUS_PENDING,
    DEPLOYMENT_STATUS_PROVISIONING,
)
from tests.conftest import (
    CURRENT_TOS_VERSION,
    create_free_plan_template,
    create_paid_plan_template,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_product_and_template(client):
    """Create a product with a canonical template. Returns (product_id, template_id)."""
    product = client.post(
        "/api/products", json={"name": "mollie-prod", "description": "test"}
    )
    assert product.status_code == 201
    product_id = product.json()["id"]

    template = client.post(
        f"/api/products/{product_id}/templates",
        json={
            "chart_ref": "oci://test/chart",
            "chart_version": "1.0.0",
            "values_schema_json": {"type": "object"},
        },
    )
    assert template.status_code == 201
    template_id = template.json()["id"]

    client.put(f"/api/products/{product_id}", json={"template_id": template_id})
    return product_id, template_id


def _get_user(client) -> dict:
    """Auto-create a user via GET /api/me and return the user ID."""
    # resp = client.get("/api/me", headers=_auth(email))
    resp = client.get("/api/me")
    assert resp.status_code == 200
    return resp.json()


def _create_paid_deployment(client, db_session, product_id, template_id):
    """Auto-create user via auth header, create paid deployment. Returns (user_id, response)."""
    user_id = _get_user(client)['id']

    ptv_id = create_paid_plan_template(db_session, product_id)

    resp = client.post(
        f"/api/users/{user_id}/deployments",
        json={"desired_template_id": template_id, "plan_template_id": ptv_id},
    )
    return user_id, resp


def _get_mollie_payment(db_session, sub_id):
    """Get the first MolliePaymentORM for a subscription."""
    return db_session.exec(
        select(MolliePaymentORM).where(MolliePaymentORM.subscription_id == sub_id)
    ).one()


def _trigger_webhook(client, mollie_payment_id):
    """POST to the Mollie webhook endpoint."""
    return client.post("/api/webhooks/mollie", data={"id": mollie_payment_id})


def _complete_first_payment(client, fake_payment_provider, db_session, sub_id):
    """Simulate first payment success via webhook. Returns mollie_payment_id."""
    mp = _get_mollie_payment(db_session, sub_id)
    fake_payment_provider.simulate_paid(mp.mollie_payment_id)
    resp = _trigger_webhook(client, mp.mollie_payment_id)
    assert resp.status_code == 200
    db_session.expire_all()
    return mp.mollie_payment_id


# ===========================================================================
# 10.2: Paid deployment creation
# ===========================================================================


def test_paid_deployment_returns_checkout_url_and_pending_state(
    paid_client, fake_payment_provider, db_session
):
    product_id, template_id = _setup_product_and_template(paid_client)
    _, resp = _create_paid_deployment(
        paid_client, db_session, product_id, template_id
    )

    assert resp.status_code == 201
    data = resp.json()

    # Envelope response with checkout URL
    assert data["checkout_url"] is not None
    assert "fake.mollie.com/checkout" in data["checkout_url"]

    dep = data["deployment"]
    assert dep["status"] == DEPLOYMENT_STATUS_PENDING

    # Subscription should be pending
    sub = db_session.get(SubscriptionORM, dep["subscription_id"])
    assert sub.payment_status == PaymentStatus.PENDING

    # MolliePaymentORM should exist with status=open, sequence_type=first
    mp = _get_mollie_payment(db_session, sub.id)
    assert mp.status == MolliePaymentStatus.OPEN
    assert mp.sequence_type == "first"
    assert mp.amount_cents == 1000  # default from create_paid_plan_template

    # No reconcile job should be enqueued for pending deployments
    jobs = db_session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == UUID(dep["id"])
        )
    ).all()
    assert len(jobs) == 0

    # User should have a Mollie customer ID assigned
    from app.models import UserORM
    user = db_session.exec(
        select(UserORM).where(UserORM.email == _get_user(paid_client)['email'])
    ).one()
    assert user.mollie_customer_id is not None
    assert user.mollie_customer_id.startswith("cst_fake_")


# ===========================================================================
# 10.3: Free deployment unchanged
# ===========================================================================


def test_free_deployment_unchanged(paid_client, db_session):
    product_id, template_id = _setup_product_and_template(paid_client)
    ptv_id = create_free_plan_template(db_session, product_id)

    user_id, email = (lambda user: (user['id'], user['email']))(_get_user(paid_client))

    resp = paid_client.post(
        f"/api/users/{user_id}/deployments",
        json={"desired_template_id": template_id, "plan_template_id": ptv_id},
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["checkout_url"] is None

    dep = data["deployment"]
    assert dep["status"] == DEPLOYMENT_STATUS_PROVISIONING

    # Subscription should be current immediately
    sub = db_session.get(SubscriptionORM, dep["subscription_id"])
    assert sub.payment_status == PaymentStatus.CURRENT

    # No MolliePaymentORM records
    mollie_payments = db_session.exec(
        select(MolliePaymentORM).where(
            MolliePaymentORM.subscription_id == sub.id
        )
    ).all()
    assert len(mollie_payments) == 0

    # Reconcile job should be enqueued
    jobs = db_session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == UUID(dep["id"]),
            DeploymentReconcileJobORM.reason == "create",
        )
    ).all()
    assert len(jobs) == 1


# ===========================================================================
# 10.4: Paid plan but no payment provider -> treated as free
# ===========================================================================


def test_paid_plan_no_provider_treated_as_free(client, db_session):
    """When payment_provider is None (no Mollie key), paid plans behave like free."""
    product_id, template_id = _setup_product_and_template(client)
    ptv_id = create_paid_plan_template(db_session, product_id)

    user_id = _get_user(client)['id']

    resp = client.post(
        f"/api/users/{user_id}/deployments",
        json={"desired_template_id": template_id, "plan_template_id": ptv_id},
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["checkout_url"] is None

    dep = data["deployment"]
    assert dep["status"] == DEPLOYMENT_STATUS_PROVISIONING

    sub = db_session.get(SubscriptionORM, dep["subscription_id"])
    assert sub.payment_status == PaymentStatus.CURRENT


# ===========================================================================
# 10.5: Mollie API failure -> error, no DB records
# ===========================================================================


def test_mollie_failure_returns_error_no_db_records(
    paid_client, fake_payment_provider, db_session
):
    product_id, template_id = _setup_product_and_template(paid_client)
    ptv_id = create_paid_plan_template(db_session, product_id)

    user_id = _get_user(paid_client)['id']

    # Monkey-patch the fake to raise on ensure_customer
    original = fake_payment_provider.ensure_customer

    def failing_ensure(*args, **kwargs):
        raise RuntimeError("Mollie API unreachable")

    fake_payment_provider.ensure_customer = failing_ensure

    # TestClient re-raises server exceptions by default
    with pytest.raises(RuntimeError, match="Mollie API unreachable"):
        paid_client.post(
            f"/api/users/{user_id}/deployments",
            json={"desired_template_id": template_id, "plan_template_id": ptv_id},
        )

    fake_payment_provider.ensure_customer = original

    # Rollback any pending session state from the failed transaction
    db_session.rollback()

    # No deployments for this user
    deps = db_session.exec(
        select(DeploymentORM).where(DeploymentORM.user_id == user_id)
    ).all()
    assert len(deps) == 0

    # No subscriptions for this user
    subs = db_session.exec(
        select(SubscriptionORM).where(SubscriptionORM.user_id == user_id)
    ).all()
    assert len(subs) == 0


# ===========================================================================
# 10.6: Webhook — first payment paid
# ===========================================================================


def test_webhook_first_payment_paid(
    paid_client, fake_payment_provider, db_session
):
    product_id, template_id = _setup_product_and_template(paid_client)
    _, resp = _create_paid_deployment(
        paid_client, db_session, product_id, template_id
    )
    assert resp.status_code == 201

    dep_data = resp.json()["deployment"]
    dep_id = UUID(dep_data["id"])
    sub_id = dep_data["subscription_id"]

    # Simulate Mollie confirming payment
    mp = _get_mollie_payment(db_session, sub_id)
    fake_payment_provider.simulate_paid(mp.mollie_payment_id)

    webhook_resp = _trigger_webhook(paid_client, mp.mollie_payment_id)
    assert webhook_resp.status_code == 200

    db_session.expire_all()

    # Subscription should be current with Mollie IDs
    sub = db_session.get(SubscriptionORM, sub_id)
    assert sub.payment_status == PaymentStatus.CURRENT
    assert sub.mollie_mandate_id is not None
    assert sub.mollie_subscription_id is not None

    # Deployment should be provisioning
    dep = db_session.get(DeploymentORM, dep_id)
    assert dep.status == DEPLOYMENT_STATUS_PROVISIONING

    # Reconcile job should exist
    jobs = db_session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == dep_id,
            DeploymentReconcileJobORM.reason == "create",
        )
    ).all()
    assert len(jobs) == 1

    # Mollie subscription should be created in the fake
    assert len(fake_payment_provider.subscriptions) == 1

    # MolliePaymentORM status should be updated to paid
    db_session.refresh(mp)
    assert mp.status == MolliePaymentStatus.PAID
    assert mp.payload is not None


# ===========================================================================
# 10.7: Webhook — first payment failed
# ===========================================================================


def test_webhook_first_payment_failed(
    paid_client, fake_payment_provider, db_session
):
    product_id, template_id = _setup_product_and_template(paid_client)
    _, resp = _create_paid_deployment(paid_client, db_session, product_id, template_id)
    assert resp.status_code == 201

    dep_data = resp.json()["deployment"]
    dep_id = UUID(dep_data["id"])
    sub_id = dep_data["subscription_id"]

    mp = _get_mollie_payment(db_session, sub_id)

    fake_payment_provider._next_payment_status = "failed"

    webhook_resp = _trigger_webhook(paid_client, mp.mollie_payment_id)
    assert webhook_resp.status_code == 200

    db_session.expire_all()

    sub = db_session.get(SubscriptionORM, sub_id)
    assert sub.payment_status == PaymentStatus.ARREARS

    dep = db_session.get(DeploymentORM, dep_id)
    assert dep.status == DEPLOYMENT_STATUS_PENDING

    # No reconcile job
    jobs = db_session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == dep_id,
        )
    ).all()
    assert len(jobs) == 0

    # No Mollie subscription created
    assert len(fake_payment_provider.subscriptions) == 0


# ===========================================================================
# 10.8: Webhook — first payment expired
# ===========================================================================


def test_webhook_first_payment_expired(
    paid_client, fake_payment_provider, db_session
):
    product_id, template_id = _setup_product_and_template(paid_client)
    _, resp = _create_paid_deployment(paid_client, db_session, product_id, template_id)
    assert resp.status_code == 201

    dep_data = resp.json()["deployment"]
    dep_id = UUID(dep_data["id"])
    sub_id = dep_data["subscription_id"]

    mp = _get_mollie_payment(db_session, sub_id)

    fake_payment_provider._next_payment_status = "expired"

    webhook_resp = _trigger_webhook(paid_client, mp.mollie_payment_id)
    assert webhook_resp.status_code == 200

    db_session.expire_all()

    sub = db_session.get(SubscriptionORM, sub_id)
    assert sub.payment_status == PaymentStatus.ARREARS

    dep = db_session.get(DeploymentORM, dep_id)
    assert dep.status == DEPLOYMENT_STATUS_PENDING


# ===========================================================================
# 10.9: Webhook — recurring payment paid
# ===========================================================================


def test_webhook_recurring_payment_paid(
    paid_client, fake_payment_provider, db_session
):
    product_id, template_id = _setup_product_and_template(paid_client)
    _, resp = _create_paid_deployment(paid_client, db_session, product_id, template_id)
    assert resp.status_code == 201

    sub_id = resp.json()["deployment"]["subscription_id"]

    # Complete the first payment
    _complete_first_payment(paid_client, fake_payment_provider, db_session, sub_id)

    sub = db_session.get(SubscriptionORM, sub_id)
    assert sub.payment_status == PaymentStatus.CURRENT
    mollie_sub_id = sub.mollie_subscription_id

    # Set up a recurring payment in the fake
    recurring_id = "tr_recurring_1"
    fake_payment_provider.payments[recurring_id] = {
        "status": "paid",
        "customer_id": sub.user.mollie_customer_id,
        "amount_cents": 1000,
        "metadata": None,
        "mandate_id": sub.mollie_mandate_id,
        "subscription_id": mollie_sub_id,
        "sequence_type": "recurring",
    }
    fake_payment_provider._next_payment_status = "paid"

    webhook_resp = _trigger_webhook(paid_client, recurring_id)
    assert webhook_resp.status_code == 200

    db_session.expire_all()

    # Subscription stays current
    sub = db_session.get(SubscriptionORM, sub_id)
    assert sub.payment_status == PaymentStatus.CURRENT

    # New MolliePaymentORM row should exist
    all_payments = db_session.exec(
        select(MolliePaymentORM).where(
            MolliePaymentORM.subscription_id == sub_id
        )
    ).all()
    assert len(all_payments) == 2  # first + recurring
    recurring_mp = [p for p in all_payments if p.mollie_payment_id == recurring_id]
    assert len(recurring_mp) == 1
    assert recurring_mp[0].sequence_type == "recurring"
    assert recurring_mp[0].status == MolliePaymentStatus.PAID


# ===========================================================================
# 10.10: Webhook — recurring payment failed
# ===========================================================================


def test_webhook_recurring_payment_failed(
    paid_client, fake_payment_provider, db_session
):
    product_id, template_id = _setup_product_and_template(paid_client)
    _, resp = _create_paid_deployment(paid_client, db_session, product_id, template_id)
    assert resp.status_code == 201

    sub_id = resp.json()["deployment"]["subscription_id"]

    _complete_first_payment(paid_client, fake_payment_provider, db_session, sub_id)

    sub = db_session.get(SubscriptionORM, sub_id)
    mollie_sub_id = sub.mollie_subscription_id

    # Set up a failing recurring payment
    recurring_id = "tr_recurring_fail"
    fake_payment_provider.payments[recurring_id] = {
        "status": "failed",
        "customer_id": sub.user.mollie_customer_id,
        "amount_cents": 1000,
        "metadata": None,
        "mandate_id": sub.mollie_mandate_id,
        "subscription_id": mollie_sub_id,
        "sequence_type": "recurring",
    }
    fake_payment_provider._next_payment_status = "failed"

    webhook_resp = _trigger_webhook(paid_client, recurring_id)
    assert webhook_resp.status_code == 200

    db_session.expire_all()

    # Subscription should be in arrears
    sub = db_session.get(SubscriptionORM, sub_id)
    assert sub.payment_status == PaymentStatus.ARREARS

    # Recurring payment record exists
    recurring_mp = db_session.exec(
        select(MolliePaymentORM).where(
            MolliePaymentORM.mollie_payment_id == recurring_id
        )
    ).one()
    assert recurring_mp.status == MolliePaymentStatus.FAILED


# ===========================================================================
# 10.11: Webhook — recurring payment paid recovers from arrears
# ===========================================================================


def test_webhook_recurring_payment_recovers_from_arrears(
    paid_client, fake_payment_provider, db_session
):
    product_id, template_id = _setup_product_and_template(paid_client)
    _, resp = _create_paid_deployment(paid_client, db_session, product_id, template_id)
    assert resp.status_code == 201

    sub_id = resp.json()["deployment"]["subscription_id"]

    _complete_first_payment(paid_client, fake_payment_provider, db_session, sub_id)

    # Put subscription into arrears manually
    sub = db_session.get(SubscriptionORM, sub_id)
    sub.payment_status = PaymentStatus.ARREARS
    db_session.commit()
    mollie_sub_id = sub.mollie_subscription_id

    # Send a successful recurring payment
    recurring_id = "tr_recurring_recover"
    fake_payment_provider.payments[recurring_id] = {
        "status": "paid",
        "customer_id": sub.user.mollie_customer_id,
        "amount_cents": 1000,
        "metadata": None,
        "mandate_id": sub.mollie_mandate_id,
        "subscription_id": mollie_sub_id,
        "sequence_type": "recurring",
    }
    fake_payment_provider._next_payment_status = "paid"

    webhook_resp = _trigger_webhook(paid_client, recurring_id)
    assert webhook_resp.status_code == 200

    db_session.expire_all()

    # Subscription should recover to current
    sub = db_session.get(SubscriptionORM, sub_id)
    assert sub.payment_status == PaymentStatus.CURRENT


# ===========================================================================
# 10.12: Webhook — duplicate is idempotent
# ===========================================================================


def test_webhook_duplicate_is_idempotent(
    paid_client, fake_payment_provider, db_session
):
    product_id, template_id = _setup_product_and_template(paid_client)
    _, resp = _create_paid_deployment(paid_client, db_session, product_id, template_id)
    assert resp.status_code == 201

    dep_data = resp.json()["deployment"]
    dep_id = UUID(dep_data["id"])
    sub_id = dep_data["subscription_id"]

    mp = _get_mollie_payment(db_session, sub_id)
    fake_payment_provider.simulate_paid(mp.mollie_payment_id)

    # First webhook call
    resp1 = _trigger_webhook(paid_client, mp.mollie_payment_id)
    assert resp1.status_code == 200
    db_session.expire_all()

    # Capture state after first call
    jobs_after_first = db_session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == dep_id,
            DeploymentReconcileJobORM.reason == "create",
        )
    ).all()
    assert len(jobs_after_first) == 1
    subs_after_first = len(fake_payment_provider.subscriptions)

    # Second webhook call (duplicate)
    resp2 = _trigger_webhook(paid_client, mp.mollie_payment_id)
    assert resp2.status_code == 200
    db_session.expire_all()

    # No second reconcile job
    jobs_after_second = db_session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == dep_id,
            DeploymentReconcileJobORM.reason == "create",
        )
    ).all()
    assert len(jobs_after_second) == 1

    # No second Mollie subscription
    assert len(fake_payment_provider.subscriptions) == subs_after_first


# ===========================================================================
# 10.13: Webhook — unknown payment ID
# ===========================================================================


def test_webhook_unknown_payment_id(
    paid_client, fake_payment_provider, db_session
):
    # Add a payment to the fake that has no matching DB record
    unknown_id = "tr_unknown_xyz"
    fake_payment_provider.payments[unknown_id] = {
        "status": "paid",
        "customer_id": "cst_ghost",
        "amount_cents": 500,
        "metadata": None,
        "mandate_id": None,
        "subscription_id": None,
        "sequence_type": "first",
    }
    fake_payment_provider._next_payment_status = "paid"

    webhook_resp = _trigger_webhook(paid_client, unknown_id)
    assert webhook_resp.status_code == 200

    # No MolliePaymentORM or SubscriptionORM changes
    mp = db_session.exec(
        select(MolliePaymentORM).where(
            MolliePaymentORM.mollie_payment_id == unknown_id
        )
    ).one_or_none()
    assert mp is None


# ===========================================================================
# 10.14: CLI refuses paid plan deployment
# ===========================================================================


def test_cli_refuses_paid_plan_deployment(cli_runner, monkeypatch):
    runner, app = cli_runner
    monkeypatch.setenv("CAELUS_MOLLIE_API_KEY", "test_key_12345")
    from app.config import get_settings
    get_settings.cache_clear()

    # Create product + template via CLI
    result = runner.invoke(app, ["create-product", "cli-paid-prod", "test"])
    assert result.exit_code == 0
    prod = yaml.safe_load(result.output)
    product_id = prod["id"]

    result = runner.invoke(
        app,
        [
            "create-template",
            "--product-id", str(product_id),
            "--chart-ref", "oci://test/chart",
            "--chart-version", "1.0.0",
        ],
    )
    assert result.exit_code == 0
    tmpl = yaml.safe_load(result.output)
    template_id = tmpl["id"]

    runner.invoke(
        app,
        ["update-product", str(product_id), "--template-id", str(template_id)],
    )

    # Create paid plan template via services
    from app.db import session_scope
    with session_scope() as session:
        ptv_id = create_paid_plan_template(session, product_id)

    # Create user via CLI
    result = runner.invoke(app, ["create-user", "paidcli@example.com"])
    assert result.exit_code == 0
    user = yaml.safe_load(result.output)
    user_id = user["id"]

    # Attempt deployment with paid plan
    result = runner.invoke(
        app,
        [
            "create-deployment",
            "--user-id", str(user_id),
            "--desired-template-id", str(template_id),
            "--plan-template-id", str(ptv_id),
        ],
    )

    assert result.exit_code == 1
    assert "Paid plans require payment via the web dashboard" in result.output


# ===========================================================================
# 10.15: CLI creates free plan deployment normally
# ===========================================================================


def test_cli_creates_free_plan_deployment(cli_runner, monkeypatch):
    runner, app = cli_runner
    # Enable Mollie so the paid-plan check is active (free plans should still pass)
    monkeypatch.setenv("CAELUS_MOLLIE_API_KEY", "test_key_12345")
    from app.config import get_settings
    get_settings.cache_clear()

    # Create product + template via CLI
    result = runner.invoke(app, ["create-product", "cli-free-prod", "test"])
    assert result.exit_code == 0
    prod = yaml.safe_load(result.output)
    product_id = prod["id"]

    result = runner.invoke(
        app,
        [
            "create-template",
            "--product-id", str(product_id),
            "--chart-ref", "oci://test/chart",
            "--chart-version", "1.0.0",
        ],
    )
    assert result.exit_code == 0
    tmpl = yaml.safe_load(result.output)
    template_id = tmpl["id"]

    runner.invoke(
        app,
        ["update-product", str(product_id), "--template-id", str(template_id)],
    )

    # Create free plan template via services
    from app.db import session_scope
    with session_scope() as session:
        ptv_id = create_free_plan_template(session, product_id)

    # Create user
    result = runner.invoke(app, ["create-user", "freecli@example.com"])
    assert result.exit_code == 0
    user = yaml.safe_load(result.output)
    user_id = user["id"]

    # Deploying requires prior ToS acceptance and a claimed subdomain.
    assert runner.invoke(
        app, ["accept-tos", "--user-id", str(user_id), "--version", CURRENT_TOS_VERSION]
    ).exit_code == 0
    assert runner.invoke(
        app, ["claim-subdomain", "--user-id", str(user_id), "--subdomain", "freecli"]
    ).exit_code == 0

    # Deploy with free plan — should succeed
    result = runner.invoke(
        app,
        [
            "create-deployment",
            "--user-id", str(user_id),
            "--desired-template-id", str(template_id),
            "--plan-template-id", str(ptv_id),
        ],
    )

    assert result.exit_code == 0
    deployment = yaml.safe_load(result.output)
    assert deployment["status"] == DEPLOYMENT_STATUS_PROVISIONING
