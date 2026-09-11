"""Every catalog file points at the chart this repository publishes.

Reads the real `products/` tree and needs no database, so a chart bump that
leaves its catalog pin behind fails in review rather than at install time.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PRODUCTS = Path(__file__).resolve().parents[2] / "products"
CHARTS_REPOSITORY = "oci://ghcr.io/erikvanzijst/freepod/charts"
CATALOG_FILES = sorted((PRODUCTS / "catalog").glob("*.y*ml"))


def _template_and_chart(catalog_file: Path) -> tuple[dict, dict]:
    document = yaml.safe_load(catalog_file.read_text())
    chart_yaml = PRODUCTS / document["product"]["slug"] / "chart" / "Chart.yaml"
    return document["template"], yaml.safe_load(chart_yaml.read_text())


def test_the_catalog_is_not_empty():
    """Otherwise a moved directory would parametrize the checks below away."""
    assert CATALOG_FILES


@pytest.mark.parametrize("catalog_file", CATALOG_FILES, ids=lambda p: p.stem)
def test_chart_ref_names_the_published_chart(catalog_file):
    template, chart = _template_and_chart(catalog_file)
    assert template["chart_ref"] == f"{CHARTS_REPOSITORY}/{chart['name']}"


@pytest.mark.parametrize("catalog_file", CATALOG_FILES, ids=lambda p: p.stem)
def test_chart_version_matches_the_chart(catalog_file):
    template, chart = _template_and_chart(catalog_file)
    assert template["chart_version"] == chart["version"]
