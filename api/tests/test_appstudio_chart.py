"""Render the `appstudio` chart and assert its access (app-studio-access): the
owner and the people they list.

Shells out to a real `helm template`. Skipped when helm is unavailable; CI runs
inside the dev container, which has it.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "products" / "appstudio" / "chart"
APP_AUTH_GO = ROOT / "daemons" / "app-auth" / "request.go"
VERIFY_URL = "http://app-auth.login.svc.cluster.local:8080/verify"
OWNER = "Alice@Example.test"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


@pytest.fixture(scope="module", autouse=True)
def _resolved_dependencies():
    """`charts/` is a build artifact; `build` vendors what `Chart.lock` names."""
    result = subprocess.run(["helm", "dependency", "build", str(CHART)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

# What the template's system values and the reconciler give every deployment.
BASE = {
    "auth.enabled": "true",
    "auth.access": "listed",
    "caelus.owner.email": OWNER,
    "caelus.owner.id": "1",
    "caelus.appAuth.verifyUrl": VERIFY_URL,
    "caelus.plan.storageSize": "10Gi",
    "caelus.ingress.enabled": "true",
    "caelus.ingress.host": "studio.alice.freepod.test",
    "caelus.ingress.tls.wildcard": "true",
    "caelus.ssh.platformPublicKey": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIV5/SURDe/M7JtAheJuxURSGgpFB8Yfrd/LY6c9+DzR platform",
}


def _helm(values: dict[str, str]) -> subprocess.CompletedProcess:
    args = ["helm", "template", "t", str(CHART), "--namespace", "tenant-ns"]
    for key, value in values.items():
        args += ["--set", f"{key}={value}"]
    return subprocess.run(args, capture_output=True, text=True)


def _render(**overrides: str) -> list[dict]:
    result = _helm({**BASE, **overrides})
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _middleware(docs: list[dict], suffix: str) -> dict:
    return next(d for d in docs if d["kind"] == "Middleware" and d["metadata"]["name"] == f"t-{suffix}")


def _identity_headers_in_go() -> list[str]:
    block = re.search(r"var identityHeaders = \[\]string\{(.*?)\}", APP_AUTH_GO.read_text(), re.S)
    assert block, "identityHeaders not found in daemons/app-auth/request.go"
    return re.findall(r'"([^"]+)"', block.group(1))


def _verifier_query(docs: list[dict]) -> tuple[str, dict[str, str]]:
    from urllib.parse import parse_qs, urlsplit

    address = _middleware(docs, "app-auth")["spec"]["forwardAuth"]["address"]
    parts = urlsplit(address)
    return address.split("?")[0], {k: v[0] for k, v in parse_qs(parts.query).items()}


def test_every_route_passes_the_verifier_first():
    docs = _render()
    ingresses = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Ingress"}
    assert set(ingresses) == {"t-ingress", "t-preview"}
    for name, ingress in ingresses.items():
        chain = ingress["metadata"]["annotations"]["traefik.ingress.kubernetes.io/router.middlewares"].split(",")
        assert chain[:2] == [
            "tenant-ns-t-strip-identity@kubernetescrd",
            "tenant-ns-t-app-auth@kubernetescrd",
        ], name
    assert [r["host"] for r in ingresses["t-preview"]["spec"]["rules"]] == ["preview-studio.alice.freepod.test"]


def test_the_access_list_applies_and_names_no_account():
    docs = _render()
    base, query = _verifier_query(docs)
    assert base == VERIFY_URL
    assert query == {"l": "1", "n": "App Studio"}
    assert OWNER not in _middleware(docs, "app-auth")["spec"]["forwardAuth"]["address"]


def test_verifier_sets_exactly_the_identity_headers():
    docs = _render()
    fwd = _middleware(docs, "app-auth")["spec"]["forwardAuth"]
    assert fwd["authResponseHeaders"] == ["Cookie", *_identity_headers_in_go()]
    # Unset, so X-Forwarded-Host is the real Host the session is bound to.
    assert "trustForwardHeader" not in fwd
    strip = _middleware(docs, "strip-identity")
    assert strip["spec"]["headers"]["customRequestHeaders"] == {h: "" for h in _identity_headers_in_go()}


def test_the_studio_ingress_sends_opencodes_password_after_sign_in():
    docs = _render()
    secret = next(d for d in docs if d["kind"] == "Secret" and d["metadata"]["name"] == "t-opencode")
    password = base64.b64decode(secret["data"]["password"]).decode()
    assert len(password) >= 32
    header = _middleware(docs, "opencode-auth")["spec"]["headers"]["customRequestHeaders"]["Authorization"]
    assert header == "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()

    pod = next(d for d in docs if d["kind"] == "StatefulSet")["spec"]["template"]["spec"]
    env = {e["name"]: e for e in next(c for c in pod["containers"] if c["name"] == "opencode")["env"]}
    assert env["OPENCODE_SERVER_PASSWORD"]["valueFrom"] == {"secretKeyRef": {"name": "t-opencode", "key": "password"}}

    ingresses = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Ingress"}
    chain = lambda name: ingresses[name]["metadata"]["annotations"]["traefik.ingress.kubernetes.io/router.middlewares"].split(",")
    studio = chain("t-ingress")
    assert studio.index("tenant-ns-t-opencode-auth@kubernetescrd") > studio.index("tenant-ns-t-app-auth@kubernetescrd")
    assert "tenant-ns-t-opencode-auth@kubernetescrd" not in chain("t-preview")


def test_the_chrome_replaces_opencodes_service_worker():
    """opencode's worker answers every navigation with opencode's page, the
    chrome's included, so the studio serves its own at the same path."""
    docs = _render()
    ingress = next(d for d in docs if d["kind"] == "Ingress" and d["metadata"]["name"] == "t-ingress")
    paths = {p["path"]: p for p in ingress["spec"]["rules"][0]["http"]["paths"]}
    # Traefik ranks by rule length: Path(`/sw.js`) would lose to PathPrefix(`/`).
    assert paths["/sw.js"]["pathType"] == "Prefix"
    assert paths["/sw.js"]["backend"]["service"]["port"] == {"name": "chrome"}
    chrome = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "t-chrome")["data"]
    assert "location = /sw.js {" in chrome["nginx.conf"]
    assert "skipWaiting" in chrome["sw.js"] and "fetch" not in chrome["sw.js"]
    pod = next(d for d in docs if d["kind"] == "StatefulSet")["spec"]["template"]["spec"]
    pages = next(v for v in pod["volumes"] if v["name"] == "chrome-pages")["configMap"]["items"]
    assert {"key": "sw.js", "path": "sw.js"} in pages


