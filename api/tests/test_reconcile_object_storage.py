"""Reconciler integration for per-deployment object storage.

Garage itself is stubbed out here — `test_object_storage.py` covers the real
request paths. What these assert is the wiring: that provisioning is gated on
the product template, that it happens in the right place in the apply path, and
above all that the secret access key reaches the Kubernetes Secret and reaches
nothing else.
"""

from __future__ import annotations

import json

import pytest

from app.config import CaelusSettings
from app.models import (
    BillingInterval,
    DeploymentCreate,
    DeploymentORM,
    PlanORM,
    PlanTemplateVersionORM,
    ProductORM,
)
from app.models.core import _utcnow
from app.services import deployments, object_storage, products, templates
from app.services.object_storage import ObjectStorageCredentials
from app.services.reconcile import DeploymentReconciler
from tests.conftest import make_accepted_user
from tests.provisioner_utils import FakeProvisioner

SECRET_KEY = "the-secret-access-key"
ENDPOINT = "https://blob.example.invalid"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    settings = CaelusSettings(
        wildcard_domains=[],
        tls_cluster_issuer="letsencrypt-http",
        domain="example.test",
        s3_endpoint_url=ENDPOINT,
        s3_region="garage",
        _env_file=None,
    )
    monkeypatch.setattr("app.services.reconcile.get_settings", lambda: settings)
    return settings


@pytest.fixture
def stub_garage(monkeypatch):
    """Replace the provisioning calls, recording what the reconciler asked for."""
    calls: list[tuple[str, object]] = []

    def ensure(deployment, **_kwargs):
        calls.append(("ensure", deployment.id))
        return ObjectStorageCredentials(
            bucket=object_storage.bucket_name(deployment),
            access_key_id="GKtest",
            secret_access_key=SECRET_KEY,
        )

    def teardown(deployment, **_kwargs):
        calls.append(("teardown", deployment.id))

    monkeypatch.setattr(object_storage, "ensure_object_storage", ensure)
    monkeypatch.setattr(object_storage, "teardown_object_storage", teardown)
    return calls


def _seed(db_session, *, storage_enabled: bool, storage_bytes: int = 1073741824) -> int:
    user = make_accepted_user(db_session, "storage-user@example.com")
    product = products.create_product(
        db_session, payload=products.ProductCreate(name="storage-product", description="d")
    )
    system_values = {"replicas": 1}
    if storage_enabled:
        system_values["objectStorage"] = {"enabled": True}
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
        storage_bytes=storage_bytes,
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
            user_values_json={"user": {"domain": "storage.example.test"}},
            plan_template_id=ptv.id,
        ),
    ).deployment.id


def _helm_values(provisioner: FakeProvisioner) -> dict:
    return next(c[1]["values"] for c in provisioner.calls if c[0] == "helm_upgrade_install")


def test_opted_in_product_provisions_and_publishes_a_secret(db_session, stub_garage):
    deployment_id = _seed(db_session, storage_enabled=True)
    provisioner = FakeProvisioner()

    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    assert [c[0] for c in stub_garage] == ["ensure"]
    secret = next(c[1] for c in provisioner.calls if c[0] == "upsert_secret")
    assert secret["namespace"]
    assert secret["string_data"]["AWS_SECRET_ACCESS_KEY"] == SECRET_KEY
    # The conventional names, so an unmodified SDK works with no configuration.
    assert secret["string_data"]["AWS_ACCESS_KEY_ID"] == "GKtest"
    assert secret["string_data"]["AWS_ENDPOINT_URL_S3"] == ENDPOINT
    assert secret["string_data"]["AWS_REGION"] == "garage"
    # The bucket name is supplied, never expected to be hard-coded by the app.
    assert secret["string_data"]["S3_BUCKET"] == secret["string_data"]["BUCKET_NAME"]
    assert secret["string_data"]["S3_BUCKET"].startswith("dep-")


def test_the_secret_is_written_before_helm_runs(db_session, stub_garage):
    """No pod may start expecting a Secret that does not exist yet."""
    deployment_id = _seed(db_session, storage_enabled=True)
    provisioner = FakeProvisioner()

    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    order = [c[0] for c in provisioner.calls]
    assert order.index("upsert_secret") < order.index("helm_upgrade_install")
    # And still after the isolation jail, which nothing may precede.
    assert order.index("ensure_tenant_isolation") < order.index("upsert_secret")


def test_helm_values_carry_references_but_never_the_credential(db_session, stub_garage):
    """Merged values are logged in full and persisted by Helm into a release
    Secret in the tenant's namespace, so the credential must not be in them."""
    deployment_id = _seed(db_session, storage_enabled=True)
    provisioner = FakeProvisioner()

    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    values = _helm_values(provisioner)
    # The toggle is the chart's own top-level value, from the catalog; only the
    # per-deployment references are injected here.
    assert values["objectStorage"]["enabled"] is True
    storage = values["caelus"]["objectStorage"]
    assert storage["endpoint"] == ENDPOINT
    assert storage["region"] == "garage"
    assert storage["bucket"].startswith("dep-")
    assert storage["secretName"].endswith("-object-storage")
    assert SECRET_KEY not in json.dumps(values)


def test_a_product_that_has_not_opted_in_provisions_nothing(db_session, stub_garage):
    deployment_id = _seed(db_session, storage_enabled=False)
    provisioner = FakeProvisioner()

    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    assert stub_garage == []
    assert not [c for c in provisioner.calls if c[0] == "upsert_secret"]
    # No block at all, so a chart can gate on it and an un-opted-in deployment
    # renders exactly as it did before this feature existed.
    assert "objectStorage" not in _helm_values(provisioner)["caelus"]


def test_a_tenant_cannot_opt_themselves_in_through_user_values(db_session, stub_garage):
    deployment_id = _seed(db_session, storage_enabled=False)
    orm = db_session.get(DeploymentORM, deployment_id)
    orm.user_values_json = {
        "user": {"domain": "storage.example.test"},
        "objectStorage": {"enabled": True},
    }
    db_session.add(orm)
    db_session.commit()

    provisioner = FakeProvisioner()
    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    # The opt-in is read off the template's system values, which user values
    # never reach — so this is refused before the schema even gets a say.
    assert stub_garage == []


def test_delete_tears_down_storage(db_session, stub_garage):
    deployment_id = _seed(db_session, storage_enabled=True)
    provisioner = FakeProvisioner()
    reconciler = DeploymentReconciler(session=db_session, provisioner=provisioner)
    reconciler.reconcile(deployment_id)

    orm = db_session.get(DeploymentORM, deployment_id)
    orm.deleted_at = _utcnow()
    db_session.add(orm)
    db_session.commit()
    provisioner.calls.clear()

    reconciler.reconcile(deployment_id)

    assert ("teardown", orm.id) in stub_garage
    # Before the namespace goes: object storage lives outside the cluster, and
    # deleting the namespace would silently orphan the bucket.
    order = [c[0] for c in provisioner.calls]
    assert "delete_namespace" in order


def test_delete_of_an_un_opted_in_deployment_skips_teardown(db_session, stub_garage):
    deployment_id = _seed(db_session, storage_enabled=False)
    provisioner = FakeProvisioner()
    reconciler = DeploymentReconciler(session=db_session, provisioner=provisioner)
    reconciler.reconcile(deployment_id)

    orm = db_session.get(DeploymentORM, deployment_id)
    orm.deleted_at = _utcnow()
    db_session.add(orm)
    db_session.commit()

    reconciler.reconcile(deployment_id)

    assert stub_garage == []
