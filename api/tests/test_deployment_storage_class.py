"""Choosing a deployment's storage class at create
(openspec default-storage-class)."""

from __future__ import annotations

import pytest
from sqlmodel import func, select

from app.config import get_settings
from app.models import DeploymentORM, DeploymentReleaseORM, ProductORM, SubscriptionORM
from app.services import deployments, products, templates
from app.services.errors import ValidationException
from tests.conftest import create_free_plan_template, create_user, make_accepted_user


@pytest.fixture
def environment(monkeypatch):
    def _environment(storage_class: str | None, *allowed: str) -> None:
        settings = get_settings().model_copy(
            update={"storage_class": storage_class, "storage_classes": list(allowed)}
        )
        monkeypatch.setattr("app.services.deployments.get_settings", lambda: settings)

    return _environment


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


def test_every_account_records_the_environments_class(db_session, environment):
    environment("ceph-freepod", "ceph-freepod")
    user = make_accepted_user(db_session, "anyone@example.com")
    created = _create(db_session, user.id, "env-product")
    assert db_session.get(DeploymentORM, created.deployment.id).storage_class == "ceph-freepod"


def test_an_environment_naming_no_class_records_none(db_session, environment):
    environment(None, "ceph-freepod")
    user = make_accepted_user(db_session, "noclass@example.com")
    created = _create(db_session, user.id, "noclass-product")
    assert db_session.get(DeploymentORM, created.deployment.id).storage_class is None


def test_an_administrator_creating_for_another_account_records_the_environments_class(
    client, db_session, environment
):
    environment("ceph-freepod", "ceph-freepod")
    owner_id = create_user(client, "owner@example.com")["id"]
    template, ptv_id = _template(db_session, "admin-product")
    resp = client.post(
        f"/api/users/{owner_id}/deployments",
        json={"desired_template_id": template.id, "plan_template_id": ptv_id},
    )
    assert resp.status_code == 201
    deployment = db_session.get(DeploymentORM, resp.json()["deployment"]["id"])
    assert deployment.storage_class == "ceph-freepod"


@pytest.mark.parametrize("allowed", [["ceph-freepod-dev"], []], ids=["other-class", "empty-list"])
def test_an_unlisted_class_is_refused_and_nothing_is_stored(db_session, environment, allowed):
    environment("ceph-freepod", *allowed)
    user = make_accepted_user(db_session, "unlisted@example.com")
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


def test_changing_the_environments_class_keeps_existing_deployments(db_session, environment):
    environment("ceph-freepod", "ceph-freepod", "ceph-freepod-next")
    user = make_accepted_user(db_session, "changed@example.com")
    first = _create(db_session, user.id, "changed-first")
    environment("ceph-freepod-next", "ceph-freepod", "ceph-freepod-next")
    second = _create(db_session, user.id, "changed-second")
    assert db_session.get(DeploymentORM, first.deployment.id).storage_class == "ceph-freepod"
    assert db_session.get(DeploymentORM, second.deployment.id).storage_class == "ceph-freepod-next"
