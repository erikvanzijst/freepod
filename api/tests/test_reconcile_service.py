from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.config import CaelusSettings
from app.models import DeploymentCreate, DeploymentORM, ProductORM, PlanORM, PlanTemplateVersionORM, BillingInterval
from app.models.core import _utcnow
from app.services import deployments, products, template_values, templates, users
from tests.conftest import make_accepted_user
from app.services.reconcile import DeploymentReconciler
from tests.provisioner_utils import FakeProvisioner


@pytest.fixture(autouse=True)
def _reconcile_tls_settings(monkeypatch):
    """Pin the settings the reconciler reads for TLS injection so tests don't depend
    on ambient ``.env`` / ``.env.local`` (no wildcard domains -> hostnames classify as
    custom). Individual tests re-patch this to exercise the wildcard branch.
    """
    monkeypatch.setattr(
        "app.services.reconcile.get_settings",
        lambda: CaelusSettings(
            wildcard_domains=[], tls_cluster_issuer="letsencrypt-http", domain="example.test", _env_file=None
        ),
    )


def _create_plan_template(db_session, product_id: int, storage_bytes: int | None) -> int:
    """Create a Plan + PlanTemplateVersion with a specific storage_bytes value."""
    plan = PlanORM(name=f"plan-{storage_bytes}", product_id=product_id, created_at=_utcnow())
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
    db_session.refresh(ptv)
    return ptv.id


def _seed_deployment(db_session, *, storage_bytes: int | None = 0) -> int:
    """Seed a deployment with a plan template.

    ``storage_bytes`` defaults to 0 (free-plan behaviour used by existing tests).
    Pass an explicit int to test plan storage injection, or ``None`` for a plan
    with no storage quota.
    """
    user = make_accepted_user(db_session, "reconcile-user@example.com")
    product = products.create_product(
        db_session,
        payload=products.ProductCreate(name="reconcile-product", description="desc"),
    )
    schema = {
        "type": "object",
        "properties": {
            "user": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "domain": {"type": "string", "title": "hostname"},
                },
                "additionalProperties": False,
            },
            "replicas": {"type": "integer"},
        },
        "additionalProperties": False,
    }
    template = templates.create_template(
        db_session,
        payload=templates.ProductTemplateVersionCreate(
            product_id=product.id,
            chart_ref="oci://example/chart",
            chart_version="1.2.3",
            system_values_json={"replicas": 1},
            values_schema_json=schema,
        ),
    )
    product_orm = db_session.get(ProductORM, product.id)
    product_orm.template_id = template.id
    db_session.add(product_orm)
    db_session.commit()
    ptv_id = _create_plan_template(db_session, product.id, storage_bytes)
    deployment = deployments.create_deployment(
        db_session,
        payload=DeploymentCreate(
            user_id=user.id,
            desired_template_id=template.id,
            user_values_json={"user": {"message": "hello", "domain": "reconcile.example.test"}},
            plan_template_id=ptv_id,
        ),
    ).deployment
    return deployment.id


def test_reconcile_apply_happy_path_returns_ready_and_applied_template(db_session) -> None:
    deployment_id = _seed_deployment(db_session)
    fake_provisioner = FakeProvisioner()
    reconciler = DeploymentReconciler(session=db_session, provisioner=fake_provisioner)

    result = reconciler.reconcile(deployment_id)
    deployment = db_session.get(DeploymentORM, deployment_id)
    assert deployment is not None

    assert result.status == "ready"
    assert result.applied_template_id == deployment.desired_template_id
    assert result.last_error is None
    assert result.last_reconcile_at is not None
    assert deployment.status == "ready"
    assert deployment.applied_template_id == deployment.desired_template_id
    # Isolation guardrails are applied after the namespace and before Helm, so no
    # tenant pod ever runs before its NetworkPolicy jail exists.
    assert fake_provisioner.calls[0][0] == "ensure_namespace"
    assert fake_provisioner.calls[1][0] == "ensure_tenant_isolation"
    assert fake_provisioner.calls[2][0] == "helm_upgrade_install"
    assert fake_provisioner.calls[2][1]["values"] == {
        "replicas": 1,
        "user": {"message": "hello", "domain": "reconcile.example.test"},
        "caelus": {
            "plan": {},
            "ingress": {
                "enabled": True,
                "host": "reconcile.example.test",
                "tls": {
                    "wildcard": False,
                    "issuer": "letsencrypt-http",
                    "secretName": f"{deployment.name}-tls",
                },
            },
            "owner": {"email": "reconcile-user@example.com", "id": deployment.user_id},
            # Offered to every product with no per-product condition; whether a
            # chart renders them is the chart's business. Both spellings of the
            # one release: the id keys the log stream, the number is what
            # `freepod releases` shows and what the SSH banner reports.
            "releaseId": str(deployment.desired_release_id),
            "releaseNumber": "1",
        },
    }


