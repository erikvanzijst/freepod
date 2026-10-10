"""The platform's Helm post-renderer (app/post_render.py).

The unit tests drive `render` directly. The chart tests run every product chart
through the real Helm plugin and compare it with a plain render, so a product
added later is held to the post-renderer from its first commit.
"""

from __future__ import annotations

import copy
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from app import egress_gate, post_render
from app.config import get_settings
from app.provisioner import HelmAdapter
from tests.test_chart_release_label_contract import (  # noqa: F401 (autouse fixture)
    CHARTS,
    MINIMUM_VALUES,
    PLATFORM_KEY,
    PRODUCTS,
    _resolved_dependencies,
)

API = Path(__file__).resolve().parents[1]
GATE = egress_gate.gate_container(image="gate:1", deadline_seconds=60)
HOSTNAME = "app.alice.freepod.eu"
HOST = {post_render.HOSTNAME_ANNOTATION: HOSTNAME}


def _deployment() -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "d"},
        "spec": {"template": {"spec": {"containers": [{"name": "app", "image": "app:1"}]}}},
    }


@pytest.mark.parametrize(
    "doc, path",
    [
        (_deployment(), ("spec", "template")),
        ({**_deployment(), "kind": "StatefulSet"}, ("spec", "template")),
        ({**_deployment(), "kind": "Job"}, ("spec", "template")),
        (
            {"kind": "CronJob", "spec": {"jobTemplate": {"spec": _deployment()["spec"]}}},
            ("spec", "jobTemplate", "spec", "template"),
        ),
        ({"kind": "Pod", "metadata": {"name": "p"}, "spec": {"containers": [{"name": "app"}]}}, ()),
    ],
    ids=["Deployment", "StatefulSet", "Job", "CronJob", "Pod"],
)
def test_every_pod_template_gets_the_gate_and_the_hostname(doc, path):
    assert post_render.rewrite(doc, GATE, HOST)
    template = doc
    for key in path:
        template = template[key]
    assert template["spec"]["initContainers"] == [GATE]
    assert template["metadata"]["annotations"] == HOST


def test_the_hostname_keeps_the_charts_annotations_and_overrides_a_forged_one():
    doc = _deployment()
    doc["spec"]["template"]["metadata"] = {
        "labels": {"app": "a"},
        "annotations": {"checksum/config": "abc", post_render.HOSTNAME_ANNOTATION: "forged"},
    }
    post_render.rewrite(doc, GATE, HOST)
    assert doc["spec"]["template"]["metadata"] == {
        "labels": {"app": "a"},
        "annotations": {"checksum/config": "abc", **HOST},
    }
    assert "annotations" not in doc["metadata"]


def test_no_hostname_adds_no_annotation():
    doc = _deployment()
    post_render.rewrite(doc, GATE)
    assert "metadata" not in doc["spec"]["template"]


@pytest.mark.parametrize(
    "doc",
    [
        {"kind": "Service", "spec": {"selector": {"app": "a"}}},
        {"kind": "ConfigMap", "data": {"template": "x"}},
        {"kind": "Deployment", "spec": {"template": {"spec": {}}}},
        None,
        "scalar",
    ],
)
def test_documents_without_a_pod_are_not_touched(doc):
    before = copy.deepcopy(doc)
    assert not post_render.rewrite(doc, GATE, HOST)
    assert doc == before


def test_render_passes_podless_documents_through_byte_for_byte():
    service = "# Source: c/templates/svc.yaml\napiVersion: v1\nkind: Service\nmetadata: {name: s}  # odd\n"
    deployment = "# Source: c/templates/deploy.yaml\n" + yaml.safe_dump(_deployment())
    out = post_render.render(f"---\n{service}---\n{deployment}", GATE, HOST)

    chunks = out.split("---\n")[1:]
    assert chunks[0] == service
    assert chunks[1].startswith("# Source: c/templates/deploy.yaml\n")
    template = yaml.safe_load(chunks[1])["spec"]["template"]
    assert template["spec"]["initContainers"] == [GATE]
    assert template["metadata"]["annotations"] == HOST


