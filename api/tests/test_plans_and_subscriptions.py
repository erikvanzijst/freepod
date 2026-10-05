"""Tests for plans and subscriptions (spec tasks 11.1–11.5)."""

import pytest
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.models import (
    BillingInterval,
    DeploymentORM,
    PaymentStatus,
    PlanCreate,
    PlanORM,
    PlanRead,
    PlanTemplateVersionORM,
    PlanUpdate,
    ProductORM,
    SubscriptionORM,
    SubscriptionRead,
    SubscriptionStatus,
)
from app.models.core import _utcnow
from app.services import deployments, plans, products, subscriptions, templates, users
from app.services.errors import (
    IntegrityException,
    NotFoundException,
    ValidationException,
)
from tests.conftest import create_free_plan_template, db_session, make_accepted_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(session, name="TestProduct"):
    return products.create_product(
        session, payload=products.ProductCreate(name=name, description="desc")
    )


def _make_user(session, email="plantest@example.com"):
    return make_accepted_user(session, email)


def _make_plan(session, product_id, name="Basic", sort_order=None):
    return plans.create_plan(
        session,
        product_id=product_id,
        payload=PlanCreate(name=name, sort_order=sort_order),
    )


def _make_template_version(session, plan_id, price_cents=1000):
    return plans.create_plan_template_version(
        session,
        plan_id=plan_id,
        payload=plans.PlanTemplateVersionCreate(
            price_cents=price_cents,
            billing_interval=BillingInterval.MONTHLY,
        ),
    )


def _make_plan_with_template(session, product_id, name="Basic", price_cents=1000, sort_order=None):
    """Create a plan, a template version, and set it as the canonical template."""
    plan = _make_plan(session, product_id, name=name, sort_order=sort_order)
    tmpl = _make_template_version(session, plan.id, price_cents=price_cents)
    plans.update_plan(
        session, plan_id=plan.id, payload=PlanUpdate(template_id=tmpl.id)
    )
    return plan, tmpl


# ===========================================================================
# 11.1 — Plan model tests
# ===========================================================================


