"""Deploying requires the owning account to hold a handle, and a tenant
hostname to end in it."""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.config import CaelusSettings
from app.models import (
    DeploymentORM,
    DeploymentReconcileJobORM,
    ProductORM,
    ProductTemplateVersionORM,
    UserORM,
)
from app.services import deployments, products, templates, users
from app.services.deployments import HandleRequired
from app.services.errors import HostnameException, ValidationException
from app.services.reconcile_constants import DEPLOYMENT_STATUS_READY
from tests.conftest import CURRENT_TOS_VERSION, create_free_plan_template, make_accepted_user

TENANT = CaelusSettings(
    domain="",
    tenant_domain="freepod.app",
    platform_domains=["freepod.eu", "freepod.app"],
    _env_file=None,
)


@pytest.fixture
def tenant_settings(monkeypatch):
    monkeypatch.setattr("app.services.hostnames.get_settings", lambda: TENANT)


def _product_with_hostname(db_session):
    product = products.create_product(
        db_session,
        payload=products.ProductCreate(name="dep-product", description="d"),
    )
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
    product_orm = db_session.get(ProductORM, product.id)
    product_orm.template_id = template.id
    db_session.add(product_orm)
    db_session.commit()
    return template, create_free_plan_template(db_session, product.id)


def _payload(user_id, template_id, ptv_id, hostname):
    return deployments.DeploymentCreate(
        user_id=user_id,
        desired_template_id=template_id,
        user_values_json={"domain": hostname},
        plan_template_id=ptv_id,
    )


def _unsettled_user(db_session, email, *, accept_tos=True, handle=None):
    user = users.create_user(db_session, users.UserCreate(email=email))
    orm = db_session.get(UserORM, user.id)
    if accept_tos:
        users.record_tos_acceptance(db_session, user=orm, version=CURRENT_TOS_VERSION)
    orm.handle = handle
    db_session.add(orm)
    db_session.commit()
    return user


def _settle(db_session, deployment_id):
    """The update path guards on `ready` and on there being no reconcile job in
    flight -- both of which the reconciler would have settled by now."""
    row = db_session.get(DeploymentORM, deployment_id)
    row.status = DEPLOYMENT_STATUS_READY
    db_session.add(row)
    for job in db_session.exec(select(DeploymentReconcileJobORM)).all():
        db_session.delete(job)
    db_session.commit()


# --- The precondition --------------------------------------------------------

def test_a_create_without_a_handle_is_refused(db_session):
    template, ptv_id = _product_with_hostname(db_session)
    user = _unsettled_user(db_session, "nosub@example.com")

    with pytest.raises(HandleRequired) as excinfo:
        deployments.create_deployment(
            db_session, payload=_payload(user.id, template.id, ptv_id, "app.example.com")
        )

    assert excinfo.value.code == "handle_required"
    assert db_session.exec(select(DeploymentORM)).all() == []


def test_the_refusal_is_a_client_error():
    """`ValidationException` is what `app/api/util.py` maps to 400, and the code
    is what tells it apart from the Terms refusal that shares that status."""
    assert issubclass(HandleRequired, ValidationException)
    assert HandleRequired.code == "handle_required"


def test_the_two_preconditions_are_reported_separately(db_session):
    template, ptv_id = _product_with_hostname(db_session)
    neither = _unsettled_user(db_session, "neither@example.com", accept_tos=False)

    with pytest.raises(HandleRequired) as excinfo:
        deployments.create_deployment(
            db_session, payload=_payload(neither.id, template.id, ptv_id, "a.example.com")
        )

    assert excinfo.value.code == "handle_required"
    assert "Terms of Service" not in str(excinfo.value)


def test_the_terms_refusal_still_names_the_terms(db_session):
    template, ptv_id = _product_with_hostname(db_session)
    no_tos = _unsettled_user(db_session, "notos@example.com", accept_tos=False, handle="notos")

    with pytest.raises(ValidationException) as excinfo:
        deployments.create_deployment(
            db_session, payload=_payload(no_tos.id, template.id, ptv_id, "b.example.com")
        )

    assert "Terms of Service" in str(excinfo.value)
    assert getattr(excinfo.value, "code", None) != "handle_required"


def test_an_update_does_not_apply_the_precondition(db_session):
    template, ptv_id = _product_with_hostname(db_session)
    user = make_accepted_user(db_session, "updater@example.com")
    created = deployments.create_deployment(
        db_session, payload=_payload(user.id, template.id, ptv_id, "app.example.com")
    ).deployment

    orm = db_session.get(UserORM, user.id)
    orm.handle = None
    db_session.add(orm)
    db_session.commit()
    _settle(db_session, created.id)

    updated = deployments.update_deployment(
        db_session,
        deployments.DeploymentUpdate(
            id=created.id,
            user_id=user.id,
            desired_template_id=template.id,
            user_values_json={"domain": "app.example.com"},
        ),
    )

    assert updated.id == created.id


