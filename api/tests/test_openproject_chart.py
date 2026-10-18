"""The OpenProject chart renders what the catalog pins and the reconciler injects.

`upstream.version_path` points into `template.system_values`, and the upgrader
writes the winning tag there and nowhere else, so the catalog's tag must be the
one every OpenProject container runs, and hocuspocus must follow it.

The owner account is seeded from `caelus.owner.email`, which the reconciler
injects; a chart that ignored it would seed every tenant with the standalone
default. Shells out to a real `helm template`; skipped when helm is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PRODUCTS = Path(__file__).resolve().parents[2] / "products"
CHART = PRODUCTS / "openproject" / "chart"
CATALOG = PRODUCTS / "catalog" / "openproject" / "openproject.yaml"
REPOSITORY = "docker.io/openproject/openproject"
HOCUSPOCUS = "docker.io/openproject/hocuspocus"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


@pytest.fixture(scope="module", autouse=True)
def _resolved_dependencies():
    result = subprocess.run(
        ["helm", "dependency", "build", str(CHART)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def _render(tmp_path: Path, values: dict) -> list[dict]:
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.safe_dump({"host": "projects.example.test", **values}))
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


def _env(container: dict) -> dict[str, dict]:
    return {e["name"]: e for e in container.get("env", [])}


def _catalog() -> dict:
    return yaml.safe_load(CATALOG.read_text())


def test_catalog_version_path_drives_every_openproject_container(tmp_path):
    catalog = _catalog()
    node = catalog
    for key in catalog["upstream"]["version_path"].split("."):
        node = node[key]

    docs = _render(tmp_path, catalog["template"]["system_values"])
    images = {name: c["image"] for name, c in _containers(docs).items()}
    assert {n: i for n, i in images.items() if i.startswith(REPOSITORY + ":")} == {
        "seeder": f"{REPOSITORY}:{node}",
        "web": f"{REPOSITORY}:{node}",
        "worker": f"{REPOSITORY}:{node}",
    }
    assert images["hocuspocus"] == f"{HOCUSPOCUS}:{node.removesuffix('-slim')}"


def test_the_owner_account_is_seeded_from_the_injected_email(tmp_path):
    docs = _render(tmp_path, {"caelus": {"owner": {"email": "owner@example.test"}}})
    env = _env(_containers(docs)["seeder"])
    assert env["OPENPROJECT_SEED__ADMIN__USER__MAIL"]["value"] == "owner@example.test"
    assert env["OPENPROJECT_SEED__ADMIN__USER__PASSWORD__RESET"]["value"] == "false"


def test_a_platform_supplied_password_suppresses_the_generated_one(tmp_path):
    docs = _render(tmp_path, {"caelus": {"vars": {"secretName": "t-vars"}}})
    secrets = {d["metadata"]["name"] for d in docs if d["kind"] == "Secret"}
    assert secrets == {"t-db"}
    ref = _env(_containers(docs)["seeder"])["OPENPROJECT_SEED__ADMIN__USER__PASSWORD"]
    assert ref["valueFrom"]["secretKeyRef"] == {"name": "t-vars", "key": "OPENPROJECT_ADMIN_PASSWORD"}


def test_platform_settings_reach_every_openproject_process(tmp_path):
    """A setting given by environment is read-only in OpenProject's
    administration, so each process must carry the same value."""
    docs = _render(tmp_path, {"smtp": {"host": "smtp.example.test"}})
    containers = _containers(docs)
    for name in ("seeder", "web", "worker"):
        env = _env(containers[name])
        assert env["OPENPROJECT_HOST__NAME"]["value"] == "projects.example.test"
        assert env["OPENPROJECT_SMTP__ADDRESS"]["value"] == "smtp.example.test"
        assert env["OPENPROJECT_COLLABORATIVE__EDITING__HOCUSPOCUS__URL"]["value"] == (
            "wss://projects.example.test/hocuspocus"
        )


def test_the_file_session_pod_claims_only_the_assets_volume(tmp_path):
    """The SSH sidecar shares the application pod, so the database volume must
    stay in a pod of its own."""
    (pod,) = [
        d["spec"]["template"]["spec"]
        for d in _render(tmp_path, {})
        if d["kind"] == "Deployment" and d["metadata"]["name"] == "t-openproject"
    ]
    claims = [v["persistentVolumeClaim"]["claimName"] for v in pod["volumes"] if "persistentVolumeClaim" in v]
    assert claims == ["assets"]
