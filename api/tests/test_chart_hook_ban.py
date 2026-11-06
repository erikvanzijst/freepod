"""No catalog chart renders a Helm hook.

A hook runs on every install and upgrade, including those applied to a
deployment at zero replicas, where a hook that needs the app fails and the
atomic apply rolls back. Each chart is rendered with its catalog file's system
values, as a real deployment would be.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest
import yaml

from tests.test_catalog_charts import CATALOG_FILES, PRODUCTS
from tests.test_chart_release_label_contract import (  # noqa: F401
    MINIMUM_VALUES,
    PLATFORM_KEY,
    _documents,
    _resolved_dependencies,
)

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

HOOK_ANNOTATION = "helm.sh/hook"

# What the reconciler injects for features a catalog file's system values turn
# on, beyond what a bare render needs (`MINIMUM_VALUES`).
INJECTED_VALUES = {
    "custom": {
        "caelus.objectStorage.secretName": "t-object-storage",
        "caelus.database.secretName": "t-database",
    },
}


def _render_catalog(catalog_file, tmp_path, *extra: str, env=None) -> list[tuple[str, dict]]:
    """The chart a catalog file pins, rendered with its system values and
    whatever the reconciler would inject; ``extra`` goes to ``helm template``."""
    document = yaml.safe_load(catalog_file.read_text())
    slug = document["product"]["slug"]
    values_file = tmp_path / "system-values.yaml"
    values_file.write_text(yaml.safe_dump(document["template"].get("system_values") or {}))
    args = [
        "helm", "template", "t", str(PRODUCTS / slug / "chart"),
        "-f", str(values_file),
        "--set-string", f"caelus.ssh.platformPublicKey={PLATFORM_KEY}",
    ]
    for key, value in {**MINIMUM_VALUES.get(slug, {}), **INJECTED_VALUES.get(slug, {})}.items():
        args += ["--set", f"{key}={value}"]
    args += extra
    result = subprocess.run(args, capture_output=True, text=True, env=env)
    assert result.returncode == 0, f"{slug}: {result.stderr}"
    return _documents(result.stdout)


@pytest.mark.parametrize("catalog_file", CATALOG_FILES, ids=lambda p: p.stem)
def test_catalog_charts_render_no_hooks(catalog_file, tmp_path):
    hooks = [
        f"{source} ({doc['kind']} {doc['metadata'].get('name')})"
        for source, doc in _render_catalog(catalog_file, tmp_path)
        if HOOK_ANNOTATION in ((doc.get("metadata") or {}).get("annotations") or {})
    ]
    assert not hooks, f"{catalog_file.stem} renders Helm hooks: {hooks}"
