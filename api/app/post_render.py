"""The platform's Helm post-renderer: every tenant release's rendered manifests
pass through it, so it covers every product chart without any chart's
cooperation. Helm takes one post-renderer per release, so every rewrite the
platform makes to a release is a step here.

Each pod template gets:

- the egress gate (``app/egress_gate.py``), first among its init containers;
- the deployment's hostname as the ``caelus.dev/hostname`` annotation, when it
  has one: operator-facing metadata only, which nothing selects on.

With ``--storage-class`` (deployment-storage-class), every PersistentVolumeClaim
and StatefulSet claim template gets that class and ``ReadWriteOncePod``, and a
release that could mount one of its claims from two pods at once is refused.

With ``--render=stopped`` the release runs nothing (deployment-power-reconciliation):
Deployments and StatefulSets go to 0 replicas, Jobs and CronJobs are suspended,
HorizontalPodAutoscalers and bare Pods are dropped, and every Ingress rule for
the deployment's own hostname is pointed at ``<release>-caelus-parking``, an
appended ExternalName Service resolving to the parking page.

Runs as the ``post-render`` plugin under ``api/helm-plugins/`` (``python -m
app.post_render``): reads Helm's rendered manifests on stdin, writes them back
on stdout.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from itertools import takewhile
import copy
from typing import Any

import yaml

from app import egress_gate

PLUGIN_NAME = "post-render"
HOSTNAME_ANNOTATION = "caelus.dev/hostname"
RENDER_NORMAL = "normal"
RENDER_STOPPED = "stopped"
PARKING_SUFFIX = "-caelus-parking"
SINGLE_WRITER = "ReadWriteOnce"
SINGLE_POD = "ReadWriteOncePod"


class SharedClaim(ValueError):
    """A release the storage step refuses (deployment-storage-class D4)."""


@dataclass(frozen=True)
class Stopped:
    """What the stopped render needs to reroute the deployment's hostname."""

    release: str
    hostname: str | None
    parking_host: str
    parking_port: int

    @property
    def service_name(self) -> str:
        return f"{self.release}{PARKING_SUFFIX}"


def parking_service(stopped: Stopped) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": stopped.service_name},
        "spec": {
            "type": "ExternalName",
            "externalName": stopped.parking_host,
            "ports": [{"name": "http", "port": stopped.parking_port, "protocol": "TCP"}],
        },
    }


def _reroute_ingress(doc: dict[str, Any], stopped: Stopped) -> bool:
    if not stopped.hostname:
        return False
    host = stopped.hostname.lower()
    backend = {"service": {"name": stopped.service_name, "port": {"number": stopped.parking_port}}}
    changed = False
    for rule in (doc.get("spec") or {}).get("rules") or []:
        if not isinstance(rule, dict) or str(rule.get("host") or "").lower() != host:
            continue
        for path in (rule.get("http") or {}).get("paths") or []:
            path["backend"] = copy.deepcopy(backend)
            changed = True
    return changed


def stop(doc: Any, stopped: Stopped) -> bool | None:
    """Apply the stopped step to ``doc``: whether it changed, or None to drop it."""
    if not isinstance(doc, dict):
        return False
    kind = doc.get("kind")
    if kind in ("Deployment", "StatefulSet"):
        doc.setdefault("spec", {})["replicas"] = 0
        return True
    if kind in ("Job", "CronJob"):
        doc.setdefault("spec", {})["suspend"] = True
        return True
    if kind in ("HorizontalPodAutoscaler", "Pod"):
        return None
    if kind == "Ingress":
        return _reroute_ingress(doc, stopped)
    return False


def pod_template(doc: Any) -> dict[str, Any] | None:
    """The object holding ``doc``'s pod ``metadata`` and ``spec`` -- the Pod
    itself, or its workload's template -- or None when ``doc`` runs no pod."""
    if not isinstance(doc, dict):
        return None
    if doc.get("kind") == "Pod":
        template = doc
    else:
        spec = doc.get("spec") or {}
        if "jobTemplate" in spec:  # CronJob
            spec = (spec["jobTemplate"] or {}).get("spec") or {}
        template = spec.get("template")
    if isinstance(template, dict) and isinstance(template.get("spec"), dict) and "containers" in template["spec"]:
        return template
    return None


