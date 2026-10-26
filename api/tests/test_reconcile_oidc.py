"""The reconciler publishes OIDC client credentials for SSO-enabled deployments.

What these assert is D10 of app-oidc-provider: a Secret in the deployment's
namespace before Helm runs, references only in the values, and no Secret once
SSO is off.
"""

from __future__ import annotations

import json
import logging

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
from app.services import app_auth_oidc, deployments, products, template_values, templates
from app.services.reconcile import DeploymentReconciler
from tests.conftest import make_accepted_user
from tests.provisioner_utils import FakeProvisioner
from tests.test_reconcile_object_storage import _helm_values

ISSUER = "https://login.dev.freepod.eu"
KEYS = "c1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    settings = CaelusSettings(
        tls_cluster_issuer="letsencrypt-http",
        domain="example.test",
        app_auth_oidc_issuer=ISSUER,
        app_auth_oidc_client_keys=KEYS,
        _env_file=None,
    )
    monkeypatch.setattr("app.services.reconcile.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.app_auth_oidc.get_settings", lambda: settings)


def _seed(db_session, *, system_sso: dict | None, user_sso: dict | None) -> DeploymentORM:
    user = make_accepted_user(db_session, "sso-user@example.com")
    product = products.create_product(
        db_session, payload=products.ProductCreate(name="sso-product", description="d")
    )
    system_values: dict = {"replicas": 1}
    if system_sso is not None:
        system_values["sso"] = system_sso
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
                    },
                    "sso": {
                        "type": "object",
                        "properties": {"enabled": {"type": "boolean"}},
                        "additionalProperties": False,
                    },
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
        plan_id=plan.id, price_cents=0, billing_interval=BillingInterval.MONTHLY, created_at=_utcnow()
    )
    db_session.add(ptv)
    db_session.flush()
    plan.template_id = ptv.id
    db_session.commit()

    user_values: dict = {"user": {"domain": "wiki.example.test"}}
    if user_sso is not None:
        user_values["sso"] = user_sso
    deployment_id = deployments.create_deployment(
        db_session,
        payload=DeploymentCreate(
            user_id=user.id,
            desired_template_id=template.id,
            user_values_json=user_values,
            plan_template_id=ptv.id,
        ),
    ).deployment.id
    return db_session.get(DeploymentORM, deployment_id)


DECLARES = {"redirectPaths": ["/oidc/callback"]}


def _reconcile(db_session, deployment: DeploymentORM) -> FakeProvisioner:
    provisioner = FakeProvisioner()
    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment.id)
    return provisioner


def _oidc_secrets(provisioner: FakeProvisioner) -> list[tuple[int, dict]]:
    return [
        (i, call[1])
        for i, call in enumerate(provisioner.calls)
        if call[0] == "upsert_secret" and call[1]["name"].endswith("-oidc")
    ]


def _oidc_removals(provisioner: FakeProvisioner) -> list[dict]:
    return [
        call[1]
        for call in provisioner.calls
        if call[0] == "delete_secrets_by_label" and "caelus.dev/component=oidc" in call[1]["selector"]
    ]


def test_enabled_publishes_credentials_before_helm_and_names_them_only(db_session, caplog):
    deployment = _seed(db_session, system_sso=DECLARES, user_sso={"enabled": True})
    caplog.set_level(logging.DEBUG)
    provisioner = _reconcile(db_session, deployment)

    [(published_at, secret)] = _oidc_secrets(provisioner)
    helm_at = next(i for i, call in enumerate(provisioner.calls) if call[0] == "helm_upgrade_install")
    client_secret = app_auth_oidc.oidc_client_secret(deployment.id)
    assert published_at < helm_at
    assert secret["name"] == f"{deployment.name}-oidc"
    assert secret["namespace"] == deployment.namespace
    assert secret["labels"]["caelus.dev/component"] == "oidc"
    assert secret["string_data"] == {
        "OIDC_ISSUER": ISSUER,
        "OIDC_CLIENT_ID": str(deployment.id),
        "OIDC_CLIENT_SECRET": client_secret,
    }

    values = _helm_values(provisioner)
    assert values["caelus"]["oidc"] == {
        "issuer": ISSUER,
        "clientId": str(deployment.id),
        "secretName": f"{deployment.name}-oidc",
    }
    assert client_secret not in json.dumps(values)
    assert client_secret not in caplog.text
    db_session.refresh(deployment)
    assert client_secret not in json.dumps(deployment.user_values_json)
    assert _oidc_removals(provisioner) == []


