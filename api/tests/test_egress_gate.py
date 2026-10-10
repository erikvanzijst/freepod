"""The egress gate init container (app/egress_gate.py).

That every product chart's pods get it is tested through the post-renderer, in
test_post_render.py.
"""

from __future__ import annotations

from app import egress_gate

GATE = egress_gate.gate_container(image="gate:1", deadline_seconds=60)


def _init_names(pod: dict) -> list[str]:
    return [c["name"] for c in pod.get("initContainers") or []]


def test_a_pod_without_init_containers_gets_the_gate():
    pod = {"containers": [{"name": "app"}]}
    egress_gate.inject(pod, GATE)
    assert pod["initContainers"] == [GATE]


def test_the_gate_runs_before_the_charts_own_init_containers():
    pod = {"containers": [{"name": "app"}], "initContainers": [{"name": "migrate", "image": "app:1"}]}
    egress_gate.inject(pod, GATE)
    assert _init_names(pod) == [egress_gate.CONTAINER_NAME, "migrate"]


def test_a_chart_cannot_supply_its_own_gate():
    impostor = {"name": egress_gate.CONTAINER_NAME, "image": "evil:1", "command": ["true"]}
    pod = {"containers": [{"name": "app"}], "initContainers": [{"name": "migrate"}, impostor]}
    egress_gate.inject(pod, GATE)
    assert pod["initContainers"] == [GATE, {"name": "migrate"}]


def test_the_gate_satisfies_pod_security_baseline_and_nonroot_pods():
    sc = GATE["securityContext"]
    assert sc["runAsNonRoot"] is True and sc["runAsUser"] != 0
    assert sc["allowPrivilegeEscalation"] is False
    assert "privileged" not in sc
