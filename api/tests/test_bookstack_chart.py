"""The BookStack chart renders what the catalog pins and the reconciler injects.

`upstream.version_path` points into `template.system_values`, and the upgrader
writes the winning tag there and nowhere else. BookStack's image runs twice per
pod -- the setup init container and the application -- so a tag that reached
only one of them would migrate the schema with one release and serve it with
another.

The owner account is written from `caelus.owner.email`, which the reconciler
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
CHART = PRODUCTS / "bookstack" / "chart"
CATALOG = PRODUCTS / "catalog" / "bookstack.yaml"
REPOSITORY = "docker.io/solidnerd/bookstack"

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


def _bookstack_tags(docs: list[dict]) -> dict[str, str]:
    tags = {}
    for name, container in _containers(docs).items():
        repo, _, tag = container["image"].rpartition(":")
        if repo == REPOSITORY:
            tags[name] = tag
    return tags


def _catalog() -> dict:
    return yaml.safe_load(CATALOG.read_text())


def test_catalog_version_path_drives_both_bookstack_containers(tmp_path):
    catalog = _catalog()
    node = catalog
    for key in catalog["upstream"]["version_path"].split("."):
        node = node[key]

    tags = _bookstack_tags(_render(tmp_path, catalog["template"]["system_values"]))
    assert tags == {"setup": str(node), "bookstack": str(node)}


def test_the_owner_account_uses_the_injected_email(tmp_path):
    docs = _render(tmp_path, {"caelus": {"owner": {"email": "owner@example.test"}}})
    env = {e["name"]: e.get("value") for e in _containers(docs)["setup"]["env"]}
    assert env["BOOKSTACK_ADMIN_EMAIL"] == "owner@example.test"


def test_a_platform_supplied_password_suppresses_the_generated_one(tmp_path):
    docs = _render(tmp_path, {"caelus": {"vars": {"secretName": "t-vars"}}})
    secrets = {d["metadata"]["name"] for d in docs if d["kind"] == "Secret"}
    assert secrets == {"t-db"}
    for name in ("setup", "bookstack"):
        sources = [s["secretRef"]["name"] for s in _containers(docs)[name]["envFrom"]]
        assert sources == ["t-vars", "t-db"]