def test_a_user_value_overrides_the_templates_default(db_session):
    deployment = _seed(db_session, system_sso={**DECLARES, "enabled": False}, user_sso={"enabled": True})
    provisioner = _reconcile(db_session, deployment)
    assert len(_oidc_secrets(provisioner)) == 1
    assert _helm_values(provisioner)["sso"]["enabled"] is True


def test_template_forced(db_session):
    deployment = _seed(db_session, system_sso={**DECLARES, "enabled": True}, user_sso=None)
    provisioner = _reconcile(db_session, deployment)
    assert len(_oidc_secrets(provisioner)) == 1
    assert _helm_values(provisioner)["caelus"]["oidc"]["clientId"] == str(deployment.id)


@pytest.mark.parametrize(
    ("system_sso", "user_sso"),
    [
        (DECLARES, None),
        (DECLARES, {"enabled": False}),
        ({**DECLARES, "enabled": True}, {"enabled": False}),
        (None, None),
    ],
    ids=["default off", "user off", "user turns the template's off", "no sso"],
)
def test_disabled_publishes_and_names_nothing(db_session, system_sso, user_sso):
    deployment = _seed(db_session, system_sso=system_sso, user_sso=user_sso)
    provisioner = _reconcile(db_session, deployment)
    assert _oidc_secrets(provisioner) == []
    values = _helm_values(provisioner)
    assert "oidc" not in values.get("caelus", {})
    assert values.get("sso", {}).get("enabled") is not True
    [removal] = _oidc_removals(provisioner)
    assert removal["namespace"] == deployment.namespace
    assert f"app.kubernetes.io/instance={deployment.name}" in removal["selector"]


def test_toggled_off_removes_the_secret_after_helm(db_session):
    deployment = _seed(db_session, system_sso=DECLARES, user_sso={"enabled": True})
    assert len(_oidc_secrets(_reconcile(db_session, deployment))) == 1

    deployment.user_values_json = {"user": {"domain": "wiki.example.test"}, "sso": {"enabled": False}}
    db_session.add(deployment)
    db_session.commit()
    provisioner = _reconcile(db_session, deployment)

    assert _oidc_secrets(provisioner) == []
    assert "oidc" not in _helm_values(provisioner).get("caelus", {})
    order = [call[0] for call in provisioner.calls]
    removal_at = next(
        i
        for i, call in enumerate(provisioner.calls)
        if call[0] == "delete_secrets_by_label" and "caelus.dev/component=oidc" in call[1]["selector"]
    )
    assert order.index("helm_upgrade_install") < removal_at


def test_no_provider_configured_publishes_nothing(db_session, monkeypatch):
    settings = CaelusSettings(tls_cluster_issuer="letsencrypt-http", domain="example.test", _env_file=None)
    monkeypatch.setattr("app.services.reconcile.get_settings", lambda: settings)
    deployment = _seed(db_session, system_sso=DECLARES, user_sso={"enabled": True})
    provisioner = _reconcile(db_session, deployment)
    assert _oidc_secrets(provisioner) == []
    assert "oidc" not in _helm_values(provisioner).get("caelus", {})


def test_user_values_cannot_shadow_the_injected_block(db_session):
    deployment = _seed(db_session, system_sso={**DECLARES, "enabled": True}, user_sso=None)
    merged = template_values.merge_values_scoped(
        {},
        {"caelus": {"oidc": {"issuer": "https://evil.example", "secretName": "stolen"}}},
        DeploymentReconciler._build_oidc_overrides(deployment, "wiki-oidc"),
    )
    assert merged["caelus"]["oidc"] == {
        "issuer": ISSUER,
        "clientId": str(deployment.id),
        "secretName": "wiki-oidc",
    }