# --- Ownership ---------------------------------------------------------------

def test_a_deployment_under_the_owners_handle_is_created(db_session, tenant_settings):
    template, ptv_id = _product_with_hostname(db_session)
    user = _unsettled_user(db_session, "alice@example.com", handle="alice")

    created = deployments.create_deployment(
        db_session,
        payload=_payload(user.id, template.id, ptv_id, "photos-alice.freepod.app"),
    ).deployment

    assert created.hostname == "photos-alice.freepod.app"


def test_a_bare_label_is_completed_and_written_back(db_session, tenant_settings):
    template, ptv_id = _product_with_hostname(db_session)
    user = _unsettled_user(db_session, "alice@example.com", handle="alice")

    created = deployments.create_deployment(
        db_session, payload=_payload(user.id, template.id, ptv_id, "Photos")
    ).deployment

    assert created.hostname == "photos-alice.freepod.app"
    row = db_session.get(DeploymentORM, created.id)
    assert row.user_values_json == {"domain": "photos-alice.freepod.app"}


def test_a_bare_label_is_completed_on_update(db_session, tenant_settings):
    template, ptv_id = _product_with_hostname(db_session)
    user = _unsettled_user(db_session, "alice@example.com", handle="alice")
    created = deployments.create_deployment(
        db_session, payload=_payload(user.id, template.id, ptv_id, "photos")
    ).deployment
    _settle(db_session, created.id)

    updated = deployments.update_deployment(
        db_session,
        deployments.DeploymentUpdate(
            id=created.id,
            user_id=user.id,
            desired_template_id=template.id,
            user_values_json={"domain": "albums"},
        ),
    )

    assert updated.hostname == "albums-alice.freepod.app"


def test_a_completed_name_meets_the_charts_own_pattern(db_session, tenant_settings):
    """A chart may require a dotted name; the bare label is completed first."""
    template, ptv_id = _product_with_hostname(db_session)
    row = db_session.get(ProductTemplateVersionORM, template.id)
    row.values_schema_json = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"domain": {"type": "string", "title": "hostname", "pattern": r"\."}},
    }
    db_session.add(row)
    db_session.commit()
    user = _unsettled_user(db_session, "alice@example.com", handle="alice")

    created = deployments.create_deployment(
        db_session, payload=_payload(user.id, template.id, ptv_id, "photos")
    ).deployment

    assert created.hostname == "photos-alice.freepod.app"


def test_a_deployment_under_another_handle_is_refused(db_session, tenant_settings):
    template, ptv_id = _product_with_hostname(db_session)
    _unsettled_user(db_session, "alice@example.com", handle="alice")
    bob = _unsettled_user(db_session, "bob@example.com", handle="bob")

    with pytest.raises(HostnameException) as excinfo:
        deployments.create_deployment(
            db_session,
            payload=_payload(bob.id, template.id, ptv_id, "photos-alice.freepod.app"),
        )

    assert excinfo.value.reason == "claimed"
    assert db_session.exec(select(DeploymentORM)).all() == []


def test_a_custom_domain_is_not_subject_to_ownership(db_session, tenant_settings):
    template, ptv_id = _product_with_hostname(db_session)
    bob = _unsettled_user(db_session, "bob@example.com", handle="bob")

    created = deployments.create_deployment(
        db_session,
        payload=_payload(bob.id, template.id, ptv_id, "photos.example.com"),
    ).deployment

    assert created.hostname == "photos.example.com"


def test_an_update_cannot_move_a_deployment_under_another_handle(
    db_session, tenant_settings
):
    template, ptv_id = _product_with_hostname(db_session)
    _unsettled_user(db_session, "alice@example.com", handle="alice")
    bob = _unsettled_user(db_session, "bob@example.com", handle="bob")
    created = deployments.create_deployment(
        db_session, payload=_payload(bob.id, template.id, ptv_id, "photos-bob.freepod.app")
    ).deployment
    _settle(db_session, created.id)

    with pytest.raises(HostnameException) as excinfo:
        deployments.update_deployment(
            db_session,
            deployments.DeploymentUpdate(
                id=created.id,
                user_id=bob.id,
                desired_template_id=template.id,
                user_values_json={"domain": "photos-alice.freepod.app"},
            ),
        )

    assert excinfo.value.reason == "claimed"
