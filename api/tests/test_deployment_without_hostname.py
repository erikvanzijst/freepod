"""A deployment whose template declares no hostname-titled field.

`deployment-create-contract` requires the service to persist `hostname` as
`null` when the desired template's schema has no field titled `hostname`, and
`create_deployment` does exactly that. The column was NOT NULL in the migration
chain until `b4c5d6e7f8a9`, so this path raised in production -- invisibly,
because the old test schema came from model metadata, which had the column
nullable all along.

This is also the groundwork for headless apps: a deployment served without an
ingress has no hostname by construction.
"""

from __future__ import annotations

from sqlmodel import select

from app.models import DeploymentORM, DeploymentReconcileJobORM, ProductORM
from app.services import deployments, products, templates
from app.services.reconcile_constants import DEPLOYMENT_STATUS_READY
from tests.conftest import create_free_plan_template, make_accepted_user


def _template_without_hostname(db_session):
    """A user plus a template whose schema declares no `hostname` field."""
    user = make_accepted_user(db_session, "headless@example.com")
    product = products.create_product(
        db_session,
        payload=products.ProductCreate(name="headless-product", description="no ingress"),
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
                "properties": {"replicas": {"type": "integer", "title": "replicas"}},
            },
        ),
    )
    product_orm = db_session.get(ProductORM, product.id)
    product_orm.template_id = template.id
    db_session.add(product_orm)
    db_session.commit()
    return user, template, create_free_plan_template(db_session, product.id)


def test_deployment_without_a_hostname_field_persists_a_null_hostname(db_session):
    user, template, ptv_id = _template_without_hostname(db_session)

    created = deployments.create_deployment(
        db_session,
        payload=deployments.DeploymentCreate(
            user_id=user.id,
            desired_template_id=template.id,
            user_values_json={"replicas": 2},
            plan_template_id=ptv_id,
        ),
    ).deployment

    stored = db_session.exec(
        select(DeploymentORM).where(DeploymentORM.id == created.id)
    ).one()
    assert stored.hostname is None


def test_updating_onto_a_hostname_less_template_persists_null(db_session):
    user, template, ptv_id = _template_without_hostname(db_session)
    created = deployments.create_deployment(
        db_session,
        payload=deployments.DeploymentCreate(
            user_id=user.id,
            desired_template_id=template.id,
            user_values_json={"replicas": 1},
            plan_template_id=ptv_id,
        ),
    ).deployment

    # Updating requires a settled deployment: creation leaves it provisioning
    # with an open reconcile job, and only one open job per deployment is
    # allowed. Stand in for the worker having processed it.
    orm = db_session.get(DeploymentORM, created.id)
    orm.status = DEPLOYMENT_STATUS_READY
    db_session.add(orm)
    for job in db_session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == created.id
        )
    ).all():
        job.status = "done"
        db_session.add(job)
    db_session.commit()

    deployments.update_deployment(
        db_session,
        deployments.DeploymentUpdate(
            id=created.id,
            user_id=user.id,
            desired_template_id=template.id,
            user_values_json={"replicas": 3},
        ),
    )

    stored = db_session.exec(
        select(DeploymentORM).where(DeploymentORM.id == created.id)
    ).one()
    assert stored.hostname is None
