"""The namespace is what the SSH edge addresses a deployment by.

Nothing enforced it before this constraint: two active deployments sharing a
namespace committed without error, and the resolver's lookup was ambiguous as a
result. These assert the guarantee the resolver now depends on, including that
it holds against deleted rows -- a recycled namespace is a recycled SSH
username.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import DeploymentORM, ProductORM, ProductTemplateVersionORM, UserORM
from app.models.core import _utcnow
from app.services.reconcile_constants import DEPLOYMENT_STATUS_DELETED
from tests.conftest import make_deployment_with_release


@pytest.fixture
def scenario(db_session: Session):
    """A user and a canonical template to hang deployments off."""
    user = UserORM(email="ns@example.com", subdomain="ns", created_at=_utcnow())
    product = ProductORM(name="nsprod", created_at=_utcnow())
    db_session.add(user)
    db_session.add(product)
    db_session.flush()
    template = ProductTemplateVersionORM(
        product_id=product.id,
        chart_ref="oci://example/chart",
        chart_version="1.0.0",
        values_schema_json={"type": "object"},
        created_at=_utcnow(),
    )
    db_session.add(template)
    db_session.flush()
    product.template_id = template.id
    db_session.commit()
    return user, template


def _add(session: Session, user, template, *, namespace: str, name: str, status="ready"):
    return make_deployment_with_release(
        session,
        user_id=user.id,
        desired_template_id=template.id,
        name=name,
        namespace=namespace,
        status=status,
    )


def test_two_active_deployments_cannot_share_a_namespace(db_session, scenario):
    user, template = scenario
    _add(db_session, user, template, namespace="shared-ns", name="a-000001")
    db_session.commit()

    _add(db_session, user, template, namespace="shared-ns", name="b-000002")
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_a_deleted_deployment_still_holds_its_namespace(db_session, scenario):
    """The index carries no status predicate: an SSH username is never reissued."""
    user, template = scenario
    _add(
        db_session,
        user,
        template,
        namespace="gone-ns",
        name="a-000001",
        status=DEPLOYMENT_STATUS_DELETED,
    )
    db_session.commit()

    _add(db_session, user, template, namespace="gone-ns", name="b-000002")
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_the_same_name_in_two_namespaces_is_permitted(db_session, scenario):
    """`name` is the Helm release name, unique only within its namespace."""
    user, template = scenario
    _add(db_session, user, template, namespace="ns-one", name="same-000001")
    _add(db_session, user, template, namespace="ns-two", name="same-000001")
    db_session.commit()

    rows = db_session.exec(
        select(DeploymentORM).where(DeploymentORM.name == "same-000001")
    ).all()
    assert {r.namespace for r in rows} == {"ns-one", "ns-two"}


# --- allocation: a collision costs a regeneration, never a failed create ---


def _create_via_service(db_session, user, template):
    from app.models.core import DeploymentCreate
    from app.services import deployments as deployments_service
    from tests.conftest import create_free_plan_template

    plan_template_id = create_free_plan_template(db_session, template.product_id)
    return deployments_service.create_deployment(
        db_session,
        payload=DeploymentCreate(
            user_id=user.id,
            desired_template_id=template.id,
            plan_template_id=plan_template_id,
            user_values_json={},
        ),
    )


def test_a_colliding_candidate_is_regenerated(db_session, scenario, monkeypatch):
    """The first draw is taken; the create still succeeds, on another namespace."""
    user, template = scenario
    user.tos_accepted_version = "2026-08-26"
    _add(db_session, user, template, namespace="taken-ns", name="a-000001")
    db_session.commit()

    draws = iter(["taken-ns", "free-ns"])
    monkeypatch.setattr(
        "app.services.deployments.generate_deployment_namespace",
        lambda *a, **k: next(draws),
    )

    result = _create_via_service(db_session, user, template)

    assert result.deployment.namespace == "free-ns"


def test_a_deleted_deployments_namespace_is_treated_as_taken(db_session, scenario, monkeypatch):
    user, template = scenario
    user.tos_accepted_version = "2026-08-26"
    _add(
        db_session,
        user,
        template,
        namespace="retired-ns",
        name="a-000001",
        status=DEPLOYMENT_STATUS_DELETED,
    )
    db_session.commit()

    draws = iter(["retired-ns", "fresh-ns"])
    monkeypatch.setattr(
        "app.services.deployments.generate_deployment_namespace",
        lambda *a, **k: next(draws),
    )

    result = _create_via_service(db_session, user, template)

    assert result.deployment.namespace == "fresh-ns"


def test_exhausted_attempts_fail_without_writing_a_row(db_session, scenario, monkeypatch):
    from app.services.errors import CaelusException

    user, template = scenario
    user.tos_accepted_version = "2026-08-26"
    _add(db_session, user, template, namespace="always-ns", name="a-000001")
    db_session.commit()

    monkeypatch.setattr(
        "app.services.deployments.generate_deployment_namespace",
        lambda *a, **k: "always-ns",
    )

    with pytest.raises(CaelusException):
        _create_via_service(db_session, user, template)
    db_session.rollback()

    remaining = db_session.exec(
        select(DeploymentORM).where(DeploymentORM.namespace == "always-ns")
    ).all()
    assert len(remaining) == 1