def test_reconcile_delete_returns_deleted_when_marked_deleted(db_session) -> None:
    deployment_id = _seed_deployment(db_session)
    deployment = db_session.get(DeploymentORM, deployment_id)
    assert deployment is not None
    deployment.deleted_at = datetime.now(UTC)
    db_session.add(deployment)
    db_session.commit()

    fake_provisioner = FakeProvisioner()
    reconciler = DeploymentReconciler(session=db_session, provisioner=fake_provisioner)

    result = reconciler.reconcile(deployment_id)
    deployment = db_session.get(DeploymentORM, deployment_id)
    assert deployment is not None

    assert result.status == "deleted"
    assert deployment.status == "deleted"
    assert result.last_error is None
    assert [name for name, _ in fake_provisioner.calls] == [
        "helm_uninstall",
        "delete_namespace",
    ]


def test_reconcile_validation_failure_returns_error_and_persists(db_session) -> None:
    deployment_id = _seed_deployment(db_session)
    deployment = db_session.get(DeploymentORM, deployment_id)
    assert deployment is not None
    deployment.name = ""
    db_session.add(deployment)
    db_session.commit()

    fake_provisioner = FakeProvisioner()
    reconciler = DeploymentReconciler(session=db_session, provisioner=fake_provisioner)

    result = reconciler.reconcile(deployment_id)
    deployment = db_session.get(DeploymentORM, deployment_id)
    assert deployment is not None

    assert result.status == "error"
    assert "name" in (result.last_error or "")
    assert fake_provisioner.calls == []
    assert deployment.status == "error"
    assert "name" in (deployment.last_error or "")


def test_reconcile_schema_validation_failure_returns_error_result(db_session) -> None:
    deployment_id = _seed_deployment(db_session)
    deployment = db_session.get(DeploymentORM, deployment_id)
    assert deployment is not None
    deployment.user_values_json = {"message": 123}
    db_session.add(deployment)
    db_session.commit()

    fake_provisioner = FakeProvisioner()
    reconciler = DeploymentReconciler(session=db_session, provisioner=fake_provisioner)

    result = reconciler.reconcile(deployment_id)
    deployment = db_session.get(DeploymentORM, deployment_id)
    assert deployment is not None

    assert result.status == "error"
    assert result.last_error is not None
    assert "invalid" in result.last_error
    assert fake_provisioner.calls == []
    assert deployment.status == "error"


def test_reconcile_injects_plan_storage_into_helm_values(db_session) -> None:
    """Plan storage_bytes is projected into caelus.plan namespace in Helm values."""
    deployment_id = _seed_deployment(db_session, storage_bytes=10737418240)  # 10 GiB
    fake_provisioner = FakeProvisioner()
    reconciler = DeploymentReconciler(session=db_session, provisioner=fake_provisioner)

    result = reconciler.reconcile(deployment_id)
    assert result.status == "ready"

    deployment = db_session.get(DeploymentORM, deployment_id)
    values = fake_provisioner.calls[2][1]["values"]
    assert values["caelus"]["plan"] == {"storageBytes": 10737418240, "storageSize": "10Gi"}
    # Ingress/TLS injected alongside plan, under the same caelus namespace.
    assert values["caelus"]["ingress"] == {
        "enabled": True,
        "host": "reconcile.example.test",
        "tls": {
            "wildcard": False,
            "issuer": "letsencrypt-http",
            "secretName": f"{deployment.name}-tls",
        },
    }
    # Other values still present
    assert values["replicas"] == 1
    assert values["user"]["message"] == "hello"


def test_reconcile_injects_empty_caelus_plan_when_no_storage_quota(db_session) -> None:
    """When plan has no storage quota, caelus.plan is injected but empty."""
    deployment_id = _seed_deployment(db_session, storage_bytes=None)
    fake_provisioner = FakeProvisioner()
    reconciler = DeploymentReconciler(session=db_session, provisioner=fake_provisioner)

    result = reconciler.reconcile(deployment_id)
    assert result.status == "ready"

    values = fake_provisioner.calls[2][1]["values"]
    assert values["caelus"]["plan"] == {}
    assert values["caelus"]["ingress"]["enabled"] is True
    assert values["replicas"] == 1


# --- _build_ingress_overrides unit tests (app-tls-termination) -----------------


def _patch_wildcard_domains(monkeypatch, domains: list[str]) -> None:
    monkeypatch.setattr(
        "app.services.reconcile.get_settings",
        lambda: CaelusSettings(
            wildcard_domains=domains, tls_cluster_issuer="letsencrypt-http", domain="example.test", _env_file=None
        ),
    )


