"""The catalog's pinned version reaches the Mattermost container.

`upstream.version_path` points into `template.system_values`, and the upgrader
writes the winning tag there and nowhere else. Nothing in the chart's own
release consults the catalog, so a key the chart does not read would leave the
upgrader bumping a value that never reaches a pod, silently. Shells out to a
real `helm template`; skipped when helm is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PRODUCTS = Path(__file__).resolve().parents[2] / "products"
CHART = PRODUCTS / "mattermost" / "chart"
CATALOG = PRODUCTS / "catalog" / "mattermost.yaml"
REPOSITORY = "mattermost/mattermost-team-edition"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


@pytest.fixture(scope="module", autouse=True)
def _resolved_dependencies():
    result = subprocess.run(
        ["helm", "dependency", "build", str(CHART)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def _mattermost_tags(tmp_path: Path, values: dict) -> set[str]:
    values_file = tmp_path / "values.yaml"
    # The reconciler injects the plan's storage size, and the chart has no
    # default for it, so rendering standalone has to supply one.
    base = {"host": "mattermost.example.test", "caelus": {"plan": {"storageSize": "1Gi"}}}
    values_file.write_text(yaml.safe_dump({**base, **values}))
    result = subprocess.run(
        ["helm", "template", "t", str(CHART), "-f", str(values_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    tags = set()
    for doc in yaml.safe_load_all(result.stdout):
        pod = ((doc or {}).get("spec") or {}).get("template", {}).get("spec", {})
        for container in pod.get("initContainers", []) + pod.get("containers", []):
            repo, _, tag = container["image"].rpartition(":")
            if repo == REPOSITORY:
                tags.add(tag)
    return tags


def _catalog() -> dict:
    return yaml.safe_load(CATALOG.read_text())


def test_catalog_version_path_drives_the_mattermost_image(tmp_path):
    catalog = _catalog()
    node = catalog
    for key in catalog["upstream"]["version_path"].split("."):
        node = node[key]

    assert _mattermost_tags(tmp_path, catalog["template"]["system_values"]) == {node}


def test_an_overridden_tag_reaches_the_container(tmp_path):
    assert _mattermost_tags(tmp_path, {"mattermost": {"image": {"tag": "9.9.9"}}}) == {"9.9.9"}
