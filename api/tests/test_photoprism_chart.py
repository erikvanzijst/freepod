"""The catalog's pinned version reaches the PhotoPrism container.

`upstream.version_path` points into `template.system_values`, and the upgrader
writes the winning tag there and nowhere else. Nothing in the chart's own
release consults the catalog, so a key the chart does not read would leave the
upgrader bumping a value that never reaches a pod, silently.

PhotoPrism's versions are six-digit dates, which makes the pin unusual among
the curated products: written unquoted it is a YAML integer, and the chart's
values schema refuses it. Rendering the catalog's own system values is what
keeps that from reaching a tenant. Shells out to a real `helm template`;
skipped when helm is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PRODUCTS = Path(__file__).resolve().parents[2] / "products"
CHART = PRODUCTS / "photoprism" / "chart"
CATALOG = PRODUCTS / "catalog" / "photoprism.yaml"
REPOSITORY = "docker.io/photoprism/photoprism"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


@pytest.fixture(scope="module", autouse=True)
def _resolved_dependencies():
    result = subprocess.run(
        ["helm", "dependency", "build", str(CHART)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def _photoprism_tags(tmp_path: Path, values: dict) -> set[str]:
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.safe_dump({"host": "photos.example.test", **values}))
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


def test_catalog_version_path_drives_the_photoprism_image(tmp_path):
    catalog = _catalog()
    node = catalog
    for key in catalog["upstream"]["version_path"].split("."):
        node = node[key]

    assert _photoprism_tags(tmp_path, catalog["template"]["system_values"]) == {node}


def test_the_pinned_version_is_a_string():
    """A date read as an integer renders as one and fails the values schema."""
    assert isinstance(_catalog()["template"]["system_values"]["image"]["tag"], str)


def test_an_overridden_tag_reaches_the_container(tmp_path):
    assert _photoprism_tags(tmp_path, {"image": {"tag": "999999"}}) == {"999999"}
