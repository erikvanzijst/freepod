"""The `user.subdomain` column.

The label an account's applications are addressed under and its certificate is
issued for. Claiming it is `account-subdomain-claim`; what is here is the column
those endpoints will write, and the reconciler's refusal to proceed without one.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.models import ProductORM, ProductTemplateVersionORM, UserORM
from app.models.core import _utcnow
from app.services.errors import IntegrityException
from app.services.reconcile_constants import DEPLOYMENT_STATUS_PROVISIONING
from app.services.reconcile import DeploymentReconciler


@pytest.fixture
def session(test_database, db_session):
    with Session(test_database.engine) as session:
        yield session


def test_subdomain_is_null_until_claimed(session):
    user = UserORM(email=f"u-{uuid4().hex[:8]}@example.com")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.subdomain is None


def test_two_accounts_cannot_hold_the_same_label(session):
    token = uuid4().hex[:8]
    session.add(UserORM(email=f"a-{token}@example.com", subdomain=f"dup{token}"))
    session.commit()

    session.add(UserORM(email=f"b-{token}@example.com", subdomain=f"dup{token}"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_the_label_is_taken_case_insensitively(session):
    token = uuid4().hex[:8]
    session.add(UserORM(email=f"a-{token}@example.com", subdomain=f"case{token}"))
    session.commit()

    session.add(UserORM(email=f"b-{token}@example.com", subdomain=f"CASE{token}".upper()))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_a_deleted_account_keeps_its_label(session):
    """The index only scopes uniqueness to live rows; refusing to re-issue a
    dead account's label is the claim service's job (account-subdomain-claim)."""
    token = uuid4().hex[:8]
    gone = UserORM(
        email=f"gone-{token}@example.com",
        subdomain=f"held{token}",
        deleted_at=_utcnow() - timedelta(days=1),
    )
    session.add(gone)
    session.commit()
    session.refresh(gone)
    assert gone.subdomain == f"held{token}"


def test_many_accounts_may_hold_none(session):
    token = uuid4().hex[:8]
    session.add(UserORM(email=f"n1-{token}@example.com"))
    session.add(UserORM(email=f"n2-{token}@example.com"))
    session.commit()


@pytest.fixture
def deployment_factory(session):
    def make(*, subdomain):
        token = uuid4().hex[:8]
        user = UserORM(email=f"sd-{token}@example.com", subdomain=subdomain)
        product = ProductORM(name=f"sd-product-{token}", created_at=_utcnow())
        session.add(user)
        session.add(product)
        session.commit()
        template = ProductTemplateVersionORM(
            product_id=product.id, chart_ref="oci://example/chart", chart_version="1.0.0"
        )
        session.add(template)
        session.commit()

        from tests.conftest import make_deployment_with_release

        deployment = make_deployment_with_release(
            session,
            user_id=user.id,
            desired_template_id=template.id,
            hostname=f"{token}.example.test",
            name=f"app-{token}",
            namespace=f"ns-{token}",
            status=DEPLOYMENT_STATUS_PROVISIONING,
        )
        session.commit()
        session.refresh(deployment)
        return deployment

    return make


def test_reconcile_refuses_a_deployment_whose_owner_holds_no_label(deployment_factory):
    with pytest.raises(IntegrityException) as exc:
        DeploymentReconciler._validate_input_state(deployment_factory(subdomain=None))
    assert "subdomain" in str(exc.value)


def test_reconcile_accepts_a_deployment_whose_owner_holds_one(deployment_factory):
    DeploymentReconciler._validate_input_state(deployment_factory(subdomain="erik"))
