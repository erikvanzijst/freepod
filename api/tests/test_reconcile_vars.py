"""Materializing a release's vars into the tenant's namespace.

What matters here is mostly what does *not* happen: no value in the Helm
values, no value in a log record, and no Secret at all when a release carries
no vars.
"""

from __future__ import annotations

import json
import logging

import pytest
from cryptography.fernet import Fernet

from app.config import CaelusSettings
from app.models import (
    BillingInterval,
    DeploymentCreate,
    DeploymentORM,
    DeploymentReleaseORM,
    PlanORM,
    PlanTemplateVersionORM,
    ProductORM,
    VarWrite,
)
from app.models.core import _utcnow
from app.services import deployments, products, templates, var_crypto
from app.services import vars as vars_service
from app.services.reconcile import DeploymentReconciler, vars_secret_name
from tests.conftest import make_accepted_user
from tests.provisioner_utils import FakeProvisioner

SECRET = "hunter2-swordfish"

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "host": {"type": "string", "title": "hostname"},
        "LOG_LEVEL": {"type": "string", "x-caelus-target": "runtime"},
        "ADMIN_TOKEN": {
            "type": "string",
            "x-caelus-target": "runtime",
            "x-caelus-sensitive": True,
        },
    },
}


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(
        "app.services.reconcile.get_settings",
        lambda: CaelusSettings(wildcard_domains=[], domain="example.test", _env_file=None),
    )


def _seed(db_session, *, vars: dict | None = None):
    user = make_accepted_user(db_session, "vars-reconcile@example.com")
    product = products.create_product(
        db_session, payload=products.ProductCreate(name="vars-product", description="d")
    )
    template = templates.create_template(
        db_session,
        payload=templates.ProductTemplateVersionCreate(
            product_id=product.id,
            chart_ref="oci://example/chart",
            chart_version="1.2.3",
            system_values_json={"replicas": 1},
            values_schema_json=SCHEMA,
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
            user_values_json={"host": "vars.example.test"},
            plan_template_id=ptv.id,
            vars=vars or {},
        ),
    ).deployment.id


def _helm_values(provisioner: FakeProvisioner) -> dict:
    """The values of the *most recent* apply, which is what a second reconcile
    in one test is asking about."""
    return [c[1]["values"] for c in provisioner.calls if c[0] == "helm_upgrade_install"][-1]


def _secrets(provisioner: FakeProvisioner) -> list[dict]:
    return [c[1] for c in provisioner.calls if c[0] == "upsert_secret"]


def _reaps(provisioner: FakeProvisioner) -> list[dict]:
    return [c[1] for c in provisioner.calls if c[0] == "delete_secrets_by_label"]


def _second_release(db_session, deployment, entries) -> DeploymentReleaseORM:
    """Write vars and mint the release that captures them, as an update would."""
    vars_service.write_vars(
        db_session, deployment=deployment, actor=deployment.user, entries=entries
    )
    release = DeploymentReleaseORM(
        number=2,
        deployment_id=deployment.id,
        template_id=deployment.desired_template_id,
    )
    db_session.add(release)
    db_session.commit()
    db_session.refresh(release)
    vars_service.snapshot_release(
        db_session, release_id=release.id, deployment_id=deployment.id
    )
    deployment.desired_release_id = release.id
    db_session.add(deployment)
    db_session.commit()
    return release


def test_a_release_with_vars_publishes_a_secret_before_helm(db_session):
    deployment_id = _seed(
        db_session,
        vars={
            "LOG_LEVEL": VarWrite(value="debug"),
            "ADMIN_TOKEN": VarWrite(value=SECRET),
        },
    )
    provisioner = FakeProvisioner()

    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    deployment = db_session.get(DeploymentORM, deployment_id)
    release = db_session.get(DeploymentReleaseORM, deployment.desired_release_id)
    secret = _secrets(provisioner)[0]
    assert secret["name"] == vars_secret_name(deployment, release) == f"{deployment.name}-vars-1"
    assert secret["namespace"] == deployment.namespace
    assert secret["string_data"] == {"LOG_LEVEL": "debug", "ADMIN_TOKEN": SECRET}

    # Before Helm, so no pod ever starts expecting a Secret that is not there.
    order = [c[0] for c in provisioner.calls]
    assert order.index("upsert_secret") < order.index("helm_upgrade_install")
    assert order.index("ensure_namespace") < order.index("upsert_secret")


def test_the_merged_values_carry_the_name_and_no_value(db_session):
    deployment_id = _seed(
        db_session,
        vars={"LOG_LEVEL": VarWrite(value="debug"), "ADMIN_TOKEN": VarWrite(value=SECRET)},
    )
    provisioner = FakeProvisioner()

    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    deployment = db_session.get(DeploymentORM, deployment_id)
    release = db_session.get(DeploymentReleaseORM, deployment.desired_release_id)
    values = _helm_values(provisioner)
    assert values["caelus"]["vars"] == {"secretName": vars_secret_name(deployment, release)}
    # Merged values are logged in full and persisted by Helm into a
    # tenant-namespace object, so no value may travel through them.
    serialized = json.dumps(values)
    assert SECRET not in serialized
    assert "debug" not in serialized


def test_a_known_plaintext_reaches_no_log_record(db_session, caplog):
    deployment_id = _seed(db_session, vars={"ADMIN_TOKEN": VarWrite(value=SECRET)})
    provisioner = FakeProvisioner()

    with caplog.at_level(logging.DEBUG):
        DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    assert SECRET not in caplog.text
    # And it did reach the Secret, so the assertion above is not vacuous.
    assert _secrets(provisioner)[0]["string_data"]["ADMIN_TOKEN"] == SECRET