def test_render_keeps_strings_go_yaml_reads_as_strings():
    """YAML 1.1 timestamps and sexagesimals would otherwise change type."""
    text = (
        "kind: Deployment\n"
        "spec:\n"
        "  template:\n"
        "    spec:\n"
        "      containers:\n"
        "        - name: app\n"
        "          args: [2026-10-03, 1:30, 0x1F, 1.5, true]\n"
    )
    out = yaml.safe_load(post_render.render(text, GATE))
    args = out["spec"]["template"]["spec"]["containers"][0]["args"]
    assert args == ["2026-10-03", "1:30", 31, 1.5, True]


def _post_renderer_args(**kwargs) -> list[str]:
    calls: list[list[str]] = []

    def runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        stdout = '{"info": {"status": "deployed"}, "version": 1}' if "status" in cmd else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    HelmAdapter(runner=runner).helm_upgrade_install(
        release_name="r", namespace="n", chart_ref="oci://x/c", chart_version="1.0.0",
        chart_digest=None, values={}, timeout=300, atomic=True, wait=True, **kwargs,
    )
    cmd = calls[0]
    assert cmd[cmd.index("--post-renderer") + 1] == post_render.PLUGIN_NAME
    return [cmd[i + 1] for i, part in enumerate(cmd) if part == "--post-renderer-args"]


def test_helm_upgrade_always_post_renders():
    settings = get_settings()
    assert _post_renderer_args() == [
        f"--image={settings.egress_gate_image}",
        f"--deadline-seconds={settings.egress_gate_deadline_seconds}",
    ]


def test_helm_upgrade_passes_the_hostname_to_the_post_renderer():
    assert _post_renderer_args(hostname=HOSTNAME)[-1] == f"--hostname={HOSTNAME}"


def _normalized(doc):
    """Drop what legitimately differs between two renders: random secrets
    (and the checksums of them), and the empty maps and trailing newlines
    Helm 4 may strip from any post-renderer's output."""
    if isinstance(doc, dict):
        if doc.get("kind") == "Secret":
            doc = {k: v for k, v in doc.items() if k not in ("data", "stringData")}
        return {
            k: _normalized(v) for k, v in doc.items()
            if v not in ({}, None) and not k.startswith("checksum/")
        }
    if isinstance(doc, list):
        return [_normalized(v) for v in doc]
    if isinstance(doc, str):
        return doc.rstrip("\n")
    return doc


def _helm_template(chart: str, *extra: str) -> list[dict]:
    args = [
        "helm", "template", "t", str(PRODUCTS / chart / "chart"),
        "--set-string", f"caelus.ssh.platformPublicKey={PLATFORM_KEY}",
        *extra,
    ]
    for key, value in MINIMUM_VALUES.get(chart, {}).items():
        args += ["--set", f"{key}={value}"]
    env = {
        **os.environ,
        "HELM_PLUGINS": str(API / "helm-plugins"),
        "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
    }
    result = subprocess.run(args, capture_output=True, text=True, cwd=API, env=env)
    assert result.returncode == 0, f"{chart}: {result.stderr}"
    return [d for d in yaml.safe_load_all(result.stdout) if d]


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
@pytest.mark.parametrize("chart", CHARTS)
def test_every_product_pod_is_rewritten_and_nothing_else_changes(chart):
    plain = _helm_template(chart)
    rendered = _helm_template(
        chart,
        "--post-renderer", post_render.PLUGIN_NAME,
        "--post-renderer-args", "--image=gate:1",
        "--post-renderer-args", "--deadline-seconds=60",
        "--post-renderer-args", f"--hostname={HOSTNAME}",
    )
    assert len(rendered) == len(plain)

    pods = 0
    for before, after in zip(plain, rendered, strict=True):
        template = post_render.pod_template(after)
        if template is not None:
            pods += 1
            name = f"{chart}: {after['metadata']['name']}"
            pod = template["spec"]
            assert pod["initContainers"][0] == GATE, name
            pod["initContainers"] = pod["initContainers"][1:] or None
            if pod["initContainers"] is None:
                del pod["initContainers"]
            assert template["metadata"]["annotations"].pop(post_render.HOSTNAME_ANNOTATION) == HOSTNAME, name
        assert _normalized(after) == _normalized(before)
    assert pods, f"{chart} rendered no pod"
