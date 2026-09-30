"""Every product chart stamps `caelus.dev/release-id` on its application pods.

The reconciler hands `caelus.releaseId` to every chart, and the log API pins a
read to a release by that label with no per-chart condition. So a chart whose
application pods lack it answers every pinned read with an empty stream, and
that is only caught here. Charts are discovered rather than listed, so a new
product is held to the contract from its first commit.

Datastores are the one exemption, declared below by the template that renders
them: a fresh id on every release would restart the database on every apply,
var-only changes included. Everything not declared is an application workload
and must carry the label. See `custom.podLabels` for why the label goes on the
pod template and nowhere else.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PRODUCTS = Path(__file__).resolve().parents[2] / "products"
CHARTS = sorted(p.parent.parent.name for p in PRODUCTS.glob("*/chart/Chart.yaml"))

LABEL = "caelus.dev/release-id"
RELEASE_ID = "3f2a9c14-0b6d-4e18-9a77-5c1e8d4b2f60"
RELEASE = {"caelus.releaseId": RELEASE_ID, "caelus.releaseNumber": "7"}

WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}

# Workloads running a third-party database or cache rather than the product,
# keyed by the `# Source:` path helm prints above each document.
DATASTORES = {
    "bookstack": {"bookstack/templates/mysql.yaml"},
    "immich": {"immich/templates/postgres.yaml", "immich/templates/valkey.yaml"},
    "lemmy": {"lemmy/templates/postgres.yaml"},
    "mattermost": {"mattermost/templates/postgresql.yaml"},
    "nextcloud": {"nextcloud/templates/postgres.yaml"},
    "photoprism": {"photoprism/templates/mariadb.yaml"},
}

# The minimum each chart needs to render standalone, unrelated to the label:
# values a real deployment always has and a bare `helm template` does not.
MINIMUM_VALUES = {
    "custom": {
        "hostname": "app.example.test",
        "caelus.owner.id": "1",
        "caelus.registry.prefix": "cr.test.example/u",
        "caelus.registry.pullSecret": "t-registry-pull",
    },
    "mattermost": {"caelus.plan.storageSize": "1Gi"},
    "vaultwarden": {"host": "v.example.test", "caelus.owner.email": "owner@example.test"},
}

# Charts with SFTP require the platform's public key, which the reconciler
# injects per environment.
PLATFORM_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIV5/SURDe/M7JtAheJuxURSGgpFB8Yfrd/LY6c9+DzR platform"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


@pytest.fixture(scope="module", autouse=True)
def _resolved_dependencies():
    """`charts/` is a build artifact (`**/*.tgz` is gitignored), so a clean
    checkout cannot render a chart with dependencies until they are built.
    `build` rather than `update`, so the tracked `Chart.lock` decides and is
    not rewritten; `ssh-sidecar` is a `file://` path, so this runs offline."""
    for chart in CHARTS:
        chart_dir = PRODUCTS / chart / "chart"
        if "dependencies:" not in (chart_dir / "Chart.yaml").read_text():
            continue
        result = subprocess.run(
            ["helm", "dependency", "build", str(chart_dir)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{chart}: {result.stderr}"


def _render(chart: str, values: dict[str, str]) -> str:
    args = [
        "helm", "template", "t", str(PRODUCTS / chart / "chart"),
        "--set-string", f"caelus.ssh.platformPublicKey={PLATFORM_KEY}",
    ]
    for key, value in MINIMUM_VALUES.get(chart, {}).items():
        args += ["--set", f"{key}={value}"]
    for key, value in values.items():
        args += ["--set-string", f"{key}={value}"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, f"{chart}: {result.stderr}"
    return result.stdout


def _documents(rendered: str) -> list[tuple[str, dict]]:
    """Each rendered object with the template it came from."""
    out = []
    for chunk in rendered.split("\n---"):
        source = next(
            (line.removeprefix("# Source: ").strip()
             for line in chunk.splitlines() if line.startswith("# Source: ")),
            None,
        )
        doc = yaml.safe_load(chunk)
        if isinstance(doc, dict) and source is not None:
            out.append((source, doc))
    return out


def _pod_template(doc: dict) -> dict:
    spec = doc.get("spec") or {}
    if doc["kind"] == "CronJob":
        return (spec.get("jobTemplate") or {}).get("spec", {}).get("template") or {}
    return spec.get("template") or {}


def _workloads(rendered: str) -> list[tuple[str, dict]]:
    return [(s, d) for s, d in _documents(rendered) if d.get("kind") in WORKLOAD_KINDS]


def _name(source: str, doc: dict) -> str:
    return f"{doc['kind']} {doc['metadata']['name']} ({source})"


@pytest.mark.parametrize("chart", CHARTS)
def test_every_application_pod_carries_the_release_id(chart):
    datastores = DATASTORES.get(chart, set())
    workloads = _workloads(_render(chart, RELEASE))
    applications = [(s, d) for s, d in workloads if s not in datastores]
    assert applications, f"{chart} rendered no application workload"

    unlabeled = [
        _name(s, d) for s, d in applications
        if (_pod_template(d).get("metadata") or {}).get("labels", {}).get(LABEL) != RELEASE_ID
    ]
    assert not unlabeled, f"{chart}: application pods without {LABEL}: {unlabeled}"


@pytest.mark.parametrize("chart", CHARTS)
def test_datastores_carry_no_release_id(chart):
    """Otherwise every release restarts the database."""
    datastores = DATASTORES.get(chart, set())
    labeled = [
        _name(s, d) for s, d in _workloads(_render(chart, RELEASE))
        if s in datastores and LABEL in ((_pod_template(d).get("metadata") or {}).get("labels") or {})
    ]
    assert not labeled, f"{chart}: datastores carrying {LABEL}: {labeled}"


@pytest.mark.parametrize("chart", CHARTS)
def test_the_release_id_appears_on_pod_templates_only(chart):
    """Never a workload selector (immutable, so the next apply fails) and never
    a Service selector (traffic drops mid-rollout). Counting occurrences over
    the whole render catches every other placement too."""
    rendered = _render(chart, RELEASE)
    selectors = [
        _name(s, d) for s, d in _documents(rendered)
        if LABEL in str((d.get("spec") or {}).get("selector") or {})
    ]
    assert not selectors, f"{chart}: selectors naming {LABEL}: {selectors}"

    stamped = sum(
        LABEL in ((_pod_template(d).get("metadata") or {}).get("labels") or {})
        for _, d in _workloads(rendered)
    )
    assert rendered.count(LABEL) == stamped, f"{chart}: {LABEL} rendered outside a pod template"


@pytest.mark.parametrize("chart", CHARTS)
def test_a_standalone_render_emits_no_release_label(chart):
    """No id supplied means no label at all, not an empty one."""
    assert LABEL not in _render(chart, {})


@pytest.mark.parametrize("chart", sorted(DATASTORES))
def test_every_declared_datastore_is_rendered(chart):
    """A stale exemption would silently cover whatever lands at that path next."""
    sources = {s for s, _ in _workloads(_render(chart, RELEASE))}
    assert DATASTORES[chart] <= sources, f"{chart}: {DATASTORES[chart] - sources} renders no workload"
