"""The Discourse chart renders what the catalog pins and the reconciler injects.

`upstream.version_path` points into `template.system_values`, and the upgrader
writes the winning tag there and nowhere else. Discourse's image runs twice per
pod, as the setup init container and as the application server, and both must
run the catalog's tag, digest included.

The owner account is created from `caelus.owner.email`, which the reconciler
injects; a chart that ignored it would sign every tenant in as the standalone
default. Shells out to a real `helm template`; skipped when helm is unavailable.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PRODUCTS = Path(__file__).resolve().parents[2] / "products"
CHART = PRODUCTS / "discourse" / "chart"
CATALOG = PRODUCTS / "catalog" / "discourse" / "discourse.yaml"
REPOSITORY = "docker.io/discourse/discourse"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


@pytest.fixture(scope="module", autouse=True)
def _resolved_dependencies():
    result = subprocess.run(
        ["helm", "dependency", "build", str(CHART)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def _render(tmp_path: Path, values: dict, namespace: str = "default") -> list[dict]:
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.safe_dump({"host": "forum.example.test", **values}))
    result = subprocess.run(
        ["helm", "template", "t", str(CHART), "-n", namespace, "-f", str(values_file)],
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


def _discourse_tags(docs: list[dict]) -> dict[str, str]:
    tags = {}
    for name, container in _containers(docs).items():
        reference, at, digest = container["image"].partition("@")
        repo, _, tag = reference.rpartition(":")
        if repo == REPOSITORY:
            tags[name] = tag + at + digest
    return tags


def _catalog() -> dict:
    return yaml.safe_load(CATALOG.read_text())


def test_catalog_version_path_drives_both_discourse_containers(tmp_path):
    catalog = _catalog()
    node = catalog
    for key in catalog["upstream"]["version_path"].split("."):
        node = node[key]

    tags = _discourse_tags(_render(tmp_path, catalog["template"]["system_values"]))
    assert tags == {"setup": str(node), "discourse": str(node)}


def test_the_owner_account_uses_the_injected_email(tmp_path):
    docs = _render(tmp_path, {"caelus": {"owner": {"email": "owner@example.test"}}})
    env = {e["name"]: e.get("value") for e in _containers(docs)["setup"]["env"]}
    assert env["DISCOURSE_ADMIN_EMAIL"] == "owner@example.test"


def test_a_platform_supplied_password_suppresses_the_generated_one(tmp_path):
    docs = _render(tmp_path, {"caelus": {"vars": {"secretName": "t-vars"}}})
    secrets = {d["metadata"]["name"] for d in docs if d["kind"] == "Secret"}
    assert secrets == {"t-db"}
    env = {e["name"]: e for e in _containers(docs)["setup"]["env"]}
    assert env["DISCOURSE_ADMIN_PASSWORD"]["valueFrom"]["secretKeyRef"]["name"] == "t-vars"


def test_the_secret_key_base_is_one_discourse_accepts(tmp_path):
    """Anything but 128 lowercase hex digits is silently replaced with a key
    Discourse keeps in Redis, which a Redis without its volume would lose."""
    (secret,) = [d for d in _render(tmp_path, {}) if d["metadata"]["name"] == "t-db"]
    assert re.fullmatch(r"[0-9a-f]{128}", secret["stringData"]["DISCOURSE_SECRET_KEY_BASE"])


def test_every_pod_prefers_the_catalog_node_pool(tmp_path):
    """The database and cache volumes are created wherever their pods first
    land, so all three pods must ask for the same pool."""
    pool = _catalog()["template"]["system_values"]["nodePool"]
    pods = _pods(_render(tmp_path, {"nodePool": pool}))
    assert set(pods) == {"t-discourse", "t-postgres", "t-redis"}
    for pod in pods.values():
        assert pod["hostUsers"] is False
        assert pod["tolerations"] == [
            {"key": "caelus.dev/node-pool", "operator": "Equal", "value": pool, "effect": "NoSchedule"}
        ]
        (term,) = pod["affinity"]["nodeAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"]
        assert term["preference"]["matchExpressions"][0]["values"] == [pool]


def test_the_edge_does_what_upstreams_nginx_does(tmp_path):
    docs = _render(tmp_path, {}, namespace="ns")
    middlewares = {
        d["metadata"]["name"]: d["spec"] for d in docs if d["kind"] == "Middleware"
    }
    assert middlewares["t-strip-accel"] == {"headers": {"customRequestHeaders": {"X-Accel-Mapping": ""}}}
    assert "buffering" in middlewares["t-buffer-uploads"]
    cache = middlewares["t-cache-static"]["headers"]["customResponseHeaders"]["Cache-Control"]
    assert "immutable" in cache

    ingresses = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Ingress"}
    chains = {
        name: ing["metadata"]["annotations"]["traefik.ingress.kubernetes.io/router.middlewares"]
        for name, ing in ingresses.items()
    }
    assert chains == {
        "t-ingress": "ns-t-strip-accel@kubernetescrd",
        "t-uploads": "ns-t-strip-accel@kubernetescrd,ns-t-buffer-uploads@kubernetescrd",
        "t-static": "ns-t-strip-accel@kubernetescrd,ns-t-cache-static@kubernetescrd",
    }

    def paths(name):
        return {p["path"] for p in ingresses[name]["spec"]["rules"][0]["http"]["paths"]}

    assert paths("t-uploads") == {"/uploads.json", "/admin/backups/upload"}
    assert paths("t-static") == {"/assets/", "/plugins/", "/images/emoji/"}


def test_the_file_session_pod_claims_only_the_shared_volume(tmp_path):
    """The SSH sidecar shares the application pod, so the database and cache
    volumes must stay in pods of their own."""
    pod = _pods(_render(tmp_path, {}))["t-discourse"]
    claims = [v["persistentVolumeClaim"]["claimName"] for v in pod["volumes"] if "persistentVolumeClaim" in v]
    assert claims == ["shared"]
