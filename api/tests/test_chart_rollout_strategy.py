"""Every product Deployment that mounts a PVC rolls out with `Recreate`.

k3s `local-path` volumes do not enforce ReadWriteOnce between pods on one node,
so any other strategy runs the old and new pod side by side on the same data
for the length of a rollout: two Postgres postmasters on one data directory
(each is PID 1 in its own container, so its lock file cannot tell), two SQLite
writers, two apps rewriting the same files. Nothing fails at the time; the data
is corrupted later. `maxSurge: 0` is not a substitute, since it starts the new
pod while the old one is still terminating. StatefulSets are out of scope: they
replace a pod only once the old one is gone.

Charts are discovered rather than listed, so a new product is held to this from
its first commit.
"""

from __future__ import annotations

import shutil

import pytest

from tests.test_chart_release_label_contract import (  # noqa: F401
    CHARTS,
    _name,
    _pod_template,
    _render,
    _resolved_dependencies,
    _workloads,
)

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


# Charts whose volume holds nothing two pods can corrupt, so a rolling update's
# zero-downtime is worth more than Recreate. Each needs its reason.
ROLLING_UPDATE_ALLOWED = {
    # The PVC holds only index.html, rewritten by an init container on every
    # start and served read-only.
    "helloworld",
}


def _claims(doc: dict) -> list[str]:
    volumes = (_pod_template(doc).get("spec") or {}).get("volumes") or []
    return [v["persistentVolumeClaim"]["claimName"] for v in volumes if "persistentVolumeClaim" in v]


def _deployments_with_claims(chart: str) -> list[tuple[str, dict]]:
    return [
        (s, d) for s, d in _workloads(_render(chart, {}))
        if d["kind"] == "Deployment" and _claims(d)
    ]


def _rolling(chart: str) -> list[str]:
    return [
        f"{_name(s, d)} mounts {_claims(d)} with strategy "
        f"{((d['spec'].get('strategy') or {}).get('type') or 'RollingUpdate (default)')}"
        for s, d in _deployments_with_claims(chart)
        if (d["spec"].get("strategy") or {}).get("type") != "Recreate"
    ]


@pytest.mark.parametrize("chart", [c for c in CHARTS if c not in ROLLING_UPDATE_ALLOWED])
def test_deployments_with_a_volume_claim_use_recreate(chart):
    rolling = _rolling(chart)
    assert not rolling, f"{chart}: two pods would share a volume during a rollout: {rolling}"


@pytest.mark.parametrize("chart", sorted(ROLLING_UPDATE_ALLOWED))
def test_allowed_rolling_updates_are_still_needed(chart):
    """An exemption outlives its reason silently unless something checks it."""
    assert chart in CHARTS, f"{chart} is no longer a product chart"
    assert _rolling(chart), f"{chart} no longer needs its RollingUpdate exemption"


def test_the_check_sees_claims():
    """Otherwise a change in how claims are found would pass every chart above."""
    assert _deployments_with_claims("immich")
