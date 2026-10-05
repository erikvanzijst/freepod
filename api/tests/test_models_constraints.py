import pytest
from datetime import UTC, datetime

from app.services import templates, deployments, products, users
from app.services.jobs import JobService
from sqlmodel import select
from app.models import DeploymentORM, DeploymentReconcileJobORM, ProductORM, SQLModel
from app.services.errors import HostnameException, IntegrityException
from app.services.reconcile import DeploymentReconciler
from app.services.reconcile_constants import DEPLOYMENT_STATUS_DELETED
from tests.conftest import db_session, make_accepted_user
from tests.conftest import create_free_plan_template
from tests.provisioner_utils import FakeProvisioner


def test_product_name_unique_constraint(db_session):
    def delete_product(prod: products.ProductORM):
        orm = db_session.get(products.ProductORM, prod.id)
        orm.deleted_at = datetime.now(UTC)
        db_session.add(orm)
        db_session.commit()

    # Create first product
    p1 = products.create_product(
        db_session, payload=products.ProductCreate(name="testprod", description="desc")
    )
    # Attempt to create duplicate product with same name
    with pytest.raises(IntegrityException):
        products.create_product(
            db_session, payload=products.ProductCreate(name="testprod", description="another")
        )

    # rollback the failed transaction
    db_session.rollback()
    # Mark first product as deleted manually
    delete_product(p1)

    # Now creating a product with same name should succeed
    p2 = products.create_product(
        db_session, payload=products.ProductCreate(name="testprod", description="new")
    )
    assert p2.id != p1.id
    # deletion should still work (the partial index should allow duplicate deleted name entries)
    delete_product(p2)


def test_product_name_unique_constraint_is_case_insensitive(db_session):
    products.create_product(
        db_session, payload=products.ProductCreate(name="CaseProd", description="desc")
    )
    with pytest.raises(IntegrityException):
        products.create_product(
            db_session, payload=products.ProductCreate(name="caseprod", description="desc")
        )


def test_user_email_unique_constraint_is_case_insensitive(db_session):
    make_accepted_user(db_session, "CaseUser@example.com")
    with pytest.raises(IntegrityException):
        make_accepted_user(db_session, "caseuser@example.com")


def test_deployment_unique_constraint(db_session):
    # Setup user
    user = make_accepted_user(db_session, "user@example.com")
    # Setup product and template
    product = products.create_product(
        db_session, payload=products.ProductCreate(name="prod2", description="desc")
    )
    template = templates.create_template(
        db_session,
        payload=templates.ProductTemplateVersionCreate(
            product_id=product.id,
            chart_ref="registry.home/nextcloud/",
            chart_version="1.0.0",
            values_schema_json={
                "type": "object",
                "additionalProperties": False,
                "properties": {"domain": {"type": "string", "title": "hostname"}},
            },
        )
    )
    product_orm = db_session.get(ProductORM, product.id)
    product_orm.template_id = template.id
    db_session.add(product_orm)
    db_session.commit()
    ptv_id = create_free_plan_template(db_session, product.id)
    # Create first deployment
    dep1 = deployments.create_deployment(
        db_session,
        payload=deployments.DeploymentCreate(
            user_id=user.id, desired_template_id=template.id, user_values_json={"domain": "example.com"},
            plan_template_id=ptv_id,
        ),
    ).deployment
    # Attempt duplicate deployment — service-level validation catches hostname reuse
    with pytest.raises(HostnameException, match="in_use"):
        deployments.create_deployment(
            db_session,
            payload=deployments.DeploymentCreate(
                user_id=user.id, desired_template_id=template.id, user_values_json={"domain": "example.com"},
                plan_template_id=ptv_id,
            ),
        )
    create_job = db_session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == dep1.id,
            DeploymentReconcileJobORM.reason == "create",
        )
    ).one()
    JobService(db_session).mark_job_done(job_id=create_job.id)
    # Delete first deployment via service
    deployments.delete_deployment(db_session, user_id=user.id, deployment_id=dep1.id)

    # Run the reconciler to actually process the delete request and set the status to deleted:
    reconciler = DeploymentReconciler(session=db_session, provisioner=FakeProvisioner())

    result = reconciler.reconcile(dep1.id)
    assert result.status == DEPLOYMENT_STATUS_DELETED

    # Now creating same deployment should succeed
    dep2 = deployments.create_deployment(
        db_session,
        payload=deployments.DeploymentCreate(
            user_id=user.id, desired_template_id=template.id, user_values_json={"domain": "example.com"},
            plan_template_id=ptv_id,
        ),
    ).deployment
    assert dep2.id != dep1.id