def test_build_ingress_overrides_custom_domain(monkeypatch) -> None:
    """A custom domain is classified non-wildcard and gets a per-app HTTP-01 cert."""
    _patch_wildcard_domains(monkeypatch, ["freepod.eu"])
    deployment = SimpleNamespace(hostname="app.example.com", name="immich-ab12cd")

    overrides = DeploymentReconciler._build_ingress_overrides(deployment)

    assert overrides == {
        "caelus": {
            "ingress": {
                "enabled": True,
                "host": "app.example.com",
                "tls": {
                    "wildcard": False,
                    "issuer": "letsencrypt-http",
                    "secretName": "immich-ab12cd-tls",
                },
            }
        }
    }


def test_build_ingress_overrides_wildcard_domain(monkeypatch) -> None:
    """A *.freepod.eu host is wildcard: enabled, no per-app issuer or secret."""
    _patch_wildcard_domains(monkeypatch, ["freepod.eu"])
    deployment = SimpleNamespace(hostname="hw.freepod.eu", name="helloworld-ab12cd")

    ingress = DeploymentReconciler._build_ingress_overrides(deployment)["caelus"]["ingress"]

    assert ingress["enabled"] is True
    assert ingress["host"] == "hw.freepod.eu"
    assert ingress["tls"]["wildcard"] is True
    assert "issuer" not in ingress["tls"]
    assert "secretName" not in ingress["tls"]


def test_build_ingress_overrides_hostname_case_insensitive(monkeypatch) -> None:
    """Classification and host are lower-cased."""
    _patch_wildcard_domains(monkeypatch, ["freepod.eu"])
    deployment = SimpleNamespace(hostname="HW.Freepod.EU", name="helloworld-ab12cd")

    ingress = DeploymentReconciler._build_ingress_overrides(deployment)["caelus"]["ingress"]

    assert ingress["host"] == "hw.freepod.eu"
    assert ingress["tls"]["wildcard"] is True


def test_build_ingress_overrides_no_hostname_returns_none(monkeypatch) -> None:
    """A deployment without a hostname gets no ingress block."""
    _patch_wildcard_domains(monkeypatch, ["freepod.eu"])
    deployment = SimpleNamespace(hostname=None, name="naas-ab12cd")

    assert DeploymentReconciler._build_ingress_overrides(deployment) is None


# --- _build_owner_overrides unit tests -----------------------------------------


def test_build_owner_overrides_projects_email_and_id() -> None:
    """The owning user's email and id are published under caelus.owner for charts
    to use. The id is what the `custom` product's chart asserts a user-supplied image
    reference against, so it must be projected alongside the email."""
    deployment = SimpleNamespace(user=SimpleNamespace(email="owner@example.com", id=42))

    assert DeploymentReconciler._build_owner_overrides(deployment) == {
        "caelus": {"owner": {"email": "owner@example.com", "id": 42}}
    }


def test_build_owner_overrides_projects_id_as_int() -> None:
    """The id stays an int: charts compare it against the string prefix of an image
    reference themselves, so any stringification belongs in the template, not here."""
    deployment = SimpleNamespace(user=SimpleNamespace(email="owner@example.com", id=7))

    owner = DeploymentReconciler._build_owner_overrides(deployment)["caelus"]["owner"]

    assert owner["id"] == 7
    assert isinstance(owner["id"], int)


def test_build_owner_overrides_includes_only_present_fields() -> None:
    """A partially populated user contributes only what it has, so a chart that needs
    the missing field hits `required`/`fail` instead of an empty string."""
    assert DeploymentReconciler._build_owner_overrides(
        SimpleNamespace(user=SimpleNamespace(email=None, id=5))
    ) == {"caelus": {"owner": {"id": 5}}}
    assert DeploymentReconciler._build_owner_overrides(
        SimpleNamespace(user=SimpleNamespace(email="owner@example.com", id=None))
    ) == {"caelus": {"owner": {"email": "owner@example.com"}}}


def test_build_owner_overrides_without_user_returns_none() -> None:
    """No owner, no block — charts that require it fail loudly rather than
    rendering an empty invite address."""
    assert DeploymentReconciler._build_owner_overrides(SimpleNamespace(user=None)) is None
    assert (
        DeploymentReconciler._build_owner_overrides(
            SimpleNamespace(user=SimpleNamespace(email=None, id=None))
        )
        is None
    )


def test_build_owner_overrides_id_is_not_shadowable_by_user_values() -> None:
    """The assertion in the `custom` chart is only sound because system overrides are
    merged last: a tenant cannot pass caelus.owner.id in their own values to claim
    someone else's image."""
    system_overrides = DeploymentReconciler._build_owner_overrides(
        SimpleNamespace(user=SimpleNamespace(email="owner@example.com", id=5))
    )

    merged = template_values.merge_values_scoped(
        {},
        {"caelus": {"owner": {"id": 7, "email": "attacker@example.com"}}},
        system_overrides,
    )

    assert merged["caelus"]["owner"] == {"id": 5, "email": "owner@example.com"}
