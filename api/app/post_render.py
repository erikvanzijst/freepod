"""The platform's Helm post-renderer: every tenant release's rendered manifests
pass through it, so it covers every product chart without any chart's
cooperation. Helm takes one post-renderer per release, so every rewrite the
platform makes to a release is a step here.

Each pod template gets:

- the egress gate (``app/egress_gate.py``), first among its init containers;
- the deployment's hostname as the ``caelus.dev/hostname`` annotation, when it
  has one: operator-facing metadata only, which nothing selects on.

Runs as the ``post-render`` plugin under ``api/helm-plugins/`` (``python -m
app.post_render``): reads Helm's rendered manifests on stdin, writes them back
on stdout.
"""

from __future__ import annotations

import argparse
import re
import sys
from itertools import takewhile
from typing import Any

import yaml

from app import egress_gate

PLUGIN_NAME = "post-render"
HOSTNAME_ANNOTATION = "caelus.dev/hostname"


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


def render(manifests: str, gate: dict[str, Any], annotations: dict[str, str] | None = None) -> str:
    """``manifests`` with every pod template rewritten.

    Documents without a pod pass through byte for byte; only the rewritten ones
    are re-serialized, keeping their leading ``# Source:`` comments.
    """
    out: list[str] = []
    for chunk in _SEPARATOR.split(manifests):
        if not chunk.strip():
            continue
        doc = yaml.load(chunk, Loader=_Loader)
        if rewrite(doc, gate, annotations):
            lines = chunk.strip("\n").splitlines()
            head = list(takewhile(lambda line: line.startswith("#"), lines))
            chunk = "\n".join([*head, yaml.safe_dump(doc, sort_keys=False, width=1 << 16)])
        out.append(chunk.strip("\n") + "\n")
    return "".join(f"---\n{c}" for c in out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog=PLUGIN_NAME, description=__doc__)
    parser.add_argument("--image", required=True, help="the egress gate's image")
    parser.add_argument("--deadline-seconds", type=int, required=True, help="the egress gate's deadline")
    parser.add_argument("--hostname")
    args = parser.parse_args(argv)
    gate = egress_gate.gate_container(image=args.image, deadline_seconds=args.deadline_seconds)
    annotations = {HOSTNAME_ANNOTATION: args.hostname} if args.hostname else None
    sys.stdout.write(render(sys.stdin.read(), gate, annotations))


if __name__ == "__main__":
    main()