def annotate(template: dict[str, Any], annotations: dict[str, str]) -> None:
    metadata = template.get("metadata") or {}
    metadata["annotations"] = {**(metadata.get("annotations") or {}), **annotations}
    template["metadata"] = metadata


def rewrite(doc: Any, gate: dict[str, Any], annotations: dict[str, str] | None = None) -> bool:
    """Apply every step to ``doc``'s pod template; whether ``doc`` has one."""
    template = pod_template(doc)
    if template is None:
        return False
    egress_gate.inject(template["spec"], gate)
    if annotations:
        annotate(template, annotations)
    return True


def _name(obj: Any) -> str:
    return str(((obj or {}).get("metadata") or {}).get("name") or "<unnamed>")


def _claims(doc: Any) -> list[dict[str, Any]]:
    """The claim objects ``doc`` renders: itself, or its claim templates."""
    if not isinstance(doc, dict):
        return []
    if doc.get("kind") == "PersistentVolumeClaim":
        return [doc]
    if doc.get("kind") == "StatefulSet":
        templates = (doc.get("spec") or {}).get("volumeClaimTemplates") or []
        return [t for t in templates if isinstance(t, dict)]
    return []


def _count(value: Any) -> int:
    return 1 if value is None else int(value)


def _concurrency(doc: dict[str, Any]) -> str | None:
    """Why ``doc`` may run more than one pod at once, or None."""
    kind, spec = doc.get("kind"), doc.get("spec") or {}
    what = f"{kind} {_name(doc)!r}"
    if kind in ("Deployment", "StatefulSet", "ReplicaSet") and _count(spec.get("replicas")) > 1:
        return f"{what}, which has {spec['replicas']} replicas"
    if kind == "Deployment":
        strategy = (spec.get("strategy") or {}).get("type") or "RollingUpdate"
        if strategy != "Recreate":
            return f"{what}, which uses the {strategy} strategy"
    if kind == "DaemonSet":
        return f"{what}, which runs a pod per node"
    if kind == "CronJob":
        policy = spec.get("concurrencyPolicy") or "Allow"
        if policy != "Forbid":
            return f"{what}, whose concurrencyPolicy is {policy}"
        spec = ((spec.get("jobTemplate") or {}).get("spec")) or {}
    if kind in ("Job", "CronJob") and _count(spec.get("parallelism")) > 1:
        return f"{what}, whose parallelism is {spec['parallelism']}"
    return None


def refuse_shared_claims(docs: list[Any]) -> None:
    """Raise ``SharedClaim`` when a claim the release renders could be mounted
    by more than one pod at once. Claims it doesn't render aren't checked."""
    rendered: set[str] = set()
    for doc in docs:
        for claim in _claims(doc):
            modes = (claim.get("spec") or {}).get("accessModes") or []
            if any(mode != SINGLE_WRITER for mode in modes):
                raise SharedClaim(f"claim {_name(claim)!r} requests {', '.join(modes)}, not {SINGLE_WRITER}")
            if doc.get("kind") == "PersistentVolumeClaim":
                rendered.add(_name(claim))
    mounts: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for doc in docs:
        template = pod_template(doc)
        if template is None:
            continue
        for volume in template["spec"].get("volumes") or []:
            name = ((volume or {}).get("persistentVolumeClaim") or {}).get("claimName")
            if name in rendered:
                mounts[name][id(doc)] = doc
    for name, workloads in mounts.items():
        if len(workloads) > 1:
            owners = ", ".join(f"{d.get('kind')} {_name(d)!r}" for d in workloads.values())
            raise SharedClaim(f"claim {name!r} is mounted by more than one pod template: {owners}")
        reason = _concurrency(next(iter(workloads.values())))
        if reason:
            raise SharedClaim(f"claim {name!r} is mounted by {reason}")


