"""The immich-sso chart is the catalog Immich chart until SSO is turned on.

It is a sandbox copy, so with `sso.enabled` off it must render what the catalog
chart renders, apart from waiting for Postgres before Immich starts, and nothing it does with SSO on may put the client secret into a
rendered object. Shells out to a real `helm template`; skipped when helm is
unavailable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PRODUCTS = Path(__file__).resolve().parents[2] / "products"
CHART = PRODUCTS / "immich-sso" / "chart"
CATALOG_CHART = PRODUCTS / "immich" / "chart"

HOST = "photos.example.test"

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


def _without_chart_label(node):
    if isinstance(node, dict):
        return {k: _without_chart_label(v) for k, v in node.items() if k != "helm.sh/chart"}
    if isinstance(node, list):
        return [_without_chart_label(v) for v in node]
    return node


def _comparable(docs: list[dict]) -> dict[tuple[str, str], dict]:
    """Each object by kind and name, with the chart label dropped, Immich's
    config parsed, so formatting differences in the config file don't count,
    and the copy's wait for Postgres left out."""
    out = {}
    for doc in docs:
        doc = _without_chart_label(doc)
        if doc["kind"] == "ConfigMap":
            doc["data"] = {k: yaml.safe_load(v) for k, v in doc["data"].items()}
        pod = doc.get("spec", {}).get("template", {}).get("spec", {})
        if "initContainers" in pod:
            pod["initContainers"] = [c for c in pod["initContainers"] if c["name"] != "wait-for-postgres"]
            if not pod["initContainers"]:
                del pod["initContainers"]
        out[(doc["kind"], doc["metadata"]["name"])] = doc
    return out


@pytest.mark.parametrize(
    "values",
    [{}, {"smtp": {"host": "smtp.example.test", "port": 25, "from": "immich@example.test"}}],
    ids=["bare", "smtp"],
)
def test_without_sso_it_renders_the_catalog_chart(tmp_path, values):
    assert _comparable(_render(tmp_path, values)) == _comparable(
        _render(tmp_path, values, CATALOG_CHART)
    )


SSO = {
    "sso": {"enabled": True},
    "caelus": {
        "oidc": {"issuer": "https://login.example.test", "clientId": "dep-42", "secretName": "t-oidc"},
        "owner": {"email": "owner@example.test"},
    },
}


def _with(values: dict, path: str, value) -> dict:
    """A deep copy of `values` with the dotted `path` set, or removed when
    `value` is None."""
    out = yaml.safe_load(yaml.safe_dump(values))
    node = out
    *parents, leaf = path.split(".")
    for key in parents:
        node = node.setdefault(key, {})
    if value is None:
        node.pop(leaf, None)
    else:
        node[leaf] = value
    return out


def _immich_config(docs: list[dict]) -> dict:
    (config,) = [d for d in docs if d["kind"] == "ConfigMap"]
    return json.loads(config["data"]["immich-config.yaml"])


def _server_pod(docs: list[dict]) -> dict:
    (pod,) = [
        d["spec"]["template"]["spec"]
        for d in docs
        if d["kind"] == "Deployment" and d["metadata"]["name"] == "t-server"
    ]
    return pod


def _server_container(docs: list[dict]) -> dict:
    return _main_container(_server_pod(docs))


def _main_container(pod: dict) -> dict:
    (main,) = [c for c in pod["containers"] if c["name"] == "main"]
    return main


def _init_container(pod: dict, name: str) -> dict:
    (init,) = [c for c in pod.get("initContainers", []) if c["name"] == name]
    return init


@pytest.mark.parametrize(
    ("path", "missing"),
    [
        ("caelus.oidc", "caelus.oidc.issuer"),
        ("caelus.oidc.clientId", "caelus.oidc.clientId"),
        ("caelus.oidc.secretName", "caelus.oidc.secretName"),
        ("caelus.owner.email", "caelus.owner.email"),
    ],
)
def test_sso_refuses_to_render_without_what_it_needs(tmp_path, path, missing):
    result = _helm_template(tmp_path, _with(SSO, path, None))
    assert result.returncode != 0
    assert missing in result.stderr


def test_without_sso_the_config_is_json_without_oauth(tmp_path):
    config = _immich_config(_render(tmp_path, {}))
    assert config == {"server": {"externalDomain": f"https://{HOST}"}}


def test_sso_configures_oauth_against_the_provider(tmp_path):
    config = _immich_config(_render(tmp_path, SSO))
    assert config["oauth"] == {
        "enabled": True,
        "issuerUrl": "https://login.example.test",
        "clientId": "dep-42",
        "scope": "openid email profile",
        "signingAlgorithm": "RS256",
        "tokenEndpointAuthMethod": "client_secret_post",
        "autoRegister": False,
        "autoLaunch": True,
        "buttonText": "Sign in with Freepod",
        "mobileOverrideEnabled": False,
        "endSessionEndpoint": (
            "https://login.example.test/oidc/logout?client_id=dep-42"
            "&post_logout_redirect_uri=https%3A%2F%2Fphotos.example.test%2F"
        ),
    }
    assert config["passwordLogin"] == {"enabled": False}
    assert config["server"] == {"externalDomain": f"https://{HOST}"}


