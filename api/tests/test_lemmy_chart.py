"""The catalog's one upstream version drives every Lemmy image.

The upgrader writes the winning tag to `upstream.version_path` and nothing else,
while lemmy-ui (which also serves as the render-config init) is only supported
against its matching backend. So the chart must derive the frontend tag from the
backend's, and the catalog must not pin it separately. Shells out to a real
`helm template`; skipped when helm is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PRODUCTS = Path(__file__).resolve().parents[2] / "products"
CHART = PRODUCTS / "lemmy" / "chart"
CATALOG = PRODUCTS / "catalog" / "lemmy.yaml"
LEMMY_REPOS = ("docker.io/dessalines/lemmy", "docker.io/dessalines/lemmy-ui")

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


@pytest.fixture(scope="module", autouse=True)
def _resolved_dependencies():
    result = subprocess.run(
        ["helm", "dependency", "build", str(CHART)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def _lemmy_images(tmp_path: Path, values: dict) -> dict[str, set[str]]:
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.safe_dump({"host": "lemmy.example.test", **values}))
    result = subprocess.run(
        ["helm", "template", "t", str(CHART), "-f", str(values_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    tags: dict[str, set[str]] = {repo: set() for repo in LEMMY_REPOS}
    for doc in yaml.safe_load_all(result.stdout):
        pod = ((doc or {}).get("spec") or {}).get("template", {}).get("spec", {})
        for container in pod.get("initContainers", []) + pod.get("containers", []):
            repo, _, tag = container["image"].rpartition(":")
            if repo in tags:
                tags[repo].add(tag)
    return tags


def _catalog() -> dict:
    return yaml.safe_load(CATALOG.read_text())


def test_catalog_version_path_drives_backend_and_frontend(tmp_path):
    catalog = _catalog()
    node = catalog
    for key in catalog["upstream"]["version_path"].split("."):
        node = node[key]
    version = node

    images = _lemmy_images(tmp_path, catalog["template"]["system_values"])

    assert images == {repo: {version} for repo in LEMMY_REPOS}


def test_catalog_does_not_pin_the_frontend_separately():
    assert "ui" not in _catalog()["template"]["system_values"]


def test_frontend_follows_an_overridden_backend_tag(tmp_path):
    images = _lemmy_images(tmp_path, {"image": {"tag": "9.9.9"}})

    assert images == {repo: {"9.9.9"} for repo in LEMMY_REPOS}


def test_explicit_frontend_tag_still_wins(tmp_path):
    images = _lemmy_images(tmp_path, {"image": {"tag": "9.9.9"}, "ui": {"image": {"tag": "9.9.8"}}})

    assert images == {LEMMY_REPOS[0]: {"9.9.9"}, LEMMY_REPOS[1]: {"9.9.8"}}
