"""Every product chart meets the storage chart contract
(openspec storage-chart-contract): its claims name no class, request
ReadWriteOnce and are each mounted by one single-pod workload, so the
post-renderer's storage step (deployment-storage-class) never refuses it.

Charts are discovered rather than listed, so a new product is held to this from
its first commit.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest
import yaml

from app import egress_gate, post_render
from tests.test_chart_release_label_contract import (  # noqa: F401
    CHARTS,
    PLATFORM_KEY,
    PRODUCTS,
    _documents,
    _name,
    _pod_template,
    _render,
    _resolved_dependencies,
    _workloads,
)

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

GATE = egress_gate.gate_container(image="gate:1", deadline_seconds=60)

# Charts allowed to break the contract, each with its reason.
EXEMPT = {
    # Rolls its claim on purpose (test_chart_rollout_strategy); not a catalog
    # product, so it never runs on a storage class.
    "helloworld",
}


def _claim_names(doc: dict) -> list[str]:
    volumes = (_pod_template(doc).get("spec") or {}).get("volumes") or []
    return [v["persistentVolumeClaim"]["claimName"] for v in volumes if "persistentVolumeClaim" in v]


def violations(rendered: str) -> list[str]:
    docs = _documents(rendered)
    found = []
    claims = [(s, d) for s, d in docs if d.get("kind") == "PersistentVolumeClaim"]
    templates = [
        (s, t) for s, d in docs if d.get("kind") == "StatefulSet"
        for t in d["spec"].get("volumeClaimTemplates") or []
    ]
    for source, claim in claims + templates:
        spec = claim.get("spec") or {}
        if spec.get("storageClassName"):
            found.append(f"{_name(source, claim)} names class {spec['storageClassName']!r}")
        if spec.get("accessModes") != ["ReadWriteOnce"]:
            found.append(f"{_name(source, claim)} requests {spec.get('accessModes')}")
    workloads = _workloads(rendered)
    for source, claim in claims:
        name = claim["metadata"]["name"]
        mounting = [_name(s, d) for s, d in workloads if name in _claim_names(d)]
        if len(mounting) != 1:
            found.append(f"claim {name!r} is mounted by {len(mounting)} pod templates: {mounting}")
    for source, doc in workloads:
        replicas = (doc.get("spec") or {}).get("replicas")
        if _claim_names(doc) and replicas is not None and int(replicas) > 1:
            found.append(f"{_name(source, doc)} mounts a claim with {replicas} replicas")
    try:
        post_render.render(rendered, GATE, storage_class="ceph-freepod")
    except post_render.SharedClaim as refused:
        found.append(f"the storage step refuses it: {refused}")
    return found


@pytest.mark.parametrize("chart", [c for c in CHARTS if c not in EXEMPT])
def test_every_chart_meets_the_storage_contract(chart):
    assert not violations(_render(chart, {})), chart


@pytest.mark.parametrize("chart", sorted(EXEMPT))
def test_exemptions_are_still_needed(chart):
    assert chart in CHARTS, f"{chart} is no longer a product chart"
    assert violations(_render(chart, {})), f"{chart} no longer needs its exemption"


def test_the_check_sees_claims():
    rendered = _render("immich", {})
    assert [d for _, d in _documents(rendered) if d.get("kind") == "PersistentVolumeClaim"]


def test_a_second_workload_on_a_claim_is_caught(tmp_path):
    chart = tmp_path / "immich"
    shutil.copytree(PRODUCTS / "immich" / "chart", chart)
    [claim] = [
        d["metadata"]["name"] for _, d in _documents(_render("immich", {}))
        if d.get("kind") == "PersistentVolumeClaim"
    ][:1]
    second = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "intruder"},
        "spec": {
            "strategy": {"type": "Recreate"},
            "selector": {"matchLabels": {"app": "intruder"}},
            "template": {
                "metadata": {"labels": {"app": "intruder"}},
                "spec": {
                    "containers": [{"name": "c", "image": "busybox"}],
                    "volumes": [{"name": "d", "persistentVolumeClaim": {"claimName": claim}}],
                },
            },
        },
    }
    (chart / "templates" / "intruder.yaml").write_text(yaml.safe_dump(second))
    rendered = subprocess.run(
        ["helm", "template", "t", str(chart), "--set-string", f"caelus.ssh.platformPublicKey={PLATFORM_KEY}"],
        capture_output=True, text=True, check=True,
    ).stdout
    found = violations(rendered)
    assert any(claim in v and "2 pod templates" in v for v in found), found
    assert any("storage step refuses" in v for v in found), found
