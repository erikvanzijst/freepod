"""The discourse-sso chart is the catalog Discourse chart until SSO is turned on.

It is a sandbox copy, so without `auth.enabled` and `auth.protocol: oidc` it
must render what the catalog chart renders, minus the SSH access it leaves out
in favor of Discourse's own backup and restore. With SSO on, nothing may sign in
except through the provider, the client secret stays out of every rendered
object, and the forum stays open to anonymous readers: no forward-auth in
front, and its registration settings left to the tenant. Shells out to a real
`helm template`; skipped when helm is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PRODUCTS = Path(__file__).resolve().parents[2] / "products"
CHART = PRODUCTS / "discourse-sso" / "chart"
CATALOG_CHART = PRODUCTS / "discourse" / "chart"

HOST = "forum.example.test"
ISSUER = "https://login.example.test"
SSO = {
    "auth": {"enabled": True, "protocol": "oidc", "access": "anyone"},
    "caelus": {
        "oidc": {"issuer": ISSUER, "clientId": "dep-1", "secretName": "t-oidc"},
        "owner": {"email": "owner@example.test", "id": 7},
    },
}

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


@pytest.fixture(scope="module", autouse=True)
def _resolved_dependencies():
    for chart in (CHART, CATALOG_CHART):
        result = subprocess.run(
            ["helm", "dependency", "build", str(chart)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr


def _helm_template(tmp_path: Path, values: dict, chart: Path = CHART) -> subprocess.CompletedProcess:
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.safe_dump({"host": HOST, **values}))
    return subprocess.run(
        ["helm", "template", "t", str(chart), "-f", str(values_file)],
        capture_output=True,
        text=True,
    )


def _render(tmp_path: Path, values: dict, chart: Path = CHART) -> list[dict]:
    result = _helm_template(tmp_path, values, chart)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]


def _comparable(docs: list[dict]) -> dict[tuple[str, str], dict]:
    """Each object by kind and name, the chart label dropped, a Secret reduced
    to its keys, whose generated values differ on every render, and SSH left
    out."""

    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != "helm.sh/chart"}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    out = {}
    for doc in docs:
        doc = strip(doc)
        if doc["metadata"]["name"].endswith("-ssh"):
            continue
        if doc["kind"] == "Secret":
            doc["stringData"] = sorted(doc.get("stringData", {}))
        if doc["kind"] == "Deployment":
            pod = doc["spec"]["template"]["spec"]
            pod["containers"] = [c for c in pod["containers"] if c["name"] == "discourse"]
        out[(doc["kind"], doc["metadata"]["name"])] = doc
    return out


def _discourse(docs: list[dict]) -> dict:
    return next(
        d["spec"]["template"]["spec"]
        for d in docs
        if d["kind"] == "Deployment" and d["metadata"]["name"] == "t-discourse"
    )


def _env(container: dict) -> dict[str, dict]:
    return {e["name"]: e for e in container["env"]}


def _containers(docs: list[dict]) -> dict[str, dict]:
    pod = _discourse(docs)
    return {c["name"]: c for c in pod["initContainers"] + pod["containers"]}


@pytest.mark.parametrize(
    "values",
    [{}, {"auth": {"enabled": False, "protocol": "oidc"}}, {"auth": {"enabled": True}}],
    ids=["no auth", "disabled", "header protocol"],
)
def test_without_sso_it_renders_the_catalog_chart(tmp_path, values):
    assert _comparable(_render(tmp_path, values)) == _comparable(_render(tmp_path, {}, CATALOG_CHART))


def test_it_pins_sign_in_to_the_provider(tmp_path):
    containers = _containers(_render(tmp_path, SSO))

    for name in ("setup", "discourse"):
        env = _env(containers[name])
        for key, value in {
            "DISCOURSE_OPENID_CONNECT_ENABLED": "true",
            "DISCOURSE_OPENID_CONNECT_DISCOVERY_DOCUMENT": f"{ISSUER}/.well-known/openid-configuration",
            "DISCOURSE_OPENID_CONNECT_CLIENT_ID": "dep-1",
            "DISCOURSE_OPENID_CONNECT_AUTHORIZE_SCOPE": "openid email profile",
            "DISCOURSE_OPENID_CONNECT_USE_PKCE": "true",
            "DISCOURSE_ENABLE_LOCAL_LOGINS": "false",
            "DISCOURSE_ENABLE_LOCAL_LOGINS_VIA_EMAIL": "false",
            "DISCOURSE_ENABLE_PASSKEYS": "false",
            "DISCOURSE_ENABLE_DISCOURSE_CONNECT": "false",
            "DISCOURSE_AUTH_OVERRIDES_EMAIL": "true",
            "DISCOURSE_EMAIL_EDITABLE": "false",
        }.items():
            assert env[key]["value"] == value, key


def test_signing_out_returns_to_the_forum(tmp_path):
    env = _env(_containers(_render(tmp_path, SSO))["discourse"])

    assert env["DISCOURSE_OPENID_CONNECT_RP_INITIATED_LOGOUT"]["value"] == "true"
    assert env["DISCOURSE_OPENID_CONNECT_RP_INITIATED_LOGOUT_INCLUDE_CLIENT_ID"]["value"] == "true"
    assert env["DISCOURSE_OPENID_CONNECT_RP_INITIATED_LOGOUT_REDIRECT"]["value"] == f"https://{HOST}/"


def test_the_client_secret_is_only_ever_a_reference(tmp_path):
    ref = _env(_containers(_render(tmp_path, SSO))["discourse"])["DISCOURSE_OPENID_CONNECT_CLIENT_SECRET"]

    assert ref["valueFrom"]["secretKeyRef"] == {"name": "t-oidc", "key": "OIDC_CLIENT_SECRET"}
    assert "value" not in ref


def test_the_owner_has_no_password(tmp_path):
    docs = _render(tmp_path, SSO)
    setup = _env(_containers(docs)["setup"])
    seed = next(d for d in docs if d["metadata"]["name"] == "t-seed")["data"]["seed_owner.rb"]

    assert setup["DISCOURSE_ADMIN_EMAIL"]["value"] == "owner@example.test"
    assert "DISCOURSE_ADMIN_PASSWORD" not in setup
    assert "DISCOURSE_ADMIN_PASSWORD" not in seed
    assert "t-admin" not in {d["metadata"]["name"] for d in docs}


def test_the_logout_plugin_is_mounted_only_with_sso(tmp_path):
    docs = _render(tmp_path, SSO)
    plugin = next(d for d in docs if d["metadata"]["name"] == "t-plugin")["data"]["plugin.rb"]
    source = (CHART / "files" / "freepod-backchannel-logout" / "plugin.rb").read_text()
    pod = _discourse(docs)
    mounts = {m["name"]: m for m in _containers(docs)["discourse"]["volumeMounts"]}

    assert plugin.strip() == source.strip()
    assert '"/freepod/backchannel-logout"' in plugin
    assert mounts["plugin"]["mountPath"] == "/var/www/discourse/plugins/freepod-backchannel-logout"
    assert mounts["plugin"]["readOnly"] is True
    assert {"name": "plugin", "configMap": {"name": "t-plugin"}} in pod["volumes"]
    assert "plugin" not in {m["name"] for m in _containers(docs)["setup"]["volumeMounts"]}
    assert "t-plugin" not in {d["metadata"]["name"] for d in _render(tmp_path, {})}


def test_a_changed_plugin_restarts_the_forum(tmp_path):
    docs = _render(tmp_path, SSO)
    template = next(
        d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "t-discourse"
    )["spec"]["template"]

    assert template["metadata"]["annotations"]["checksum/plugin"]


def test_the_forum_stays_public_and_decides_who_joins(tmp_path):
    docs = _render(tmp_path, SSO)
    env = _env(_containers(docs)["discourse"])

    assert not [d for d in docs if d["kind"] == "Middleware" and "forwardAuth" in d["spec"]]
    for setting in ("LOGIN_REQUIRED", "ALLOW_NEW_REGISTRATIONS", "INVITE_ONLY", "MUST_APPROVE_USERS"):
        assert f"DISCOURSE_{setting}" not in env


@pytest.mark.parametrize(
    "missing, message",
    [
        ("issuer", "caelus.oidc.issuer"),
        ("clientId", "caelus.oidc.clientId"),
        ("secretName", "caelus.oidc.secretName"),
    ],
)
def test_sso_refuses_to_render_without_the_oidc_client(tmp_path, missing, message):
    oidc = {k: v for k, v in SSO["caelus"]["oidc"].items() if k != missing}
    result = _helm_template(tmp_path, {**SSO, "caelus": {**SSO["caelus"], "oidc": oidc}})

    assert result.returncode != 0
    assert message in result.stderr


def test_sso_refuses_to_render_without_the_owner(tmp_path):
    result = _helm_template(tmp_path, {**SSO, "caelus": {"oidc": SSO["caelus"]["oidc"]}})

    assert result.returncode != 0
    assert "caelus.owner.email" in result.stderr
