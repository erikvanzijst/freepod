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


# ── Storage class (deployment-storage-class) ──────────────────────────────

CLASS = "ceph-freepod"


def _pvc(name: str = "data", **spec) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {"name": name},
        "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "1Gi"}}, **spec},
    }


def _mounting(kind: str = "Deployment", claim: str = "data", name: str = "app", **spec) -> dict:
    doc = {
        "apiVersion": "apps/v1",
        "kind": kind,
        "metadata": {"name": name},
        "spec": {
            "template": {
                "spec": {
                    "containers": [{"name": "app", "image": "app:1"}],
                    "volumes": [{"name": "d", "persistentVolumeClaim": {"claimName": claim}}],
                }
            },
            **spec,
        },
    }
    if kind == "Deployment" and "strategy" not in spec:
        doc["spec"]["strategy"] = {"type": "Recreate"}
    if kind == "CronJob":
        doc["spec"] = {"concurrencyPolicy": "Forbid", "jobTemplate": {"spec": {"template": doc["spec"]["template"]}}, **spec}
    return doc


def _database(**template_spec) -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {"name": "db"},
        "spec": {
            "replicas": 1,
            "template": {"spec": {"containers": [{"name": "pg", "image": "postgres:17"}]}},
            "volumeClaimTemplates": [
                {"metadata": {"name": "pgdata"}, "spec": {"accessModes": ["ReadWriteOnce"], **template_spec}}
            ],
        },
    }


def _placed(*docs, **kwargs) -> list[dict]:
    text = "".join(f"---\n{yaml.safe_dump(d, sort_keys=False)}" for d in docs)
    return list(yaml.safe_load_all(post_render.render(text, GATE, storage_class=CLASS, **kwargs)))


def test_a_standalone_claim_and_a_claim_template_are_placed():
    pvc, _, database = _placed(_pvc(), _mounting(), _database())
    assert pvc["spec"]["storageClassName"] == CLASS
    assert pvc["spec"]["accessModes"] == ["ReadWriteOncePod"]
    [template] = database["spec"]["volumeClaimTemplates"]
    assert template["spec"]["storageClassName"] == CLASS
    assert template["spec"]["accessModes"] == ["ReadWriteOncePod"]


def test_a_charts_own_class_is_overridden():
    [pvc] = _placed(_pvc(storageClassName="local-path"))
    assert pvc["spec"]["storageClassName"] == CLASS


def test_documents_without_claims_pass_through_byte_for_byte():
    chunk = "# Source: c/templates/cm.yaml\napiVersion: v1\nkind: ConfigMap\nmetadata: {name: c}  # odd\n"
    out = post_render.render(f"---\n{chunk}", GATE, storage_class=CLASS)
    assert out == f"---\n{chunk}"


@pytest.mark.parametrize(
    "docs, named",
    [
        ([_pvc(), _mounting(), _mounting("CronJob", name="backup")], "data"),
        ([_pvc(), _mounting(replicas=2)], "data"),
        ([_pvc(), _mounting(strategy={"type": "RollingUpdate"})], "data"),
        ([_pvc(), _mounting(strategy=None)], "data"),
        ([_pvc(), _mounting("StatefulSet", replicas=2)], "data"),
        ([_pvc(accessModes=["ReadWriteMany"])], "data"),
        ([_database(accessModes=["ReadWriteOnce", "ReadOnlyMany"])], "pgdata"),
    ],
    ids=["two-pod-templates", "replicas", "rolling", "default-strategy", "statefulset-by-name", "rwx", "template-mode"],
)
def test_a_release_that_could_share_a_claim_is_refused(docs, named):
    with pytest.raises(post_render.SharedClaim, match=repr(named)):
        _placed(*docs)


def test_a_claim_the_release_does_not_render_is_neither_checked_nor_rewritten():
    [first, second] = _placed(_mounting(claim="existing", replicas=3), _mounting(claim="existing", name="other"))
    assert first["spec"]["replicas"] == 3
    assert second["spec"]["template"]["spec"]["volumes"][0]["persistentVolumeClaim"] == {"claimName": "existing"}


def test_the_plugin_exits_non_zero_naming_the_claim(monkeypatch, capsys):
    manifests = "".join(f"---\n{yaml.safe_dump(d)}" for d in (_pvc(), _mounting(replicas=2)))
    with pytest.raises(SystemExit) as exc:
        _main(["--image=gate:1", "--deadline-seconds=60", "--release=r", f"--storage-class={CLASS}"], manifests, monkeypatch, capsys)
    assert exc.value.code == 1
    assert "'data'" in capsys.readouterr().err


def test_without_a_class_claims_and_templates_render_unchanged():
    docs = (_pvc(), _mounting(), _database())
    text = "".join(f"---\n{yaml.safe_dump(d, sort_keys=False)}" for d in docs)
    out = list(yaml.safe_load_all(post_render.render(text, GATE)))
    assert out[0] == _pvc()
    assert out[2]["spec"]["volumeClaimTemplates"] == _database()["spec"]["volumeClaimTemplates"]


def test_a_stopped_render_keeps_the_class():
    pvc, _, database, _parking = _placed(_pvc(), _mounting(), _database(), stopped=STOPPED)
    assert pvc["spec"]["storageClassName"] == CLASS
    assert database["spec"]["replicas"] == 0
    assert database["spec"]["volumeClaimTemplates"][0]["spec"]["accessModes"] == ["ReadWriteOncePod"]


def test_helm_upgrade_passes_the_storage_class_only_when_set():
    assert f"--storage-class={CLASS}" in _post_renderer_args(storage_class=CLASS)
    assert not [a for a in _post_renderer_args() if a.startswith("--storage-class")]
    stopped = _post_renderer_args(storage_class=CLASS, render="stopped", parking_host="p")
    assert f"--storage-class={CLASS}" in stopped and "--render=stopped" in stopped
