"""The nextcloud-sso chart is the catalog Nextcloud chart until SSO is turned on.

It is a sandbox copy, so without `auth.enabled` and `auth.protocol: oidc` it
must render what the catalog chart renders. With SSO on, Nextcloud signs in
through the provider, the client secret stays out of every rendered object, the
owner is provisioned by subject, and the chart refuses to render without the
access list that decides who gets an account. Shells out to a real
`helm template`; skipped when helm is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PRODUCTS = Path(__file__).resolve().parents[2] / "products"
CHART = PRODUCTS / "nextcloud-sso" / "chart"
CATALOG_CHART = PRODUCTS / "nextcloud" / "chart"

HOST = "cloud.example.test"
ISSUER = "https://login.example.test"
SUBJECT = "0b0e2c3a-1111-4222-8333-444455556666"
SSO = {
    "auth": {"enabled": True, "protocol": "oidc", "access": "listed"},
    "caelus": {
        "oidc": {"issuer": ISSUER, "clientId": "dep-1", "secretName": "t-oidc"},
        "owner": {"email": "owner@example.test", "id": 7, "subject": SUBJECT},
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
    """Each object by kind and name, the chart label and the config checksum
    that covers it dropped, and a Secret reduced to its keys, whose generated
    values differ on every render."""

    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k not in ("helm.sh/chart", "checksum/config")}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    out = {}
    for doc in docs:
        doc = strip(doc)
        if doc["kind"] == "Secret":
            doc["stringData"] = sorted(doc.get("stringData", {}))
            doc["data"] = sorted(doc.get("data", {}))
        out[(doc["kind"], doc["metadata"]["name"])] = doc
    return out


def _by_name(docs: list[dict], name: str) -> dict:
    return next(d for d in docs if d["metadata"]["name"] == name)


def _nextcloud(docs: list[dict]) -> dict:
    pod = next(
        d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "t-nextcloud"
    )["spec"]["template"]["spec"]
    return next(c for c in pod["containers"] if c["name"] == "nextcloud")


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"caelus": {"vars": {"secretName": "t-vars"}}},
        {"auth": {"enabled": False, "protocol": "oidc"}},
        {"auth": {"enabled": True}},
    ],
    ids=["no auth", "with vars", "disabled", "header protocol"],
)
def test_without_sso_it_renders_the_catalog_chart(tmp_path, values):
    catalog = {k: v for k, v in values.items() if k != "auth"}
    assert _comparable(_render(tmp_path, values)) == _comparable(_render(tmp_path, catalog, CATALOG_CHART))


def test_sso_requires_the_access_list(tmp_path):
    values = {**SSO, "auth": {**SSO["auth"], "access": "anyone"}}
    result = _helm_template(tmp_path, values)

    assert result.returncode != 0
    assert "needs auth.access listed" in result.stderr


@pytest.mark.parametrize(
    "path",
    [("oidc", "issuer"), ("oidc", "clientId"), ("oidc", "secretName"), ("owner", "subject"), ("owner", "email")],
)
def test_sso_refuses_to_render_without_what_it_needs(tmp_path, path):
    block, key = path
    caelus = {k: dict(v) for k, v in SSO["caelus"].items()}
    del caelus[block][key]
    result = _helm_template(tmp_path, {**SSO, "caelus": caelus})

    assert result.returncode != 0
    assert f"caelus.{block}.{key}" in result.stderr


def test_it_configures_the_provider_and_the_owner(tmp_path):
    docs = _render(tmp_path, SSO)
    config = _by_name(docs, "t-config")["data"]
    hooks = _by_name(docs, "t-hooks")["data"]

    assert config["FREEPOD_OIDC_DISCOVERY_URI"] == f"{ISSUER}/.well-known/openid-configuration"
    assert config["FREEPOD_OIDC_CLIENT_ID"] == "dep-1"
    assert config["FREEPOD_OWNER_SUBJECT"] == SUBJECT
    assert config["FREEPOD_OWNER_EMAIL"] == "owner@example.test"
    sso = hooks["00-sso.sh"]
    assert sorted(hooks)[0] == "00-sso.sh"
    for line in (
        "set -eu",
        "$occ upgrade",
        "user_oidc:provider freepod",
        "--clientsecret-env=OIDC_CLIENT_SECRET",
        "--unique-uid=0",
        "--mapping-uid=sub",
        "--send-id-token-hint=1",
        "--group-provisioning=0",
        "--value=0 user_oidc allow_multiple_user_backends",
        "user_oidc soft_auto_provision --type=boolean --value=false",
        'php "$hooks/owner.php"',
        'user:disable "$NEXTCLOUD_ADMIN_USER"',
    ):
        assert line in sso, line
    assert "FREEPOD_OWNER_SUBJECT" in hooks["owner.php"]


def test_the_client_secret_is_only_ever_a_reference(tmp_path):
    docs = _render(tmp_path, SSO)
    env = {e["name"]: e for e in _nextcloud(docs)["env"]}

    assert env["OIDC_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"] == {"name": "t-oidc", "key": "OIDC_CLIENT_SECRET"}
    assert "value" not in env["OIDC_CLIENT_SECRET"]
    assert "--clientsecret=" not in _by_name(docs, "t-hooks")["data"]["00-sso.sh"]


def test_the_install_admin_gets_a_generated_password(tmp_path):
    values = {**SSO, "caelus": {**SSO["caelus"], "vars": {"secretName": "t-vars"}}}
    docs = _render(tmp_path, values)
    sources = [s["secretRef"]["name"] for s in _nextcloud(docs)["envFrom"] if "secretRef" in s]

    assert _by_name(docs, "t-admin")["stringData"]["NEXTCLOUD_ADMIN_PASSWORD"]
    assert sources[:2] == ["t-vars", "t-admin"]


def test_the_hooks_are_sso_only(tmp_path):
    hooks = _by_name(_render(tmp_path, {}), "t-hooks")["data"]

    assert "00-sso.sh" not in hooks
    assert "owner.php" not in hooks


def test_the_freepod_app_is_mounted_only_with_sso(tmp_path):
    docs = _render(tmp_path, SSO)
    app = _by_name(docs, "t-freepod-app")["data"]
    pod = next(
        d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "t-nextcloud"
    )["spec"]["template"]
    [volume] = [v for v in pod["spec"]["volumes"] if v["name"] == "freepod-app"]
    mounts = {m["name"]: m for m in _nextcloud(docs)["volumeMounts"]}
    files = CHART / "files" / "freepod"

    assert {i["path"]: app[i["key"]] for i in volume["configMap"]["items"]} == {
        str(f.relative_to(files)): f.read_text() for f in files.rglob("*") if f.is_file()
    }
    assert mounts["freepod-app"] == {
        "name": "freepod-app", "mountPath": "/var/www/html/custom_apps/freepod", "readOnly": True,
    }
    assert pod["metadata"]["annotations"]["checksum/freepod-app"]
    assert "$occ app:enable freepod" in _by_name(docs, "t-hooks")["data"]["00-sso.sh"]
    assert "t-freepod-app" not in {d["metadata"]["name"] for d in _render(tmp_path, {})}


def test_access_is_revoked_only_on_the_platform_claim(tmp_path):
    controller = (CHART / "files" / "freepod" / "lib" / "Controller" / "BackchannelController.php").read_text()

    assert "backChannelLogout(self::PROVIDER, $logout_token)" in controller
    assert "($claims['freepod_access'] ?? null) !== 'revoked'" in controller
    assert "invalidateTokensOfUser($uid, null)" in controller
