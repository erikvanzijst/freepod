"""Reconciler integration for per-deployment relational storage.

The tenant cluster is stubbed here; `test_relational_storage.py` covers the
real statements. What these assert is the wiring: the gate on the product
template, the position in the apply path, and that the password reaches the
Kubernetes Secret and nothing else.
"""

from __future__ import annotations

import json

import pytest

from app.config import CaelusSettings
from app.models import (
    BillingInterval,
    DeploymentCreate,
    PlanORM,
    PlanTemplateVersionORM,
    ProductORM,
)
from app.models.core import _utcnow
from app.services import deployments, products, relational_storage, templates
from app.services.postgres_admin import PostgresAdminException
from app.services.reconcile import DeploymentReconciler
from tests.conftest import make_accepted_user
from tests.provisioner_utils import FakeProvisioner

PASSWORD = "the-database-password"
POOLER_HOST = "caelus-tenant-pooler.caelus-test.svc.cluster.local"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    settings = CaelusSettings(
        wildcard_domains=[],
        tls_cluster_issuer="letsencrypt-http",
        domain="example.test",
        tenant_db_pooler_host=POOLER_HOST,
        tenant_db_pooler_port=6432,
        _env_file=None,
    )
    monkeypatch.setattr("app.services.reconcile.get_settings", lambda: settings)
    return settings


@pytest.fixture
def stub_cluster(monkeypatch):
    """Replace the provisioning calls, recording what the reconciler asked for."""
    calls: list[tuple[str, object]] = []

    def ensure(session, deployment, **_kwargs):
        calls.append(("ensure", deployment.id))
        return relational_storage.DatabaseCredentials(
            host=POOLER_HOST,
            port=6432,
            database=relational_storage.database_name(deployment),
            user=relational_storage.role_name(deployment),
            password=PASSWORD,
        )

    def teardown(session, deployment, **_kwargs):
        calls.append(("teardown", deployment.id))

    monkeypatch.setattr(relational_storage, "ensure_database", ensure)
    monkeypatch.setattr(relational_storage, "teardown_database", teardown)
    return calls


def _seed(db_session, *, enabled: bool, database_bytes: int = 104857600) -> int:
    user = make_accepted_user(db_session, "database-user@example.com")
    product = products.create_product(
        db_session, payload=products.ProductCreate(name="database-product", description="d")
    )
    system_values = {"replicas": 1}
    if enabled:
        system_values["relationalStorage"] = {"enabled": True}
    template = templates.create_template(
        db_session,
        payload=templates.ProductTemplateVersionCreate(
            product_id=product.id,
            chart_ref="oci://example/chart",
            chart_version="1.2.3",
            system_values_json=system_values,
            values_schema_json={
                "type": "object",
                "properties": {
                    "user": {
                        "type": "object",
                        "properties": {"domain": {"type": "string", "title": "hostname"}},
                        "additionalProperties": False,
                    }
                },
                "additionalProperties": False,
            },
        ),
    )
    product_orm = db_session.get(ProductORM, product.id)
    product_orm.template_id = template.id
    db_session.add(product_orm)
    db_session.commit()

    plan = PlanORM(name="plan", product_id=product.id, created_at=_utcnow())
    db_session.add(plan)
    db_session.flush()
    ptv = PlanTemplateVersionORM(
        plan_id=plan.id,
        price_cents=0,
        billing_interval=BillingInterval.MONTHLY,
        storage_bytes=0,
        database_bytes=database_bytes,
        created_at=_utcnow(),
    )
    db_session.add(ptv)
    db_session.flush()
    plan.template_id = ptv.id
    db_session.commit()

    return deployments.create_deployment(
        db_session,
        payload=DeploymentCreate(
            user_id=user.id,
            desired_template_id=template.id,
            user_values_json={"user": {"domain": "database.example.test"}},
            plan_template_id=ptv.id,
        ),
    ).deployment.id


def _helm_values(provisioner: FakeProvisioner) -> dict:
    return next(c[1]["values"] for c in provisioner.calls if c[0] == "helm_upgrade_install")


def _secret(provisioner: FakeProvisioner, suffix: str) -> dict:
    return next(
        c[1]
        for c in provisioner.calls
        if c[0] == "upsert_secret" and c[1]["name"].endswith(suffix)
    )


def _mark_deleted(db_session, deployment_id) -> None:
    """What the delete path keys off, without the queue in the way."""
    from app.models import DeploymentORM

    deployment = db_session.get(DeploymentORM, deployment_id)
    deployment.deleted_at = _utcnow()
    db_session.add(deployment)
    db_session.commit()