def place(doc: Any, storage_class: str) -> bool:
    """Give each of ``doc``'s claims the class and single-pod access; whether it has any."""
    claims = _claims(doc)
    for claim in claims:
        spec = claim.setdefault("spec", {})
        spec["storageClassName"] = storage_class
        spec["accessModes"] = [SINGLE_POD]
    return bool(claims)


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


def _dump(doc: Any) -> str:
    return yaml.safe_dump(doc, sort_keys=False, width=1 << 16)


def render(
    manifests: str,
    gate: dict[str, Any],
    annotations: dict[str, str] | None = None,
    stopped: Stopped | None = None,
    storage_class: str | None = None,
) -> str:
    """``manifests`` with every pod template rewritten, its claims placed on
    ``storage_class`` when given, and stopped when ``stopped`` is given.

    Untouched documents pass through byte for byte; only the rewritten ones
    are re-serialized, keeping their leading ``# Source:`` comments.
    """
    chunks = [chunk for chunk in _SEPARATOR.split(manifests) if chunk.strip()]
    docs = [yaml.load(chunk, Loader=_Loader) for chunk in chunks]
    if storage_class is not None:
        refuse_shared_claims(docs)
    out: list[str] = []
    for chunk, doc in zip(chunks, docs):
        changed = rewrite(doc, gate, annotations)
        if storage_class is not None:
            changed = place(doc, storage_class) or changed
        if stopped is not None:
            stop_changed = stop(doc, stopped)
            if stop_changed is None:
                continue
            changed = changed or stop_changed
        if changed:
            lines = chunk.strip("\n").splitlines()
            head = list(takewhile(lambda line: line.startswith("#"), lines))
            chunk = "\n".join([*head, _dump(doc)])
        out.append(chunk.strip("\n") + "\n")
    if stopped is not None and stopped.hostname:
        out.append(f"# Source: caelus post-render (stopped)\n{_dump(parking_service(stopped))}")
    return "".join(f"---\n{c}" for c in out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog=PLUGIN_NAME, description=__doc__)
    parser.add_argument("--image", required=True, help="the egress gate's image")
    parser.add_argument("--deadline-seconds", type=int, required=True, help="the egress gate's deadline")
    parser.add_argument("--hostname")
    parser.add_argument("--render", choices=(RENDER_NORMAL, RENDER_STOPPED), default=RENDER_NORMAL)
    parser.add_argument("--release", required=True, help="the Helm release name; names the platform's objects")
    parser.add_argument("--parking-host", help="the parking page's FQDN; required with --render=stopped")
    parser.add_argument("--parking-port", type=int, help="the parking page's port; required with --render=stopped")
    parser.add_argument("--storage-class", help="the deployment's StorageClass, applied to every claim")
    args = parser.parse_args(argv)
    stopped = None
    if args.render == RENDER_STOPPED:
        missing = [
            flag for flag, value in (
                ("--parking-host", args.parking_host),
                ("--parking-port", args.parking_port),
            ) if not value
        ]
        if missing:
            parser.error(f"--render=stopped requires {', '.join(missing)}")
        stopped = Stopped(
            release=args.release,
            hostname=args.hostname,
            parking_host=args.parking_host,
            parking_port=args.parking_port,
        )
    gate = egress_gate.gate_container(image=args.image, deadline_seconds=args.deadline_seconds)
    annotations = {HOSTNAME_ANNOTATION: args.hostname} if args.hostname else None
    try:
        rendered = render(sys.stdin.read(), gate, annotations, stopped, args.storage_class)
    except SharedClaim as refused:
        parser.exit(1, f"{PLUGIN_NAME}: refusing to render on storage class {args.storage_class!r}: {refused}\n")
    sys.stdout.write(rendered)


if __name__ == "__main__":
    main()