def test_no_rendered_object_carries_a_client_secret(tmp_path):
    """The chart never receives the secret; the init container reads it from
    the published Secret at pod start."""
    docs = _render(tmp_path, SSO)
    assert "clientSecret" not in _immich_config(docs)["oauth"]
    assert "clientSecret" not in yaml.safe_dump([d for d in docs if d["kind"] == "ConfigMap"])
    assert {d["metadata"]["name"] for d in docs if d["kind"] == "Secret"} == {"t-postgresql-auth"}


def test_only_the_init_container_reads_the_oidc_secret(tmp_path):
    docs = _render(tmp_path, SSO)
    pod = _server_pod(docs)
    init = _init_container(pod, "config")
    assert init["env"] == [
        {
            "name": "OIDC_CLIENT_SECRET",
            "valueFrom": {"secretKeyRef": {"name": "t-oidc", "key": "OIDC_CLIENT_SECRET"}},
        }
    ]
    assert "envFrom" not in init

    others = [
        c
        for d in docs
        if d["kind"] == "Deployment"
        for c in d["spec"]["template"]["spec"]["containers"]
        + d["spec"]["template"]["spec"].get("initContainers", [])
        if c is not init
    ]
    assert "t-oidc" not in yaml.safe_dump(others)
    assert "OIDC_CLIENT_SECRET" not in yaml.safe_dump(others)


def test_sso_mounts_the_merged_config_from_memory(tmp_path):
    pod = _server_pod(_render(tmp_path, SSO))
    volumes = {v["name"]: v for v in pod["volumes"]}
    assert volumes["config"]["emptyDir"]["medium"] == "Memory"
    assert volumes["config-source"]["configMap"] == {"name": "t-config"}
    mounts = {m["name"]: m["mountPath"] for m in _main_container(pod)["volumeMounts"]}
    assert mounts["config"] == "/config"
    assert "config-source" not in mounts


def test_without_sso_the_server_mounts_the_configmap(tmp_path):
    pod = _server_pod(_render(tmp_path, {}))
    volumes = {v["name"]: v for v in pod["volumes"]}
    assert volumes["config"] == {"name": "config", "configMap": {"name": "t-config"}}
    assert [c["name"] for c in pod["initContainers"]] == ["wait-for-postgres"]


def _merge(tmp_path: Path, env: dict) -> subprocess.CompletedProcess:
    docs = _render(tmp_path, SSO)
    node, flag, script, source, target = _init_container(_server_pod(docs), "config")["command"]
    assert (node, flag) == ("node", "-e")
    assert source.startswith("/config-source/") and target.startswith("/config/")
    (tmp_path / "source.json").write_text(json.dumps(_immich_config(docs)))
    return subprocess.run(
        ["node", "-e", script, str(tmp_path / "source.json"), str(tmp_path / "target.json")],
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"], **env},
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_init_container_merges_the_secret_into_the_config(tmp_path):
    result = _merge(tmp_path, {"OIDC_CLIENT_SECRET": "s3cret"})
    assert result.returncode == 0, result.stderr
    merged = json.loads((tmp_path / "target.json").read_text())
    assert merged["oauth"]["clientSecret"] == "s3cret"
    assert {k: v for k, v in merged["oauth"].items() if k != "clientSecret"} == _immich_config(
        _render(tmp_path, SSO)
    )["oauth"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_init_container_fails_without_the_secret(tmp_path):
    result = _merge(tmp_path, {})
    assert result.returncode != 0
    assert "OIDC_CLIENT_SECRET" in result.stderr
    assert not (tmp_path / "target.json").exists()


def test_the_owner_hook_runs_only_with_sso(tmp_path):
    assert "lifecycle" not in _server_container(_render(tmp_path, {}))

    hook = _server_container(_render(tmp_path, SSO))["lifecycle"]["postStart"]["exec"]["command"]
    assert hook[:2] == ["node", "-e"]
    assert "/auth/admin-sign-up" in hook[2]
    assert '"owner@example.test"' in hook[2]


@pytest.mark.parametrize("values", [{}, SSO], ids=["without-sso", "sso"])
def test_immich_waits_for_postgres_before_anything_else(tmp_path, values):
    """Immich exits while Postgres refuses connections, and with SSO on it
    would take the owner hook down with it."""
    (first, *_) = _server_pod(_render(tmp_path, values))["initContainers"]
    assert first["name"] == "wait-for-postgres"
    assert "pg_isready -h t-postgresql" in first["command"][-1]


def test_an_external_database_needs_no_wait(tmp_path):
    assert "initContainers" not in _server_pod(_render(tmp_path, {"postgresql": {"enabled": False}}))
