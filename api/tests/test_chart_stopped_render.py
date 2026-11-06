"""Every catalog chart, rendered stopped through the real post-renderer plugin,
runs nothing and routes its own hostname to the parking page
(deployment-power-reconciliation)."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from app import post_render
from tests.test_catalog_charts import CATALOG_FILES, PRODUCTS
from tests.test_chart_hook_ban import _render_catalog
from tests.test_chart_release_label_contract import _resolved_dependencies  # noqa: F401

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

API = Path(__file__).resolve().parents[1]
HOSTNAME = "app-alice.freepod.app"
RELEASE = "t"
PARKING = f"{RELEASE}{post_render.PARKING_SUFFIX}"
PARKING_HOST = "caelus-api.caelus.svc.cluster.local"
ENV = {
    **os.environ,
    "HELM_PLUGINS": str(API / "helm-plugins"),
    "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
}


# Charts whose Ingress always runs app authentication, which needs the
# verification URL the reconciler injects.
INGRESS_AUTH = {"appstudio"}


def _host_values(slug: str) -> list[str]:
    """The hostname under every key the chart reads it from, as the reconciler
    would inject it (`caelus.ingress`) or the user value carries it."""
    args = [
        "--set", "caelus.ingress.enabled=true",
        "--set-string", f"caelus.ingress.host={HOSTNAME}",
        "--set", "caelus.ingress.tls.wildcard=true",
    ]
    chart = PRODUCTS / slug / "chart"
    schema_file = chart / "values.schema.json"
    properties = json.loads(schema_file.read_text()).get("properties", {}) if schema_file.exists() else {}
    defaults = yaml.safe_load((chart / "values.yaml").read_text()) or {}
    for key in ("host", "serverName"):
        if key in properties or key in defaults:
            args += ["--set-string", f"{key}={HOSTNAME}"]
    if slug in INGRESS_AUTH:
        args += ["--set-string", "caelus.appAuth.verifyUrl=http://app-auth.test/verify"]
    return args


def _post_render(render: str) -> list[str]:
    return [
        "--post-renderer", post_render.PLUGIN_NAME,
        "--post-renderer-args", "--image=gate:1",
        "--post-renderer-args", "--deadline-seconds=60",
        "--post-renderer-args", f"--hostname={HOSTNAME}",
        "--post-renderer-args", f"--render={render}",
        "--post-renderer-args", f"--release={RELEASE}",
        "--post-renderer-args", f"--parking-host={PARKING_HOST}",
        "--post-renderer-args", "--parking-port=8000",
    ]


def _render(catalog_file, tmp_path, render: str) -> list[dict]:
    slug = yaml.safe_load(catalog_file.read_text())["product"]["slug"]
    docs = _render_catalog(catalog_file, tmp_path, *_host_values(slug), *_post_render(render), env=ENV)
    return [doc for _, doc in docs]


def _own_host_backends(docs: list[dict]) -> list[dict]:
    return [
        path["backend"]
        for doc in docs if doc.get("kind") == "Ingress"
        for rule in doc["spec"].get("rules") or [] if str(rule.get("host", "")).lower() == HOSTNAME
        for path in (rule.get("http") or {}).get("paths") or []
    ]


@pytest.mark.parametrize("catalog_file", CATALOG_FILES, ids=lambda p: p.stem)
def test_a_stopped_catalog_chart_runs_nothing_and_parks_its_host(catalog_file, tmp_path):
    normal = _render(catalog_file, tmp_path, "normal")
    stopped = _render(catalog_file, tmp_path, "stopped")
    name = catalog_file.stem

    workloads = [d for d in stopped if d.get("kind") in ("Deployment", "StatefulSet")]
    assert workloads, f"{name} rendered no workload"
    assert all(d["spec"]["replicas"] == 0 for d in workloads), name
    assert not [d for d in stopped if d.get("kind") in ("HorizontalPodAutoscaler", "Pod")], name

    backends = _own_host_backends(stopped)
    assert backends, f"{name} renders no Ingress rule for its own hostname"
    assert backends == [{"service": {"name": PARKING, "port": {"number": 8000}}}] * len(backends), name

    [parking] = [d for d in stopped if d.get("kind") == "Service" and d["metadata"]["name"] == PARKING]
    assert parking["spec"] == {
        "type": "ExternalName",
        "externalName": PARKING_HOST,
        "ports": [{"name": "http", "port": 8000, "protocol": "TCP"}],
    }

    # The name is reserved: no chart renders it itself.
    assert not [d for d in normal if d.get("kind") == "Service" and d["metadata"]["name"] == PARKING], name


def test_app_studio_preview_keeps_its_backends(tmp_path):
    [catalog_file] = [f for f in CATALOG_FILES if f.stem == "appstudio"]

    def preview(docs):
        return [d for d in docs if d.get("kind") == "Ingress" and d["metadata"]["name"].endswith("-preview")]

    before = preview(_render(catalog_file, tmp_path, "normal"))
    after = preview(_render(catalog_file, tmp_path, "stopped"))
    assert before, "App Studio rendered no preview Ingress"
    assert after == before
