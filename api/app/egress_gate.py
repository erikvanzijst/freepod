"""The egress gate: a platform init container that holds every tenant pod until
its NetworkPolicy jail is enforced.

On k3s (flannel + kube-router) a new pod's policy rules are programmed after the
pod already has its IP and its containers are running, so a fresh pod briefly
has unrestricted egress. The gate runs first among the init containers and
probes the kube-apiserver, which the tenant baseline policy denies and which
always listens: while the connect succeeds the jail is not up yet, and the
tenant's containers never start until it fails.

The platform's Helm post-renderer (``app/post_render.py``) injects it into
every rendered pod template, so it covers every product chart without any
chart's cooperation.
"""

from __future__ import annotations

from typing import Any

CONTAINER_NAME = "caelus-egress-gate"

# KUBERNETES_SERVICE_HOST/PORT are injected by kubelet into every container,
# regardless of enableServiceLinks. Two consecutive refusals rather than
# one, so a single transient failure is not mistaken for the jail.
GATE_SCRIPT = r"""
set -u
target="${KUBERNETES_SERVICE_HOST:?}/${KUBERNETES_SERVICE_PORT:?}"
deadline=$((SECONDS + GATE_DEADLINE_SECONDS))
refused=0
while (( SECONDS < deadline )); do
  if timeout 0.5 bash -c "exec 3<>/dev/tcp/${target}" 2>/dev/null; then
    refused=0
  else
    refused=$((refused + 1))
    if (( refused >= 2 )); then
      echo "egress-gate: ${target/\//:} denied after ${SECONDS}s; egress is jailed"
      exit 0
    fi
  fi
  sleep 0.2
done
echo "egress-gate: ${target/\//:} still reachable after ${GATE_DEADLINE_SECONDS}s;" \
  "the egress NetworkPolicy is not enforced, refusing to start the pod" >&2
exit 1
""".strip()


def gate_container(*, image: str, deadline_seconds: int) -> dict[str, Any]:
    return {
        "name": CONTAINER_NAME,
        "image": image,
        "imagePullPolicy": "IfNotPresent",
        "command": ["bash", "-c", GATE_SCRIPT],
        # A gate that fails says why in the pod's status, not only its log.
        "terminationMessagePolicy": "FallbackToLogsOnError",
        "env": [{"name": "GATE_DEADLINE_SECONDS", "value": str(deadline_seconds)}],
        "resources": {
            "requests": {"cpu": "10m", "memory": "8Mi"},
            "limits": {"memory": "32Mi"},
        },
        # Explicit uid: some products set pod-level runAsNonRoot, and the image's
        # default user is root.
        "securityContext": {
            "runAsNonRoot": True,
            "runAsUser": 65534,
            "runAsGroup": 65534,
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
        },
    }


def inject(pod: dict[str, Any], gate: dict[str, Any]) -> None:
    """Put ``gate`` first among the pod spec ``pod``'s init containers."""
    others = [c for c in pod.get("initContainers") or [] if c.get("name") != CONTAINER_NAME]
    pod["initContainers"] = [gate, *others]