def test_an_opted_in_product_provisions_and_publishes_a_secret(db_session, stub_cluster):
    deployment_id = _seed(db_session, enabled=True)
    provisioner = FakeProvisioner()

    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    assert [c[0] for c in stub_cluster] == ["ensure"]
    secret = _secret(provisioner, "-database")
    data = secret["string_data"]
    assert data["PGPASSWORD"] == PASSWORD
    assert data["PGHOST"] == POOLER_HOST
    assert data["PGPORT"] == "6432"
    assert data["PGUSER"] == data["PGDATABASE"]
    assert data["PGDATABASE"].startswith("dpl_")
    # The URL covers every ORM; the PG* variables cover libpq and its tools.
    assert data["DATABASE_URL"] == (
        f"postgresql://{data['PGUSER']}:{PASSWORD}@{POOLER_HOST}:6432/{data['PGDATABASE']}"
    )


def test_the_secret_is_written_before_helm_runs(db_session, stub_cluster):
    deployment_id = _seed(db_session, enabled=True)
    provisioner = FakeProvisioner()

    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    order = [c[0] for c in provisioner.calls]
    names = [c[1].get("name") for c in provisioner.calls if c[0] == "upsert_secret"]
    database_secret = order.index("upsert_secret") + names.index(
        next(n for n in names if n.endswith("-database"))
    )
    assert database_secret < order.index("helm_upgrade_install")
    assert order.index("ensure_tenant_isolation") < order.index("upsert_secret")


def test_the_same_secret_is_updated_across_reconciles(db_session, stub_cluster):
    deployment_id = _seed(db_session, enabled=True)
    provisioner = FakeProvisioner()
    reconciler = DeploymentReconciler(session=db_session, provisioner=provisioner)

    reconciler.reconcile(deployment_id)
    first = _secret(provisioner, "-database")["name"]
    provisioner.calls.clear()
    reconciler.reconcile(deployment_id)

    assert _secret(provisioner, "-database")["name"] == first


def test_helm_values_carry_references_but_never_the_password(db_session, stub_cluster):
    deployment_id = _seed(db_session, enabled=True)
    provisioner = FakeProvisioner()

    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    values = _helm_values(provisioner)
    assert values["relationalStorage"]["enabled"] is True
    database = values["caelus"]["database"]
    assert database["host"] == POOLER_HOST
    assert database["port"] == 6432
    assert database["name"] == database["user"]
    assert database["secretName"].endswith("-database")
    assert set(database) == {"host", "port", "name", "user", "secretName"}
    assert PASSWORD not in json.dumps(values)


def test_a_product_that_has_not_opted_in_provisions_nothing(db_session, stub_cluster):
    deployment_id = _seed(db_session, enabled=False)
    provisioner = FakeProvisioner()

    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    assert stub_cluster == []
    assert not [
        c for c in provisioner.calls if c[0] == "upsert_secret" and c[1]["name"].endswith("-database")
    ]
    assert "database" not in _helm_values(provisioner)["caelus"]


def test_a_tenant_cannot_opt_themselves_in_through_user_values(db_session, stub_cluster):
    deployment_id = _seed(db_session, enabled=False)
    from app.models import DeploymentORM

    deployment = db_session.get(DeploymentORM, deployment_id)
    deployment.user_values_json = {
        "user": {"domain": "database.example.test"},
        "relationalStorage": {"enabled": True},
    }
    db_session.add(deployment)
    db_session.commit()

    provisioner = FakeProvisioner()
    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    assert stub_cluster == []


def test_an_unreachable_cluster_fails_the_reconcile_before_helm(db_session, monkeypatch):
    """Fail closed: no pod may start expecting a database that was never made."""
    deployment_id = _seed(db_session, enabled=True)

    def unreachable(session, deployment, **_kwargs):
        raise PostgresAdminException("cannot reach the tenant PostgreSQL cluster")

    monkeypatch.setattr(relational_storage, "ensure_database", unreachable)
    provisioner = FakeProvisioner()

    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    assert not [c for c in provisioner.calls if c[0] == "helm_upgrade_install"]
    from app.models import DeploymentORM

    deployment = db_session.get(DeploymentORM, deployment_id)
    assert deployment.status == "error"
    assert "tenant PostgreSQL cluster" in (deployment.last_error or "")


def test_deleting_a_deployment_tears_the_database_down(db_session, stub_cluster):
    deployment_id = _seed(db_session, enabled=True)
    provisioner = FakeProvisioner()
    reconciler = DeploymentReconciler(session=db_session, provisioner=provisioner)
    reconciler.reconcile(deployment_id)

    _mark_deleted(db_session, deployment_id)
    reconciler.reconcile(deployment_id)

    assert [c[0] for c in stub_cluster] == ["ensure", "teardown"]


def test_deleting_a_deployment_without_a_database_tears_nothing_down(db_session, stub_cluster):
    deployment_id = _seed(db_session, enabled=False)
    provisioner = FakeProvisioner()
    reconciler = DeploymentReconciler(session=db_session, provisioner=provisioner)
    reconciler.reconcile(deployment_id)

    _mark_deleted(db_session, deployment_id)
    reconciler.reconcile(deployment_id)

    assert stub_cluster == []