def test_hostname_active_unique_constraint_across_non_deleted_deployments(db_session):
    user_a = make_accepted_user(db_session, "domain-a@example.com")
    user_b = make_accepted_user(db_session, "domain-b@example.com")
    product = products.create_product(
        db_session,
        payload=products.ProductCreate(name="domain-uniq-product", description="desc"),
    )
    template_v1 = templates.create_template(
        db_session,
        payload=templates.ProductTemplateVersionCreate(
            product_id=product.id,
            chart_ref="registry.home/nextcloud/",
            chart_version="1.0.0",
            values_schema_json={
                "type": "object",
                "additionalProperties": False,
                "properties": {"domain": {"type": "string", "title": "hostname"}},
            },
        ),
    )
    template_v2 = templates.create_template(
        db_session,
        payload=templates.ProductTemplateVersionCreate(
            product_id=product.id,
            chart_ref="registry.home/nextcloud/",
            chart_version="2.0.0",
            values_schema_json={
                "type": "object",
                "additionalProperties": False,
                "properties": {"domain": {"type": "string", "title": "hostname"}},
            },
        ),
    )

    product_orm = db_session.get(ProductORM, product.id)
    product_orm.template_id = template_v1.id
    db_session.add(product_orm)
    db_session.commit()
    ptv_id = create_free_plan_template(db_session, product.id)

    dep_a = deployments.create_deployment(
        db_session,
        payload=deployments.DeploymentCreate(
            user_id=user_a.id,
            desired_template_id=template_v1.id,
            user_values_json={"domain": "shared.example.com"},
            plan_template_id=ptv_id,
        ),
    ).deployment
    assert dep_a.hostname == "shared.example.com"

    product_orm = db_session.get(ProductORM, product.id)
    product_orm.template_id = template_v2.id
    db_session.add(product_orm)
    db_session.commit()

    with pytest.raises(HostnameException, match="in_use"):
        deployments.create_deployment(
            db_session,
            payload=deployments.DeploymentCreate(
                user_id=user_b.id,
                desired_template_id=template_v2.id,
                user_values_json={"domain": "shared.example.com"},
                plan_template_id=ptv_id,
            ),
        )
    dep_a_orm = db_session.get(deployments.DeploymentORM, dep_a.id)
    assert dep_a_orm is not None
    dep_a_orm.status = DEPLOYMENT_STATUS_DELETED
    db_session.add(dep_a_orm)
    db_session.commit()

    product_orm = db_session.get(ProductORM, product.id)
    product_orm.template_id = template_v2.id
    db_session.add(product_orm)
    db_session.commit()

    dep_b = deployments.create_deployment(
        db_session,
        payload=deployments.DeploymentCreate(
            user_id=user_b.id,
            desired_template_id=template_v2.id,
            user_values_json={"domain": "shared.example.com"},
            plan_template_id=ptv_id,
        ),
    ).deployment
    assert dep_b.hostname == "shared.example.com"


def test_deployment_active_unique_constraint_ignores_deleted_status_rows(db_session):
    user = make_accepted_user(db_session, "active-uniq@example.com")
    product = products.create_product(
        db_session, payload=products.ProductCreate(name="active-uniq-product", description="desc")
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
    ptv_id = create_free_plan_template(db_session, product.id)

    dep_a = deployments.create_deployment(
        db_session,
        payload=deployments.DeploymentCreate(
            user_id=user.id,
            desired_template_id=template.id,
            user_values_json={"domain": "active.example.com"},
            plan_template_id=ptv_id,
        ),
    ).deployment
    with pytest.raises(HostnameException, match="in_use"):
        deployments.create_deployment(
            db_session,
            payload=deployments.DeploymentCreate(
                user_id=user.id,
                desired_template_id=template.id,
                user_values_json={"domain": "active.example.com"},
                plan_template_id=ptv_id,
            ),
        )

    dep_a_orm = db_session.get(DeploymentORM, dep_a.id)
    assert dep_a_orm is not None
    dep_a_orm.status = DEPLOYMENT_STATUS_DELETED
    dep_a_orm.deleted_at = None
    db_session.add(dep_a_orm)
    db_session.commit()

    dep_b = deployments.create_deployment(
        db_session,
        payload=deployments.DeploymentCreate(
            user_id=user.id,
            desired_template_id=template.id,
            user_values_json={"domain": "active.example.com"},
            plan_template_id=ptv_id,
        ),
    ).deployment
    assert dep_b.id != dep_a.id


def test_template_versions_allow_duplicates_when_active(db_session):
    product = products.create_product(
        db_session,
        payload=products.ProductCreate(name="template-dup-product", description="desc"),
    )
    template_a = templates.create_template(
        db_session,
        payload=templates.ProductTemplateVersionCreate(
            product_id=product.id,
            chart_ref="oci://example/dup-chart",
            chart_version="1.0.0",
        ),
    )
    template_b = templates.create_template(
        db_session,
        payload=templates.ProductTemplateVersionCreate(
            product_id=product.id,
            chart_ref="oci://example/dup-chart",
            chart_version="1.0.0",
        ),
    )
    assert template_a.id != template_b.id


def test_partial_indexes_declare_a_postgres_predicate_and_no_other():
    """Partial predicates are Postgres-only now that no second dialect exists.

    A predicate declared for another dialect is a constraint that silently does
    not exist on the database we actually run.
    """
    for table in SQLModel.metadata.tables.values():
        for index in table.indexes:
            for dialect in index.dialect_options:
                if dialect == "postgresql":
                    continue
                assert index.dialect_options[dialect].get("where") is None, (
                    f"Index {index.name} declares a {dialect} predicate; "
                    "partial indexes are Postgres-only"
                )
