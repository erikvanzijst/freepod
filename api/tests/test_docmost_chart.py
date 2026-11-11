"""The Docmost chart renders what the catalog pins and the reconciler injects.

`upstream.version_path` points into `template.system_values`, and the upgrader
writes the winning tag there and nowhere else, so the catalog's tag must be the
one the application container runs.

The owner account is created from `caelus.owner.email`, which the reconciler
injects; a chart that ignored it would sign every tenant in as the standalone
default. Shells out to a real `helm template`; skipped when helm is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PRODUCTS = Path(__file__).resolve().parents[2] / "products"
CHART = PRODUCTS / "docmost" / "chart"
CATALOG = PRODUCTS / "catalog" / "docmost" / "docmost.yaml"
REPOSITORY = "docker.io/docmost/docmost"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


@pytest.fixture(scope="module", autouse=True)
def _resolved_dependencies():
    result = subprocess.run(
        ["helm", "dependency", "build", str(CHART)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def _render(tmp_path: Path, values: dict) -> list[dict]:
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.safe_dump({"host": "wiki.example.test", **values}))
    result = subprocess.run(
        ["helm", "template", "t", str(CHART), "-f", str(values_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]


def _containers(docs: list[dict]) -> dict[str, dict]:
    containers = {}
    for doc in docs:
        pod = doc.get("spec", {}).get("template", {}).get("spec", {})
        for container in pod.get("initContainers", []) + pod.get("containers", []):
            containers[container["name"]] = container
    return containers


def _catalog() -> dict:
    return yaml.safe_load(CATALOG.read_text())


def test_catalog_version_path_drives_the_docmost_container(tmp_path):
    catalog = _catalog()
    node = catalog
    for key in catalog["upstream"]["version_path"].split("."):
        node = node[key]

    docs = _render(tmp_path, catalog["template"]["system_values"])
    images = {
        name: c["image"] for name, c in _containers(docs).items() if c["image"].startswith(REPOSITORY)
    }
    assert images == {"docmost": f"{REPOSITORY}:{node}"}


def test_the_owner_account_uses_the_injected_email(tmp_path):
    docs = _render(tmp_path, {"caelus": {"owner": {"email": "owner@example.test"}}})
    env = {e["name"]: e.get("value") for e in _containers(docs)["docmost"]["env"]}
    assert env["DOCMOST_ADMIN_EMAIL"] == "owner@example.test"


def test_a_platform_supplied_password_suppresses_the_generated_one(tmp_path):
    docs = _render(tmp_path, {"caelus": {"vars": {"secretName": "t-vars"}}})
    secrets = {d["metadata"]["name"] for d in docs if d["kind"] == "Secret"}
    assert secrets == {"t-db"}
    sources = [s["secretRef"]["name"] for s in _containers(docs)["docmost"]["envFrom"]]
    assert sources == ["t-vars", "t-db"]


def test_the_file_session_pod_claims_only_the_storage_volume(tmp_path):
    """The SSH sidecar shares the application pod, so the database and queue
    volumes must stay in pods of their own."""
    (pod,) = [
        d["spec"]["template"]["spec"]
        for d in _render(tmp_path, {})
        if d["kind"] == "Deployment" and d["metadata"]["name"] == "t-docmost"
    ]
    claims = [v["persistentVolumeClaim"]["claimName"] for v in pod["volumes"] if "persistentVolumeClaim" in v]
    assert claims == ["storage"]


def test_redis_clears_an_empty_lost_and_found_first(tmp_path):
    """storage-chart-contract: redis:8's entrypoint skips its ownership fix while
    a fresh volume's lost+found is there."""
    [redis] = [d for d in _render(tmp_path, {}) if d["kind"] == "StatefulSet" and d["metadata"]["name"].endswith("-redis")]
    pod = redis["spec"]["template"]["spec"]
    [init] = pod["initContainers"]
    assert init["image"] == pod["containers"][0]["image"]
    assert init["command"] == ["sh", "-c", "rmdir /data/lost+found 2>/dev/null || true"]
    assert init["volumeMounts"] == [{"name": "data", "mountPath": "/data"}]
