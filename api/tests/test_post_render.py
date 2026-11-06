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
        "--release=r",
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
        "--post-renderer-args", "--release=r",
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


# ── Stopped render ───────────────────────────────────────────────────────

STOPPED = post_render.Stopped(
    release="r", hostname=HOSTNAME, parking_host="caelus-api.caelus.svc.cluster.local", parking_port=8000
)
PARKING_BACKEND = {"service": {"name": "r-caelus-parking", "port": {"number": 8000}}}


def _stopped(*docs) -> list[dict]:
    manifests = "".join(f"---\n{yaml.safe_dump(d, sort_keys=False)}" for d in docs)
    return [d for d in yaml.safe_load_all(post_render.render(manifests, GATE, HOST, STOPPED)) if d]


def _ingress(*rules, **spec) -> dict:
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": "i",
            "annotations": {"traefik.ingress.kubernetes.io/router.middlewares": "ns-app-auth@kubernetescrd"},
        },
        "spec": {"rules": list(rules), **spec},
    }


def _rule(host: str, *services: str) -> dict:
    return {
        "host": host,
        "http": {
            "paths": [
                {"path": f"/{s}", "pathType": "Prefix", "backend": {"service": {"name": s, "port": {"number": 80}}}}
                for s in services
            ]
        },
    }


@pytest.mark.parametrize("kind", ["Deployment", "StatefulSet"])
def test_stopped_workloads_have_zero_replicas(kind):
    doc = {**_deployment(), "kind": kind}
    doc["spec"]["replicas"] = 3
    out = _stopped(doc)[0]
    assert out["spec"]["replicas"] == 0
    assert out["spec"]["template"]["spec"]["initContainers"][0] == GATE


def test_stopped_sets_replicas_the_chart_left_out():
    assert _stopped(_deployment())[0]["spec"]["replicas"] == 0


@pytest.mark.parametrize(
    "doc",
    [
        {**_deployment(), "kind": "Job"},
        {"kind": "CronJob", "metadata": {"name": "c"}, "spec": {"jobTemplate": {"spec": _deployment()["spec"]}}},
    ],
    ids=["Job", "CronJob"],
)
def test_stopped_jobs_are_suspended(doc):
    assert _stopped(doc)[0]["spec"]["suspend"] is True


@pytest.mark.parametrize(
    "doc",
    [
        {"apiVersion": "autoscaling/v2", "kind": "HorizontalPodAutoscaler", "metadata": {"name": "h"}, "spec": {}},
        {"kind": "Pod", "metadata": {"name": "p"}, "spec": {"containers": [{"name": "app"}]}},
    ],
    ids=["HorizontalPodAutoscaler", "Pod"],
)
def test_stopped_drops_autoscalers_and_bare_pods(doc):
    kinds = [d["kind"] for d in _stopped(doc, {"kind": "ConfigMap", "metadata": {"name": "c"}})]
    assert kinds == ["ConfigMap", "Service"]


def test_stopped_reroutes_every_path_of_the_own_host_only():
    tls = [{"hosts": [HOSTNAME], "secretName": "t"}]
    ingress = _ingress(
        _rule(HOSTNAME.upper(), "web", "api"),
        _rule(f"preview-{HOSTNAME}", "preview"),
        tls=tls,
    )
    out = _stopped(ingress)[0]
    own, other = out["spec"]["rules"]
    assert [p["backend"] for p in own["http"]["paths"]] == [PARKING_BACKEND, PARKING_BACKEND]
    assert [p["path"] for p in own["http"]["paths"]] == ["/web", "/api"]
    assert other == _rule(f"preview-{HOSTNAME}", "preview")
    assert out["spec"]["tls"] == tls
    assert out["metadata"]["annotations"] == ingress["metadata"]["annotations"]


def test_stopped_appends_the_parking_service():
    service = _stopped({"kind": "ConfigMap", "metadata": {"name": "c"}})[-1]
    assert service == {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "r-caelus-parking"},
        "spec": {
            "type": "ExternalName",
            "externalName": "caelus-api.caelus.svc.cluster.local",
            "ports": [{"name": "http", "port": 8000, "protocol": "TCP"}],
        },
    }


def test_stopped_without_a_hostname_reroutes_nothing_and_adds_no_service():
    stopped = post_render.Stopped(release="r", hostname=None, parking_host="p", parking_port=8000)
    ingress = _ingress(_rule(HOSTNAME, "web"))
    manifests = f"---\n{yaml.safe_dump(ingress, sort_keys=False)}"
    out = [d for d in yaml.safe_load_all(post_render.render(manifests, GATE, None, stopped)) if d]
    assert out == [ingress]


def test_stopped_keeps_untouched_documents_byte_for_byte():
    chunk = "# Source: c/templates/cm.yaml\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: c\ndata:\n  when: 2026-10-03\n"
    out = post_render.render(f"---\n{chunk}", GATE, HOST, STOPPED)
    assert out.startswith(f"---\n{chunk}---\n")


def _main(argv: list[str], stdin: str, monkeypatch, capsys) -> str:
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    post_render.main(argv)
    return capsys.readouterr().out


def test_the_default_render_is_the_normal_one(monkeypatch, capsys):
    manifests = "".join(
        f"---\n{yaml.safe_dump(d, sort_keys=False)}"
        for d in (_deployment(), _ingress(_rule(HOSTNAME, "web")), {"kind": "Pod", "metadata": {"name": "p"}, "spec": {"containers": [{"name": "a"}]}})
    )
    base = ["--image=gate:1", "--deadline-seconds=60", "--release=r", f"--hostname={HOSTNAME}"]
    default = _main(base, manifests, monkeypatch, capsys)
    explicit = _main([*base, "--render=normal"], manifests, monkeypatch, capsys)
    assert default == explicit == post_render.render(manifests, GATE, HOST)


def test_every_render_requires_the_release(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        _main(["--image=gate:1", "--deadline-seconds=60"], "", monkeypatch, capsys)
    assert exc.value.code == 2


@pytest.mark.parametrize("missing", ["--parking-host=p", "--parking-port=8000"])
def test_stopped_without_its_flags_is_a_usage_error(missing, monkeypatch, capsys):
    flags = ["--parking-host=p", "--parking-port=8000"]
    flags.remove(missing)
    with pytest.raises(SystemExit) as exc:
        _main(["--image=gate:1", "--deadline-seconds=60", "--release=r", "--render=stopped", *flags], "", monkeypatch, capsys)
    assert exc.value.code == 2


def test_helm_upgrade_passes_the_stopped_render():
    args = _post_renderer_args(
        hostname=HOSTNAME, render="stopped", parking_host="caelus-api.caelus.svc.cluster.local", parking_port=8000
    )
    assert args[-3:] == [
        "--render=stopped",
        "--parking-host=caelus-api.caelus.svc.cluster.local",
        "--parking-port=8000",
    ]


def test_helm_upgrade_passes_the_release_to_every_render():
    assert "--release=r" in _post_renderer_args(hostname=HOSTNAME, render="normal")


def test_helm_upgrade_normal_render_passes_no_stopped_flags():
    assert not [a for a in _post_renderer_args(hostname=HOSTNAME, render="normal") if a.startswith(("--render", "--parking"))]


def test_helm_upgrade_refuses_a_stopped_render_without_a_parking_host():
    from app.services.errors import IntegrityException

    with pytest.raises(IntegrityException):
        _post_renderer_args(hostname=HOSTNAME, render="stopped", parking_host="")