class TestPlanModel:
    def test_create_plan_for_product(self, db_session):
        product = _make_product(db_session)
        plan = PlanORM(name="Starter", product_id=product.id, created_at=_utcnow())
        db_session.add(plan)
        db_session.commit()
        db_session.refresh(plan)

        assert plan.id is not None
        assert plan.name == "Starter"
        assert plan.product_id == product.id
        assert plan.deleted_at is None

    def test_create_plan_template_version(self, db_session):
        product = _make_product(db_session)
        plan = PlanORM(name="Pro", product_id=product.id, created_at=_utcnow())
        db_session.add(plan)
        db_session.flush()

        ptv = PlanTemplateVersionORM(
            plan_id=plan.id,
            price_cents=2500,
            billing_interval=BillingInterval.ANNUAL,
            storage_bytes=1024,
            created_at=_utcnow(),
        )
        db_session.add(ptv)
        db_session.commit()
        db_session.refresh(ptv)

        assert ptv.id is not None
        assert ptv.plan_id == plan.id
        assert ptv.price_cents == 2500
        assert ptv.billing_interval == BillingInterval.ANNUAL

    def test_update_canonical_template(self, db_session):
        product = _make_product(db_session)
        plan = PlanORM(name="Flex", product_id=product.id, created_at=_utcnow())
        db_session.add(plan)
        db_session.flush()

        ptv1 = PlanTemplateVersionORM(
            plan_id=plan.id, price_cents=100, billing_interval=BillingInterval.MONTHLY, created_at=_utcnow()
        )
        db_session.add(ptv1)
        db_session.flush()
        plan.template_id = ptv1.id
        db_session.commit()
        db_session.refresh(plan)
        assert plan.template_id == ptv1.id

        ptv2 = PlanTemplateVersionORM(
            plan_id=plan.id, price_cents=200, billing_interval=BillingInterval.MONTHLY, created_at=_utcnow()
        )
        db_session.add(ptv2)
        db_session.flush()
        plan.template_id = ptv2.id
        db_session.commit()
        db_session.refresh(plan)
        assert plan.template_id == ptv2.id

    def test_soft_delete_plan(self, db_session):
        product = _make_product(db_session)
        plan = PlanORM(name="Deletable", product_id=product.id, created_at=_utcnow())
        db_session.add(plan)
        db_session.commit()
        db_session.refresh(plan)

        plan.deleted_at = datetime.now(UTC)
        db_session.commit()
        db_session.refresh(plan)
        assert plan.deleted_at is not None

    def test_partial_unique_index_duplicate_name_same_product_fails(self, db_session):
        product = _make_product(db_session)
        p1 = PlanORM(name="Unique", product_id=product.id, created_at=_utcnow())
        db_session.add(p1)
        db_session.commit()

        p2 = PlanORM(name="Unique", product_id=product.id, created_at=_utcnow())
        db_session.add(p2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_partial_unique_index_same_name_different_product_succeeds(self, db_session):
        prod_a = _make_product(db_session, name="ProdA")
        prod_b = _make_product(db_session, name="ProdB")

        p1 = PlanORM(name="Shared", product_id=prod_a.id, created_at=_utcnow())
        p2 = PlanORM(name="Shared", product_id=prod_b.id, created_at=_utcnow())
        db_session.add_all([p1, p2])
        db_session.commit()

        assert p1.id != p2.id

    def test_partial_unique_index_reuse_after_soft_delete(self, db_session):
        product = _make_product(db_session)
        p1 = PlanORM(name="Reusable", product_id=product.id, created_at=_utcnow())
        db_session.add(p1)
        db_session.commit()

        p1.deleted_at = datetime.now(UTC)
        db_session.commit()

        p2 = PlanORM(name="Reusable", product_id=product.id, created_at=_utcnow())
        db_session.add(p2)
        db_session.commit()
        assert p2.id != p1.id


# ===========================================================================
# 11.2 — Subscription model tests
# ===========================================================================


class TestSubscriptionModel:
    def test_create_subscription(self, db_session):
        product = _make_product(db_session, name="SubProd")
        user = _make_user(db_session, email="subuser@example.com")
        ptv_id = create_free_plan_template(db_session, product.id)

        sub = SubscriptionORM(
            plan_template_id=ptv_id,
            user_id=user.id,
            created_at=_utcnow(),
        )
        db_session.add(sub)
        db_session.commit()
        db_session.refresh(sub)

        assert sub.id is not None
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.payment_status == PaymentStatus.CURRENT
        assert sub.cancelled_at is None

    def test_cancel_subscription_sets_status_and_cancelled_at(self, db_session):
        product = _make_product(db_session, name="CancelProd")
        user = _make_user(db_session, email="cancel@example.com")
        ptv_id = create_free_plan_template(db_session, product.id)

        sub = SubscriptionORM(
            plan_template_id=ptv_id, user_id=user.id, created_at=_utcnow()
        )
        db_session.add(sub)
        db_session.commit()
        db_session.refresh(sub)

        sub.status = SubscriptionStatus.CANCELLED
        sub.cancelled_at = datetime.now(UTC)
        db_session.commit()
        db_session.refresh(sub)

        assert sub.status == SubscriptionStatus.CANCELLED
        assert sub.cancelled_at is not None

    def test_status_and_payment_status_independent_arrears_while_active(self, db_session):
        product = _make_product(db_session, name="IndepProd1")
        user = _make_user(db_session, email="indep1@example.com")
        ptv_id = create_free_plan_template(db_session, product.id)

        sub = SubscriptionORM(
            plan_template_id=ptv_id, user_id=user.id, created_at=_utcnow()
        )
        db_session.add(sub)
        db_session.commit()

        sub.payment_status = PaymentStatus.ARREARS
        db_session.commit()
        db_session.refresh(sub)

        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.payment_status == PaymentStatus.ARREARS

    def test_status_and_payment_status_independent_cancelled_while_arrears(self, db_session):
        product = _make_product(db_session, name="IndepProd2")
        user = _make_user(db_session, email="indep2@example.com")
        ptv_id = create_free_plan_template(db_session, product.id)

        sub = SubscriptionORM(
            plan_template_id=ptv_id, user_id=user.id, created_at=_utcnow()
        )
        db_session.add(sub)
        db_session.commit()

        sub.payment_status = PaymentStatus.ARREARS
        sub.status = SubscriptionStatus.CANCELLED
        sub.cancelled_at = datetime.now(UTC)
        db_session.commit()
        db_session.refresh(sub)

        assert sub.status == SubscriptionStatus.CANCELLED
        assert sub.payment_status == PaymentStatus.ARREARS


# ===========================================================================
# 11.3 — Plan service tests
# ===========================================================================


class TestPlanService:
    # -- create_plan --

    def test_create_plan_success(self, db_session):
        product = _make_product(db_session, name="SvcProd")
        result = plans.create_plan(
            db_session,
            product_id=product.id,
            payload=PlanCreate(name="Gold"),
        )
        assert result.name == "Gold"
        assert result.product_id == product.id
        assert isinstance(result, PlanRead)

    def test_create_plan_product_not_found(self, db_session):
        with pytest.raises(NotFoundException, match="Product"):
            plans.create_plan(
                db_session,
                product_id=99999,
                payload=PlanCreate(name="Ghost"),
            )

    def test_create_plan_duplicate_name(self, db_session):
        product = _make_product(db_session, name="DupPlanProd")
        plans.create_plan(
            db_session,
            product_id=product.id,
            payload=PlanCreate(name="Dup"),
        )
        with pytest.raises(IntegrityException):
            plans.create_plan(
                db_session,
                product_id=product.id,
                payload=PlanCreate(name="Dup"),
            )

    # -- get_plan --

    def test_get_plan_success(self, db_session):
        product = _make_product(db_session, name="GetPlanProd")
        created = _make_plan(db_session, product.id, name="Visible")
        fetched = plans.get_plan(db_session, created.id)
        assert fetched.id == created.id
        assert fetched.name == "Visible"

    def test_get_plan_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            plans.get_plan(db_session, 99999)

    def test_get_plan_soft_deleted_returns_not_found(self, db_session):
        product = _make_product(db_session, name="SoftDelGetProd")
        created = _make_plan(db_session, product.id, name="WillDelete")
        plans.delete_plan(db_session, plan_id=created.id)

        with pytest.raises(NotFoundException):
            plans.get_plan(db_session, created.id)

    # -- list_plans_for_product --

    def test_list_plans_excludes_deleted(self, db_session):
        product = _make_product(db_session, name="ListProd")
        p1 = _make_plan(db_session, product.id, name="Keep")
        p2 = _make_plan(db_session, product.id, name="Remove")
        plans.delete_plan(db_session, plan_id=p2.id)

        result = plans.list_plans_for_product(db_session, product.id)
        ids = [p.id for p in result]
        assert p1.id in ids
        assert p2.id not in ids

    def test_list_plans_ordered_by_sort_order(self, db_session):
        product = _make_product(db_session, name="SortProd")
        _make_plan(db_session, product.id, name="Third", sort_order=3)
        _make_plan(db_session, product.id, name="First", sort_order=1)
        _make_plan(db_session, product.id, name="Second", sort_order=2)

        result = plans.list_plans_for_product(db_session, product.id)
        names = [p.name for p in result]
        assert names == ["First", "Second", "Third"]

    # -- update_plan --

    def test_update_plan_rename(self, db_session):
        product = _make_product(db_session, name="RenameProd")
        created = _make_plan(db_session, product.id, name="OldName")
        updated = plans.update_plan(
            db_session, plan_id=created.id, payload=PlanUpdate(name="NewName")
        )
        assert updated.name == "NewName"

    def test_update_plan_canonical_template(self, db_session):
        product = _make_product(db_session, name="CanonProd")
        plan = _make_plan(db_session, product.id, name="Canon")
        tmpl = _make_template_version(db_session, plan.id)
        updated = plans.update_plan(
            db_session, plan_id=plan.id, payload=PlanUpdate(template_id=tmpl.id)
        )
        assert updated.template_id == tmpl.id

    def test_update_plan_template_from_wrong_plan_rejected(self, db_session):
        product = _make_product(db_session, name="WrongTmplProd")
        plan_a = _make_plan(db_session, product.id, name="PlanA")
        plan_b = _make_plan(db_session, product.id, name="PlanB")
        tmpl_b = _make_template_version(db_session, plan_b.id)

        with pytest.raises(NotFoundException):
            plans.update_plan(
                db_session,
                plan_id=plan_a.id,
                payload=PlanUpdate(template_id=tmpl_b.id),
            )

    # -- delete_plan --

    def test_delete_plan_soft_deletes(self, db_session):
        product = _make_product(db_session, name="DelPlanProd")
        created = _make_plan(db_session, product.id, name="ToDel")
        deleted = plans.delete_plan(db_session, plan_id=created.id)
        assert deleted.id == created.id

        # Verify it is soft-deleted at the ORM level
        orm = db_session.get(PlanORM, created.id)
        assert orm.deleted_at is not None

    def test_delete_plan_already_deleted_returns_not_found(self, db_session):
        product = _make_product(db_session, name="AlreadyDelProd")
        created = _make_plan(db_session, product.id, name="AlreadyDel")
        plans.delete_plan(db_session, plan_id=created.id)

        with pytest.raises(NotFoundException):
            plans.delete_plan(db_session, plan_id=created.id)


# ===========================================================================
# 11.4 — Subscription service tests
# ===========================================================================


class TestSubscriptionService:
    def test_create_subscription_success(self, db_session):
        product = _make_product(db_session, name="SubSvcProd")
        user = _make_user(db_session, email="subsvc@example.com")
        ptv_id = create_free_plan_template(db_session, product.id)

        sub = subscriptions.create_subscription(
            db_session, plan_template_id=ptv_id, user_id=user.id
        )
        assert sub.id is not None
        assert sub.plan_template_id == ptv_id
        assert sub.user_id == user.id
        assert sub.status == SubscriptionStatus.ACTIVE

    def test_create_subscription_invalid_plan_template_raises_validation(self, db_session):
        user = _make_user(db_session, email="badsub@example.com")
        with pytest.raises(ValidationException):
            subscriptions.create_subscription(
                db_session, plan_template_id=99999, user_id=user.id
            )

    def test_cancel_subscription_success(self, db_session):
        product = _make_product(db_session, name="CancelSvcProd")
        user = _make_user(db_session, email="cancelsvc@example.com")
        ptv_id = create_free_plan_template(db_session, product.id)

        sub = subscriptions.create_subscription(
            db_session, plan_template_id=ptv_id, user_id=user.id
        )
        result = subscriptions.cancel_subscription(
            db_session, subscription_id=sub.id
        )
        assert result.status == SubscriptionStatus.CANCELLED
        assert result.cancelled_at is not None

    def test_cancel_subscription_idempotent(self, db_session):
        product = _make_product(db_session, name="IdempCancelProd")
        user = _make_user(db_session, email="idemcancel@example.com")
        ptv_id = create_free_plan_template(db_session, product.id)

        sub = subscriptions.create_subscription(
            db_session, plan_template_id=ptv_id, user_id=user.id
        )
        first = subscriptions.cancel_subscription(db_session, subscription_id=sub.id)
        second = subscriptions.cancel_subscription(db_session, subscription_id=sub.id)

        # No error; cancelled_at should not change
        assert first.cancelled_at == second.cancelled_at
        assert second.status == SubscriptionStatus.CANCELLED

    def test_cancel_subscription_sets_cancelled_at(self, db_session):
        product = _make_product(db_session, name="CancelAtProd")
        user = _make_user(db_session, email="cancelat@example.com")
        ptv_id = create_free_plan_template(db_session, product.id)

        sub = subscriptions.create_subscription(
            db_session, plan_template_id=ptv_id, user_id=user.id
        )
        assert sub.cancelled_at is None

        result = subscriptions.cancel_subscription(db_session, subscription_id=sub.id)
        assert result.cancelled_at is not None

    def test_list_subscriptions_for_user_returns_active_and_cancelled(self, db_session):
        product = _make_product(db_session, name="ListSubProd")
        user = _make_user(db_session, email="listsub@example.com")
        ptv_id = create_free_plan_template(db_session, product.id)

        sub_active = subscriptions.create_subscription(
            db_session, plan_template_id=ptv_id, user_id=user.id
        )
        sub_cancel = subscriptions.create_subscription(
            db_session, plan_template_id=ptv_id, user_id=user.id
        )
        subscriptions.cancel_subscription(db_session, subscription_id=sub_cancel.id)

        result = subscriptions.list_subscriptions_for_user(db_session, user.id)
        ids = [s.id for s in result]
        assert sub_active.id in ids
        assert sub_cancel.id in ids

        statuses = {s.id: s.status for s in result}
        assert statuses[sub_active.id] == SubscriptionStatus.ACTIVE
        assert statuses[sub_cancel.id] == SubscriptionStatus.CANCELLED

    def test_update_payment_status_success(self, db_session):
        product = _make_product(db_session, name="PayStatProd")
        user = _make_user(db_session, email="paystat@example.com")
        ptv_id = create_free_plan_template(db_session, product.id)

        sub = subscriptions.create_subscription(
            db_session, plan_template_id=ptv_id, user_id=user.id
        )
        assert sub.payment_status == PaymentStatus.CURRENT

        result = subscriptions.update_payment_status(
            db_session, subscription_id=sub.id, payment_status=PaymentStatus.ARREARS
        )
        assert result.payment_status == PaymentStatus.ARREARS


# ===========================================================================
# 11.5 — Deployment service tests (atomic subscription creation)
# ===========================================================================


class TestDeploymentSubscriptionAtomic:
    """Verify that deployment creation atomically creates a subscription."""

    def _setup_product_with_template(self, db_session, name="AtomicProd"):
        user = _make_user(db_session, email=f"{name.lower()}@example.com")
        product = _make_product(db_session, name=name)
        template = templates.create_template(
            db_session,
            payload=templates.ProductTemplateVersionCreate(
                product_id=product.id,
                chart_ref="oci://example/chart",
                chart_version="1.0.0",
                values_schema_json={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"domain": {"type": "string", "title": "hostname"}},
                },
            ),
        )
        # Set canonical template on the product
        product_orm = db_session.get(ProductORM, product.id)
        product_orm.template_id = template.id
        db_session.add(product_orm)
        db_session.commit()
        ptv_id = create_free_plan_template(db_session, product.id)
        return user, product, template, ptv_id

    def test_atomic_creation_deployment_and_subscription(self, db_session):
        user, product, template, ptv_id = self._setup_product_with_template(
            db_session, name="AtomicCreate"
        )

        dep = deployments.create_deployment(
            db_session,
            payload=deployments.DeploymentCreate(
                user_id=user.id,
                desired_template_id=template.id,
                user_values_json={"domain": "atomic.example.com"},
                plan_template_id=ptv_id,
            ),
        ).deployment

        assert dep.subscription_id is not None

        # Verify the subscription actually exists in the DB
        sub = db_session.get(SubscriptionORM, dep.subscription_id)
        assert sub is not None
        assert sub.user_id == user.id
        assert sub.plan_template_id == ptv_id

    def test_rollback_hostname_conflict_no_subscription_created(self, db_session):
        user, product, template, ptv_id = self._setup_product_with_template(
            db_session, name="RollbackProd"
        )

        # Create the first deployment to claim the hostname
        deployments.create_deployment(
            db_session,
            payload=deployments.DeploymentCreate(
                user_id=user.id,
                desired_template_id=template.id,
                user_values_json={"domain": "conflict.example.com"},
                plan_template_id=ptv_id,
            ),
        )

        # Count subscriptions before the failed attempt
        subs_before = db_session.exec(
            select(SubscriptionORM).where(SubscriptionORM.user_id == user.id)
        ).all()
        count_before = len(subs_before)

        # Attempt a second deployment with the same hostname — should fail
        from app.services.errors import HostnameException

        with pytest.raises(HostnameException):
            deployments.create_deployment(
                db_session,
                payload=deployments.DeploymentCreate(
                    user_id=user.id,
                    desired_template_id=template.id,
                    user_values_json={"domain": "conflict.example.com"},
                    plan_template_id=ptv_id,
                ),
            )

        # Subscription count should not have increased
        subs_after = db_session.exec(
            select(SubscriptionORM).where(SubscriptionORM.user_id == user.id)
        ).all()
        assert len(subs_after) == count_before