def test_a_release_with_no_vars_produces_no_secret_and_no_block(db_session):
    deployment_id = _seed(db_session)
    provisioner = FakeProvisioner()

    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    assert _secrets(provisioner) == []
    assert "vars" not in _helm_values(provisioner).get("caelus", {})


def test_each_release_gets_its_own_secret_and_supersedes_the_last(db_session):
    """The pod template changes with the Secret's name, so a var-only change
    rolls the pod -- and the superseded Secret is reaped once Helm succeeds."""
    deployment_id = _seed(db_session, vars={"LOG_LEVEL": VarWrite(value="debug")})
    provisioner = FakeProvisioner()
    reconciler = DeploymentReconciler(session=db_session, provisioner=provisioner)
    reconciler.reconcile(deployment_id)

    deployment = db_session.get(DeploymentORM, deployment_id)
    second = _second_release(db_session, deployment, {"LOG_LEVEL": VarWrite(value="trace")})
    reconciler.reconcile(deployment_id)

    assert [secret["name"] for secret in _secrets(provisioner)] == [
        f"{deployment.name}-vars-1",
        f"{deployment.name}-vars-2",
    ]
    # The second apply keeps its own Secret and sweeps the first.
    reaps = _reaps(provisioner)
    assert reaps[-1]["except_name"] == f"{deployment.name}-vars-{second.number}"
    assert reaps[-1]["namespace"] == deployment.namespace


def test_the_reaper_cannot_reach_another_deployments_secrets(db_session):
    """A namespace is not guaranteed to hold exactly one deployment."""
    deployment_id = _seed(db_session, vars={"LOG_LEVEL": VarWrite(value="debug")})
    provisioner = FakeProvisioner()
    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    deployment = db_session.get(DeploymentORM, deployment_id)
    selector = _reaps(provisioner)[0]["selector"]
    assert "caelus.dev/component=vars" in selector
    assert f"app.kubernetes.io/instance={deployment.name}" in selector


def test_a_failed_apply_reaps_nothing(db_session):
    """`--atomic` rolls the pod spec back onto the previous release's Secret,
    which is exactly the object a reap on this path would delete."""
    deployment_id = _seed(db_session, vars={"LOG_LEVEL": VarWrite(value="debug")})
    provisioner = FakeProvisioner()
    provisioner.raise_on_upgrade = RuntimeError("helm exploded")

    result = DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(
        deployment_id
    )

    assert result.status == "error"
    assert _reaps(provisioner) == []


def test_a_release_with_no_vars_reaps_every_secret(db_session):
    """Removing the last var leaves no Secret to keep, and none to reference."""
    deployment_id = _seed(db_session, vars={"LOG_LEVEL": VarWrite(value="debug")})
    provisioner = FakeProvisioner()
    reconciler = DeploymentReconciler(session=db_session, provisioner=provisioner)
    reconciler.reconcile(deployment_id)

    deployment = db_session.get(DeploymentORM, deployment_id)
    _second_release(db_session, deployment, {"LOG_LEVEL": VarWrite(value=None)})
    reconciler.reconcile(deployment_id)

    assert _reaps(provisioner)[-1]["except_name"] is None
    assert "vars" not in _helm_values(provisioner).get("caelus", {})


def test_a_failing_reap_does_not_fail_the_rollout(db_session):
    """Litter is a cheaper failure than the one this naming scheme prevents."""
    deployment_id = _seed(db_session, vars={"LOG_LEVEL": VarWrite(value="debug")})
    provisioner = FakeProvisioner()

    def boom(**_kwargs):
        raise RuntimeError("kubectl unavailable")

    provisioner.delete_secrets_by_label = boom

    result = DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(
        deployment_id
    )

    assert result.status == "ready"


def test_the_applied_snapshot_is_the_releases_not_head(db_session):
    """A var written after the release was created waits for the next one."""
    deployment_id = _seed(db_session, vars={"LOG_LEVEL": VarWrite(value="debug")})
    deployment = db_session.get(DeploymentORM, deployment_id)
    vars_service.write_vars(
        db_session,
        deployment=deployment,
        actor=deployment.user,
        entries={"LOG_LEVEL": VarWrite(value="trace")},
    )
    db_session.commit()

    provisioner = FakeProvisioner()
    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    assert _secrets(provisioner)[0]["string_data"] == {"LOG_LEVEL": "debug"}


def test_an_undecryptable_row_fails_the_reconcile_and_writes_nothing(db_session, monkeypatch):
    """E11: a partial Secret would start a pod missing some of its variables."""
    deployment_id = _seed(
        db_session,
        vars={"LOG_LEVEL": VarWrite(value="debug"), "ADMIN_TOKEN": VarWrite(value=SECRET)},
    )
    stored_key_id = var_crypto.current_key_id()

    # The worker comes up holding a different key than the one that encrypted.
    monkeypatch.setattr(
        "app.services.var_crypto.get_settings",
        lambda: CaelusSettings(
            var_encryption_keys=[Fernet.generate_key().decode()], _env_file=None
        ),
    )
    var_crypto.get_keyring.cache_clear()

    provisioner = FakeProvisioner()
    result = DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(
        deployment_id
    )

    assert result.status == "error"
    assert stored_key_id in result.last_error
    assert _secrets(provisioner) == []
    assert [c[0] for c in provisioner.calls].count("helm_upgrade_install") == 0

    var_crypto.get_keyring.cache_clear()