def test_the_preview_probe_never_forwards_opencodes_password():
    conf = next(d for d in _render() if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "t-chrome")["data"]["nginx.conf"]
    probe = conf.split("location = /.appstudio/probe {", 1)[1].split("}", 1)[0]
    assert 'proxy_set_header Authorization "";' in probe


def _chrome_page(docs: list[dict]) -> str:
    return next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "t-chrome")["data"]["index.html"]


def _chrome_config(page: str) -> dict:
    found = re.search(r'<script id="config" type="application/json">(.*?)</script>', page, re.S)
    assert found, "the chrome page carries no #config"
    return json.loads(found.group(1))


def test_root_opens_the_chrome_with_settings_from_the_chart():
    """The page takes nothing from its URL, which anyone can craft for the owner
    to open: the chart renders the settings into it."""
    docs = _render(platformUrl="https://dev.freepod.test")
    assert _middleware(docs, "open-project")["spec"]["redirectRegex"]["replacement"] == "${1}/.appstudio/"
    assert _chrome_config(_chrome_page(docs)) == {
        "apps": "/workspace/apps",
        "firstApp": "/workspace/apps/app",
        "platform": "https://dev.freepod.test",
        "preview": "https://preview-studio.alice.freepod.test",
    }


def test_a_setting_cannot_close_the_config_element():
    hostile = "https://x.test/</script><script>alert(1)</script>"
    page = _chrome_page(_render(platformUrl=hostile))
    assert page.count("</script>") == 2  # the config element's and the script's own
    assert _chrome_config(page)["platform"] == hostile


