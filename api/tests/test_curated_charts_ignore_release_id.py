"""The nine curated charts are handed the release identity and ignore it.

The reconciler supplies `caelus.releaseId` and `caelus.releaseNumber` to *every*
product with no per-product condition — rendering them is each chart's decision,
and only `custom` does (the id as a pod label, the number by handing it to the
SSH sidecar). This asserts the other half of that: a chart that ignores them
applies normally and its pods carry no release label, so the deployment's logs
stay fully readable at `{namespace, instance}` granularity with only release
pinning unavailable.

Schema rejection was never the risk — every curated chart sets
`caelus.additionalProperties: true` and `mattermost` has no schema at all — so
what this confirms is the *render* path.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PRODUCTS = Path(__file__).resolve().parents[2] / "products"
RELEASE_ID = "3f2a9c14-0b6d-4e18-9a77-5c1e8d4b2f60"
RELEASE = {"caelus.releaseId": RELEASE_ID, "caelus.releaseNumber": "7"}

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

# The minimum each chart needs to render standalone, unrelated to this change:
# values a real deployment always has and a bare `helm template` does not.
CURATED = {
    "bookstack": {},
    "helloworld": {},
    "immich": {},
    "matrix": {},
    "mattermost": {"caelus.plan.storageSize": "1Gi"},
    "naas": {},
    "nextcloud": {},
    "photoprism": {},
    "vaultwarden": {"host": "v.example.test", "caelus.owner.email": "owner@example.test"},
}


@pytest.fixture(scope="module", autouse=True)
def _resolved_dependencies():
    """Resolve each chart's declared dependencies before anything renders.

    `helm template` refuses a chart whose `Chart.yaml` declares a dependency
    absent from `charts/`, and that directory is a **build artifact**:
    `products/.gitignore` ignores `**/*.tgz`, so a clean checkout has none.
    Five of these seven depend on `ssh-sidecar`.

    This is the failure mode where a developer's machine and CI disagree, and
    it disagrees in the dangerous direction: a tree that happens to hold the
    artifacts from an earlier `helm dependency build` passes, while a clean
    checkout does not. That is precisely how it reached CI.

    `build` rather than `update`, so the tracked `Chart.lock` decides what is
    fetched and is not rewritten. The `ssh-sidecar` dependency is a `file://`
    path into `products/_lib`, so this resolves offline and deterministically.
    """
    for chart in CURATED:
        chart_dir = PRODUCTS / chart / "chart"
        if "dependencies:" not in (chart_dir / "Chart.yaml").read_text():
            continue
        result = subprocess.run(
            ["helm", "dependency", "build", str(chart_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{chart}: {result.stderr}"


# Charts with SFTP require the platform's public key, which the reconciler
# injects per environment.
PLATFORM_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIV5/SURDe/M7JtAheJuxURSGgpFB8Yfrd/LY6c9+DzR platform"


def _render(chart: str, values: dict[str, str]) -> str:
    args = [
        "helm", "template", "t", str(PRODUCTS / chart / "chart"),
        "--set-string", f"caelus.ssh.platformPublicKey={PLATFORM_KEY}",
    ]
    for key, value in values.items():
        args += ["--set", f"{key}={value}"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, f"{chart}: {result.stderr}"
    return result.stdout


@pytest.mark.parametrize("chart", sorted(CURATED))
def test_a_curated_chart_applies_while_ignoring_the_release_id(chart):
    baseline = CURATED[chart]
    with_id = _render(chart, {**baseline, **RELEASE})

    # It rendered, and no pod carries a release label.
    assert "caelus.dev/release-id" not in with_id
    for doc in yaml.safe_load_all(with_id):
        if not doc:
            continue
        labels = (
            doc.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {})
            if isinstance(doc.get("spec"), dict)
            else {}
        )
        assert "caelus.dev/release-id" not in (labels or {})


def _pod_template_labels(rendered: str) -> list[dict]:
    """Every workload pod template's labels, in document order."""
    out = []
    for doc in yaml.safe_load_all(rendered):
        if not isinstance(doc, dict) or doc.get("kind") not in {
            "Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"
        }:
            continue
        spec = doc.get("spec") or {}
        template = (
            spec.get("jobTemplate", {}).get("spec", {}).get("template")
            if doc["kind"] == "CronJob"
            else spec.get("template")
        ) or {}
        out.append((template.get("metadata") or {}).get("labels") or {})
    return out


@pytest.mark.parametrize("chart", sorted(CURATED))
def test_the_release_id_does_not_change_a_curated_pod_template(chart):
    """A chart that ignores the value produces the same pod template with and
    without it, so its deployments keep their existing Helm no-op behaviour --
    only `custom` pays the redeploy-cycles-pods cost.

    Compared at the pod template rather than over the whole render: several of
    these charts generate a random secret on every render, so a byte comparison
    would fail on noise unrelated to this change.
    """
    baseline = CURATED[chart]
    without = _pod_template_labels(_render(chart, baseline))
    with_id = _pod_template_labels(_render(chart, {**baseline, **RELEASE}))
    assert without == with_id
    assert without, f"{chart} rendered no workload pod template to compare"
