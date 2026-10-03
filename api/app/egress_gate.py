"""The egress gate: a platform init container that holds every tenant pod until
its NetworkPolicy jail is enforced.

On k3s (flannel + kube-router) a new pod's policy rules are programmed after the
pod already has its IP and its containers are running, so a fresh pod briefly
has unrestricted egress. The gate runs first among the init containers and
probes the kube-apiserver, which the tenant baseline policy denies and which
always listens: while the connect succeeds the jail is not up yet, and the
tenant's containers never start until it fails.

Injected into every rendered pod template as a Helm post-renderer (the
``egress-gate`` plugin under ``api/helm-plugins/``), so it covers every product
chart without any chart's cooperation. Run as ``python -m app.egress_gate``:
reads Helm's rendered manifests on stdin, writes them back on stdout.
"""

from __future__ import annotations

import argparse
import re
import sys
from itertools import takewhile
from typing import Any

import yaml

CONTAINER_NAME = "caelus-egress-gate"
PLUGIN_NAME = "egress-gate"

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


def _pod_spec(doc: dict[str, Any]) -> dict[str, Any] | None:
    if doc.get("kind") == "Pod":
        return doc.get("spec")
    spec = doc.get("spec") or {}
    if "jobTemplate" in spec:  # CronJob
        spec = (spec["jobTemplate"] or {}).get("spec") or {}
    template = spec.get("template")
    if isinstance(template, dict) and isinstance(template.get("spec"), dict):
        return template["spec"]
    return None


def inject(doc: Any, gate: dict[str, Any]) -> bool:
    """Put ``gate`` first among ``doc``'s init containers; whether ``doc`` has a pod."""
    if not isinstance(doc, dict):
        return False
    pod = _pod_spec(doc)
    if pod is None or "containers" not in pod:
        return False
    others = [c for c in pod.get("initContainers") or [] if c.get("name") != CONTAINER_NAME]
    pod["initContainers"] = [gate, *others]
    return True


class _Loader(yaml.SafeLoader):
    """SafeLoader without the YAML 1.1 resolvers Helm's Go parser does not share.

    A rewritten document is re-serialized, so a scalar Go reads as a string
    (an unquoted date, a sexagesimal ``1:30``) must survive as one rather than
    come back as a timestamp or the integer 90.
    """


_Loader.yaml_implicit_resolvers = {
    first: [
        (tag, regexp)
        for tag, regexp in resolvers
        if tag != "tag:yaml.org,2002:timestamp"
        and not (tag in ("tag:yaml.org,2002:int", "tag:yaml.org,2002:float") and ":" in regexp.pattern)
    ]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
for _tag, _pattern in (
    ("tag:yaml.org,2002:int", r"^(?:[-+]?0b[0-1_]+|[-+]?0[0-7_]+|[-+]?(?:0|[1-9][0-9_]*)|[-+]?0x[0-9a-fA-F_]+)$"),
    (
        "tag:yaml.org,2002:float",
        (
            r"^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?|\.[0-9_]+(?:[eE][-+][0-9]+)?"
            r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$"
        ),
    ),
):
    _Loader.add_implicit_resolver(_tag, re.compile(_pattern), list("-+0123456789."))

_SEPARATOR = re.compile(r"^---[ \t]*$", re.MULTILINE)


def render(manifests: str, gate: dict[str, Any]) -> str:
    """``manifests`` with ``gate`` injected into every pod template.

    Documents without a pod pass through byte for byte; only the ones the gate
    is added to are re-serialized, keeping their leading ``# Source:`` comments.
    """
    out: list[str] = []
    for chunk in _SEPARATOR.split(manifests):
        if not chunk.strip():
            continue
        doc = yaml.load(chunk, Loader=_Loader)
        if inject(doc, gate):
            lines = chunk.strip("\n").splitlines()
            head = list(takewhile(lambda line: line.startswith("#"), lines))
            chunk = "\n".join([*head, yaml.safe_dump(doc, sort_keys=False, width=1 << 16)])
        out.append(chunk.strip("\n") + "\n")
    return "".join(f"---\n{c}" for c in out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog=PLUGIN_NAME, description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--deadline-seconds", type=int, required=True)
    args = parser.parse_args(argv)
    gate = gate_container(image=args.image, deadline_seconds=args.deadline_seconds)
    sys.stdout.write(render(sys.stdin.read(), gate))


if __name__ == "__main__":
    main()
