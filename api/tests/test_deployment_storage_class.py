"""Choosing a deployment's storage class at create
(openspec deployment-storage-class)."""

from __future__ import annotations

import pytest
from sqlmodel import func, select

from app.config import get_settings
from app.models import DeploymentORM, DeploymentReleaseORM, ProductORM, SubscriptionORM, UserORM
from app.services import deployments, products, templates
from app.services.errors import ValidationException
from tests.conftest import create_free_plan_template, create_user, make_accepted_user


@pytest.fixture
def allow(monkeypatch):
    def _allow(*classes: str) -> None:
        settings = get_settings().model_copy(update={"storage_classes": list(classes)})
        monkeypatch.setattr("app.services.deployments.get_settings", lambda: settings)

    return _allow


def _flag(db_session, user_id: int, storage_class: str | None) -> None:
    user = db_session.get(UserORM, user_id)
    user.storage_class = storage_class
    db_session.add(user)
    db_session.commit()


def _template(db_session, name: str):
    product = products.create_product(
        db_session, payload=products.ProductCreate(name=name, description="d")
    )
    template = templates.create_template(
        db_session,
        payload=templates.ProductTemplateVersionCreate(
            product_id=product.id,
            chart_ref="oci://example/chart",
            chart_version="1.0.0",
            values_schema_json={"type": "object", "additionalProperties": False},
        ),
    )
    product_orm = db_session.get(ProductORM, product.id)
    product_orm.template_id = template.id
    db_session.add(product_orm)
    db_session.commit()
    return template, create_free_plan_template(db_session, product.id)


def _create(db_session, user_id: int, name: str):
    template, ptv_id = _template(db_session, name)
    return deployments.create_deployment(
        db_session,
        payload=deployments.DeploymentCreate(
            user_id=user_id, desired_template_id=template.id, plan_template_id=ptv_id
        ),
    )


def _count(db_session, model) -> int:
    return db_session.exec(select(func.count()).select_from(model)).one()


def test_a_flagged_account_records_its_class(db_session, allow):
    allow("ceph-freepod")
    user = make_accepted_user(db_session, "flagged@example.com")
    _flag(db_session, user.id, "ceph-freepod")
    created = _create(db_session, user.id, "flagged-product")
    assert db_session.get(DeploymentORM, created.deployment.id).storage_class == "ceph-freepod"


def test_an_unflagged_account_records_none(db_session, allow):
    allow("ceph-freepod")
    user = make_accepted_user(db_session, "unflagged@example.com")
    created = _create(db_session, user.id, "unflagged-product")
    assert db_session.get(DeploymentORM, created.deployment.id).storage_class is None


def test_an_administrator_creating_for_a_flagged_owner_records_the_owners_class(client, db_session, allow):
    allow("ceph-freepod")
    owner_id = create_user(client, "owner@example.com")["id"]
    _flag(db_session, owner_id, "ceph-freepod")
    template, ptv_id = _template(db_session, "admin-product")
    resp = client.post(
        f"/api/users/{owner_id}/deployments",
        json={"desired_template_id": template.id, "plan_template_id": ptv_id},
    )
    assert resp.status_code == 201
    deployment = db_session.get(DeploymentORM, resp.json()["deployment"]["id"])
    assert deployment.storage_class == "ceph-freepod"


@pytest.mark.parametrize("allowed", [["ceph-freepod-dev"], []], ids=["other-class", "empty-list"])
def test_an_unlisted_class_is_refused_and_nothing_is_stored(db_session, allow, allowed):
    allow(*allowed)
    user = make_accepted_user(db_session, "prodflag@example.com")
    _flag(db_session, user.id, "ceph-freepod")
    template, ptv_id = _template(db_session, "refused-product")
    before = {m: _count(db_session, m) for m in (DeploymentORM, DeploymentReleaseORM, SubscriptionORM)}
    with pytest.raises(ValidationException, match="ceph-freepod"):
        deployments.create_deployment(
            db_session,
            payload=deployments.DeploymentCreate(
                user_id=user.id, desired_template_id=template.id, plan_template_id=ptv_id
            ),
        )
    db_session.rollback()
    assert {m: _count(db_session, m) for m in before} == before


def test_clearing_an_accounts_class_keeps_existing_deployments(db_session, allow):
    allow("ceph-freepod")
    user = make_accepted_user(db_session, "cleared@example.com")
    _flag(db_session, user.id, "ceph-freepod")
    first = _create(db_session, user.id, "cleared-first")
    _flag(db_session, user.id, None)
    second = _create(db_session, user.id, "cleared-second")
    assert db_session.get(DeploymentORM, first.deployment.id).storage_class == "ceph-freepod"
    assert db_session.get(DeploymentORM, second.deployment.id).storage_class is None
