"""The PeerTube chart renders what the catalog pins and the reconciler injects.

`upstream.version_path` points into `template.system_values`, and the upgrader
writes the winning tag there and nowhere else. PeerTube's image runs twice per
pod, as the setup init container and as the application, and both must run the
catalog's tag, digest included.

PeerTube logs the password of the administrator it creates on first start, so
the tenant's password must reach the setup container alone, which sets it
through stdin, and never the application. Shells out to a real
`helm template`; skipped when helm is unavailable.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PRODUCTS = Path(__file__).resolve().parents[3] / "products"
CHART = PRODUCTS / "peertube" / "chart"
CATALOG = PRODUCTS / "catalog" / "peertube" / "peertube.yaml"
REPOSITORY = "docker.io/chocobozzz/peertube"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


@pytest.fixture(scope="module", autouse=True)
def _resolved_dependencies():
    result = subprocess.run(
        ["helm", "dependency", "build", str(CHART)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def _render(tmp_path: Path, values: dict) -> list[dict]:
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.safe_dump({"host": "videos.example.test", **values}))
    result = subprocess.run(
        ["helm", "template", "t", str(CHART), "-f", str(values_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]


def _pods(docs: list[dict]) -> dict[str, dict]:
    return {
        d["metadata"]["name"]: d["spec"]["template"]["spec"]
        for d in docs
        if d["kind"] in ("Deployment", "StatefulSet")
    }


def _containers(docs: list[dict]) -> dict[str, dict]:
    containers = {}
    for pod in _pods(docs).values():
        for container in pod.get("initContainers", []) + pod.get("containers", []):
            containers[container["name"]] = container
    return containers


def _env(container: dict) -> dict[str, dict]:
    return {e["name"]: e for e in container.get("env", [])}


def _catalog() -> dict:
    return yaml.safe_load(CATALOG.read_text())


def test_catalog_version_path_drives_both_peertube_containers(tmp_path):
    catalog = _catalog()
    node = catalog
    for key in catalog["upstream"]["version_path"].split("."):
        node = node[key]

    tags = {}
    for name, container in _containers(_render(tmp_path, catalog["template"]["system_values"])).items():
        reference, at, digest = container["image"].partition("@")
        repo, _, tag = reference.rpartition(":")
        if repo == REPOSITORY:
            tags[name] = tag + at + digest
    assert tags == {"setup": str(node), "peertube": str(node)}


def test_the_upstream_match_accepts_the_pinned_tag():
    catalog = _catalog()
    tag = catalog["template"]["system_values"]["image"]["tag"]
    assert re.fullmatch(catalog["upstream"]["match"], tag)


def test_the_password_reaches_the_setup_container_only(tmp_path):
    docs = _render(tmp_path, {"caelus": {"vars": {"secretName": "t-vars"}}})
    assert {d["metadata"]["name"] for d in docs if d["kind"] == "Secret"} == {"t-peertube"}

    containers = _containers(docs)
    setup = _env(containers["setup"])
    assert setup["PEERTUBE_ADMIN_PASSWORD"]["valueFrom"]["secretKeyRef"]["name"] == "t-vars"
    assert "PT_INITIAL_ROOT_PASSWORD" not in setup

    app = containers["peertube"]
    assert not {"PEERTUBE_ADMIN_PASSWORD", "PT_INITIAL_ROOT_PASSWORD"} & set(_env(app))
    assert [s["secretRef"]["name"] for s in app["envFrom"]] == ["t-peertube"]


def test_the_owner_is_the_administrator(tmp_path):
    docs = _render(tmp_path, {"caelus": {"owner": {"email": "owner@example.test"}}})
    for name in ("setup", "peertube"):
        assert _env(_containers(docs)[name])["PEERTUBE_ADMIN_EMAIL"]["value"] == "owner@example.test"


def test_live_streaming_is_pinned_off(tmp_path):
    """Live ingest is RTMP, which nothing routes to the pod; an environment
    variable outranks what the admin UI saves."""
    env = _env(_containers(_render(tmp_path, {}))["peertube"])
    assert env["PEERTUBE_LIVE_ENABLED"]["value"] == "false"
    assert env["PEERTUBE_LIVE_RTMP_ENABLED"]["value"] == "false"


def test_every_pod_prefers_the_catalog_node_pool(tmp_path):
    pool = _catalog()["template"]["system_values"]["nodePool"]
    pods = _pods(_render(tmp_path, {"nodePool": pool}))
    assert set(pods) == {"t-peertube", "t-postgres", "t-redis"}
    for pod in pods.values():
        assert pod["hostUsers"] is False
        assert pod["tolerations"] == [
            {"key": "caelus.dev/node-pool", "operator": "Equal", "value": pool, "effect": "NoSchedule"}
        ]


def test_the_file_session_shows_the_storage_tree_and_not_the_settings(tmp_path):
    """The volume holds data/ and config/; the session sees data/ alone, and the
    database and cache volumes stay in pods of their own."""
    pod = _pods(_render(tmp_path, {}))["t-peertube"]
    claims = [v["persistentVolumeClaim"]["claimName"] for v in pod["volumes"] if "persistentVolumeClaim" in v]
    assert claims == ["data"]

    ssh = next(c for c in pod["containers"] if c["name"] != "peertube")
    assert [(m["name"], m.get("subPath")) for m in ssh["volumeMounts"] if m["name"] == "data"] == [("data", "data")]


def test_the_data_volume_takes_the_plan_size(tmp_path):
    docs = _render(tmp_path, {"caelus": {"plan": {"storageSize": "25Gi"}}})
    (claim,) = [d for d in docs if d["kind"] == "PersistentVolumeClaim" and d["metadata"]["name"] == "data"]
    assert claim["spec"]["resources"]["requests"]["storage"] == "25Gi"
