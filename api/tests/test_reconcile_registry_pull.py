"""The reconciler publishes each deployment's registry pull credential.

What these assert is the wiring of D11: a dockerconfigjson Secret in the
deployment's namespace, before Helm runs, whose password is a recomputation
from the platform's HMAC key -- and that Helm is handed its name, never its
contents.
"""

from __future__ import annotations

import base64
import json

import pytest

from app.config import CaelusSettings
from app.models import DeploymentORM
from app.services import registry_tokens
from app.services.reconcile import DeploymentReconciler
from tests.provisioner_utils import FakeProvisioner
from tests.test_reconcile_object_storage import _helm_values, _seed

HOST = "cr.test.example"
HMAC_KEY = "test-pull-hmac-key"


def _use_settings(monkeypatch, **registry) -> None:
    settings = CaelusSettings(
        wildcard_domains=[],
        tls_cluster_issuer="letsencrypt-http",
        domain="example.test",
        _env_file=None,
        **registry,
    )
    monkeypatch.setattr("app.services.reconcile.get_settings", lambda: settings)


@pytest.fixture
def reconciled(db_session, monkeypatch) -> tuple[DeploymentORM, FakeProvisioner]:
    _use_settings(monkeypatch, registry_host=HOST, registry_pull_hmac_key=HMAC_KEY)
    deployment_id = _seed(db_session, storage_enabled=False)
    provisioner = FakeProvisioner()
    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)
    return db_session.get(DeploymentORM, deployment_id), provisioner


def _pull_secret_calls(provisioner: FakeProvisioner) -> list[tuple[int, dict]]:
    return [
        (i, call[1])
        for i, call in enumerate(provisioner.calls)
        if call[0] == "upsert_secret" and call[1]["name"].endswith("-registry-pull")
    ]


def test_every_deployment_gets_its_owners_pull_credential(reconciled):
    deployment, provisioner = reconciled
    [(_, secret)] = _pull_secret_calls(provisioner)

    assert secret["name"] == f"{deployment.name}-registry-pull"
    assert secret["namespace"] == deployment.namespace
    assert secret["secret_type"] == "kubernetes.io/dockerconfigjson"
    entry = json.loads(secret["string_data"][".dockerconfigjson"])["auths"][HOST]
    assert entry["username"] == f"pull-{deployment.user_id}"
    assert entry["password"] == registry_tokens.pull_password(HMAC_KEY, deployment.user_id)
    assert base64.b64decode(entry["auth"]).decode() == f"{entry['username']}:{entry['password']}"


def test_the_credential_is_published_before_helm_and_only_named_to_it(reconciled):
    deployment, provisioner = reconciled
    [(published_at, _)] = _pull_secret_calls(provisioner)
    helm_at = next(i for i, call in enumerate(provisioner.calls) if call[0] == "helm_upgrade_install")
    values = _helm_values(provisioner)

    assert published_at < helm_at
    assert values["caelus"]["registry"] == {
        "prefix": f"{HOST}/u",
        "pullSecret": f"{deployment.name}-registry-pull",
    }
    assert registry_tokens.pull_password(HMAC_KEY, deployment.user_id) not in json.dumps(values)


def test_no_registry_configured_publishes_and_names_nothing(db_session, monkeypatch):
    _use_settings(monkeypatch)
    deployment_id = _seed(db_session, storage_enabled=False)
    provisioner = FakeProvisioner()

    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    assert _pull_secret_calls(provisioner) == []
    assert "registry" not in _helm_values(provisioner).get("caelus", {})