def test_chrome_serves_on_its_port_and_probes_the_preview_port():
    docs = _render(chromePort="4199", **{"preview.port": "8181"})
    conf = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "t-chrome")["data"]["nginx.conf"]
    assert "listen 4199;" in conf
    assert "proxy_pass http://127.0.0.1:8181/;" in conf
    pod = next(d for d in docs if d["kind"] == "StatefulSet")["spec"]["template"]["spec"]
    chrome = next(c for c in pod["containers"] if c["name"] == "chrome")
    assert chrome["ports"] == [{"name": "chrome", "containerPort": 4199}]


def test_a_changed_nginx_config_rolls_the_pod():
    """nginx reads its config once, through a subPath mount that is never
    refreshed, so the pod template carries a checksum of it."""
    def checksum(**overrides: str) -> str:
        pod = next(d for d in _render(**overrides) if d["kind"] == "StatefulSet")["spec"]["template"]
        return pod["metadata"]["annotations"]["checksum/chrome-nginx"]

    assert checksum() != checksum(chromePort="4199")


def test_the_agent_caps_its_ephemeral_storage_without_reserving_it():
    pod = next(d for d in _render() if d["kind"] == "StatefulSet")["spec"]["template"]["spec"]
    resources = next(c for c in pod["containers"] if c["name"] == "opencode")["resources"]
    assert resources["limits"]["ephemeral-storage"] == "5Gi"
    assert resources["requests"]["ephemeral-storage"] == "0"


def test_sftp_reaches_only_the_apps_read_only():
    pod = next(d for d in _render() if d["kind"] == "StatefulSet")["spec"]["template"]["spec"]
    sidecar = next(c for c in pod["containers"] if c["name"] == "ssh")
    assert sidecar["volumeMounts"] == [
        {"name": "workspace", "mountPath": "/srv/session/apps", "subPath": "apps", "readOnly": True}
    ]


def test_the_studio_knows_where_the_apps_are():
    docs = _render(appsDir="/workspace/projects/")
    pod = next(d for d in docs if d["kind"] == "StatefulSet")["spec"]["template"]["spec"]
    env = {e["name"]: e.get("value") for e in next(c for c in pod["containers"] if c["name"] == "opencode")["env"]}
    assert env["APPSTUDIO_APPS_DIR"] == "/workspace/projects"
    config = _chrome_config(_chrome_page(docs))
    assert (config["apps"], config["firstApp"]) == ("/workspace/projects", "/workspace/projects/app")


@pytest.mark.parametrize("apps_dir", ["/workspace", "/opt/apps", "/workspace/../etc"])
def test_refuses_apps_outside_the_workspace(apps_dir):
    result = _helm({**BASE, "appsDir": apps_dir})
    assert result.returncode != 0
    assert "must be a directory inside /workspace" in result.stderr


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"auth.enabled": "false"}, "auth.enabled must be true"),
        ({"auth.enabled": "null"}, "auth.enabled must be true"),
        ({"auth.access": "anyone"}, "auth.access listed"),
        ({"auth.access": "null"}, "auth.access listed"),
        ({"auth.protocol": "oidc"}, "header authentication"),
        ({"caelus.appAuth.verifyUrl": ""}, "caelus.appAuth.verifyUrl"),
    ],
)
def test_refuses_to_render_without_listed_sign_in(overrides, message):
    result = _helm({**BASE, **overrides})
    assert result.returncode != 0
    assert message in result.stderr


def test_only_this_origin_may_frame_the_studio():
    docs = _render()
    assert _middleware(docs, "frame-self")["spec"]["headers"] == {"customFrameOptionsValue": "SAMEORIGIN"}
    ingresses = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Ingress"}
    chain = lambda name: ingresses[name]["metadata"]["annotations"]["traefik.ingress.kubernetes.io/router.middlewares"].split(",")
    assert "tenant-ns-t-frame-self@kubernetescrd" in chain("t-ingress")
    assert "tenant-ns-t-frame-self@kubernetescrd" not in chain("t-preview")


def test_user_values_cannot_widen_access():
    from app.services.errors import CaelusException
    from app.services.template_values import validate_user_values

    catalog = ROOT / "products" / "catalog" / "appstudio" / "appstudio.yaml"
    template = yaml.safe_load(catalog.read_text())["template"]
    assert template["system_values"]["auth"] == {"enabled": True, "access": "listed"}
    with pytest.raises(CaelusException):
        validate_user_values({"hostname": "studio-alice.freepod.app", "auth": {"access": "anyone"}}, template["values_schema"])
