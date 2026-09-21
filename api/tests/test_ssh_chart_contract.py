"""What a product chart declares to get SSH access, and what it renders for it.

One sidecar serves every deployment, and a product declares exactly one thing:
its **session root**. `volume:/<path>` roots the session at a read-only mount of
the data the product exposes; `app-container` roots it at the filesystem the
tenant's own code runs in. Everything else follows.

Two properties are load-bearing and neither has a runtime symptom when wrong:

* **No product acquires SSH access by omission.** The value that grants a shell
  is the one an author has to write deliberately, and the safe outcome -- no
  sidecar, no Service, not routable at the edge -- is the one reached by writing
  nothing. The classification below is exhaustive over `products/*/chart`, so a
  product added without one fails rather than getting whatever its chart happens
  to render.
* **A curated deployment stays reachable while its application is broken.** Its
  pod is `NotReady` when the app container crash-loops, and a Service excludes
  `NotReady` pods from its endpoints -- so the sidecar beside that container,
  running perfectly well, would become unreachable at exactly the moment the
  tenant most wants their files. The fix is one field on one Service and its
  loss is silent until an app crash-loops, which is when nobody is looking.

Its companion is the sidecar's liveness probe. With readiness no longer gating
routing, nothing else stops connections being routed to a wedged `sshd`, so the
probe is load-bearing rather than decorative -- and it must stay a bare TCP
check that touches neither the app container, the mounted data, nor any
credential.

Every consumer is asserted rather than one, because the library chart ships as
nine independently versioned artifacts: a product that falls behind on the
vendored library is the realistic way this regresses.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parents[2]
PRODUCTS = REPO / "products"
SSH_PORT = 2222
SESSION_JAIL = "/srv/session"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

# The platform's public key, injected per environment by the reconciler.
PLATFORM_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIV5/SURDe/M7JtAheJuxURSGgpFB8Yfrd/LY6c9+DzR platform"

# Values a real deployment always has and a bare `helm template` does not.
# Unrelated to SSH.
EXTRA_VALUES: dict[str, dict[str, str]] = {
    "mattermost": {"caelus.plan.storageSize": "1Gi"},
    "vaultwarden": {"host": "v.example.test", "caelus.owner.email": "owner@example.test"},
    "custom": {"hostname": "app.example.test", "caelus.owner.id": "1"},
}

# **Every product in the catalog, classified.** The value is the session root
# the chart must render, or None for a product that renders no SSH resource at
# all -- which is what a product with nothing to expose and no tenant code to
# reach gets, and it gets it by declaring nothing.
#
# A stateless curated product belongs in the None bucket even once it grows a
# volume: owning one is not a declaration, and the presence of a volume must
# never be what opts a product into a session.
SESSION_ROOTS: dict[str, str | None] = {
    "bookstack": "volume:/uploads",
    "custom": "app-container",
    "helloworld": "volume:/data",
    "immich": "volume:/library",
    "lemmy": "volume:/media",
    "matrix": None,
    "mattermost": "volume:/data",
    "naas": None,
    "nextcloud": "volume:/data",
    "photoprism": "volume:/originals",
    "vaultwarden": "volume:/data",
}

# Products that stamp `caelus.dev/release-id` on a pod template for reasons of
# their own -- `custom` keys its log stream on it. That is independent of SSH
# access and carries its own accepted cost: a redeploy cycles the pod.
CHARTS_RENDERING_THEIR_OWN_RELEASE_LABEL = frozenset({"custom"})

VOLUME_ROOTED = sorted(k for k, v in SESSION_ROOTS.items() if v and v != "app-container")
WITH_SSH = sorted(k for k, v in SESSION_ROOTS.items() if v)
WITHOUT_SSH = sorted(k for k, v in SESSION_ROOTS.items() if v is None)


def _charts() -> list[str]:
    """Every product chart in the repository, found rather than listed."""
    return sorted(
        d.name for d in PRODUCTS.iterdir()
        if (d / "chart" / "Chart.yaml").is_file() and not d.name.startswith("_")
    )


@pytest.fixture(scope="module", autouse=True)
def _resolved_dependencies():
    """Vendor each chart's `ssh-sidecar` dependency before anything renders.

    `charts/` is a build artifact -- `products/.gitignore` ignores `**/*.tgz`,
    so a clean checkout has none and `helm template` refuses the chart. `build`
    rather than `update`, so the tracked `Chart.lock` decides what is vendored
    and is not rewritten; that lock is what pins the library version this file
    is really asserting about.
    """
    for chart in _charts():
        chart_dir = PRODUCTS / chart / "chart"
        if not (chart_dir / "Chart.yaml").read_text().count("dependencies:"):
            continue
        result = subprocess.run(
            ["helm", "dependency", "build", str(chart_dir)], capture_output=True, text=True
        )
        assert result.returncode == 0, f"{chart}: {result.stderr}"


# What the reconciler projects for every product, with no per-product condition.
RELEASE_ID = "8d1c0b2e-0000-4000-8000-000000000001"
RELEASE_NUMBER = "7"


def _render(chart: str, *, platform_key: str | None = PLATFORM_KEY) -> list[dict]:
    args = ["helm", "template", "t", str(PRODUCTS / chart / "chart")]
    if platform_key is not None:
        args += ["--set-string", f"caelus.ssh.platformPublicKey={platform_key}"]
    args += ["--set-string", f"caelus.releaseId={RELEASE_ID}"]
    args += ["--set-string", f"caelus.releaseNumber={RELEASE_NUMBER}"]
    for key, value in EXTRA_VALUES.get(chart, {}).items():
        args += ["--set", f"{key}={value}"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, f"{chart}: {result.stderr}"
    return [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]


def _containers(docs: list[dict]) -> list[dict]:
    """Every container in every workload pod template, in document order."""
    out = []
    for doc in docs:
        if doc.get("kind") not in {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}:
            continue
        spec = doc.get("spec") or {}
        template = (
            (spec.get("jobTemplate") or {}).get("spec", {}).get("template")
            if doc["kind"] == "CronJob"
            else spec.get("template")
        ) or {}
        pod = template.get("spec") or {}
        out += (pod.get("containers") or []) + (pod.get("initContainers") or [])
    return out


def _sidecar(docs: list[dict]) -> dict:
    sidecars = [c for c in _containers(docs) if c.get("name") == "ssh"]
    assert len(sidecars) == 1, f"expected exactly one sidecar container, got {len(sidecars)}"
    return sidecars[0]


def _ssh_service(docs: list[dict]) -> dict:
    services = [
        doc
        for doc in docs
        if doc.get("kind") == "Service"
        and any(p.get("port") == SSH_PORT for p in (doc.get("spec") or {}).get("ports") or [])
    ]
    assert len(services) == 1, f"expected exactly one SSH Service, got {len(services)}"
    return services[0]


def _env(container: dict) -> dict[str, dict]:
    return {e["name"]: e for e in container.get("env") or []}


def _ssh_objects(docs: list[dict], kinds: set[str]) -> list[dict]:
    return [
        doc
        for doc in docs
        if doc.get("kind") in kinds
        and (doc.get("metadata", {}).get("labels") or {}).get("caelus.dev/component") == "ssh"
    ]


# --- the classification is exhaustive --------------------------------------

def test_every_product_chart_is_classified():
    """A product added without a classification fails here rather than being
    granted whatever its chart happens to render."""
    assert set(_charts()) == set(SESSION_ROOTS), (
        "a product chart was added or removed without stating what its SSH "
        "access is. The value that grants a shell in the tenant's own container "
        f"has to be written deliberately: {set(_charts()) ^ set(SESSION_ROOTS)}"
    )


@pytest.mark.parametrize("chart", WITH_SSH)
def test_the_rendered_session_root_is_the_one_pinned_for_the_product(chart):
    env = _env(_sidecar(_render(chart)))
    assert "FREEPOD_SESSION_ROOT" in env, f"{chart}: the sidecar is given no session root"
    assert env["FREEPOD_SESSION_ROOT"]["value"] == SESSION_ROOTS[chart]


@pytest.mark.parametrize("chart", WITHOUT_SSH)
def test_a_product_declaring_nothing_renders_no_ssh_resource(chart):
    """Not routable at the edge, which derives a deployment's upstream from a
    Service name that does not exist. That is the outcome for a product with
    nothing to expose, and it is reached by declaring nothing."""
    docs = _render(chart)
    assert [c for c in _containers(docs) if c.get("name") == "ssh"] == []
    assert _ssh_objects(docs, {"Secret", "ConfigMap", "Service"}) == []
    for doc in docs:
        if doc.get("kind") != "Service":
            continue
        ports = [p.get("port") for p in (doc.get("spec") or {}).get("ports") or []]
        assert SSH_PORT not in ports, f"{chart}: renders a Service on the SSH port"
        assert not doc["metadata"]["name"].endswith("-ssh"), f"{chart}: renders an -ssh Service"


# --- one server, and it is the platform's ----------------------------------

@pytest.mark.parametrize("chart", sorted(SESSION_ROOTS))
def test_no_chart_renders_a_third_party_ssh_server(chart):
    """`atmoz/sftp` is gone, and it is gone from the rendered manifest rather
    than merely from the chart source."""
    rendered = yaml.safe_dump_all(_render(chart))
    assert "atmoz" not in rendered, f"{chart} still renders an atmoz/sftp container"

    servers = [c for c in _containers(_render(chart)) if c.get("name") in {"ssh", "sftp"}]
    assert len(servers) <= 1, f"{chart} renders {len(servers)} SSH servers in one pod"


@pytest.mark.parametrize("chart", sorted(SESSION_ROOTS))
def test_the_tenant_namespace_holds_no_credential_for_this_feature(chart):
    """The sidecar takes every input as an environment variable and writes its
    own `authorized_keys`, `sshd_config` and host key at startup, so a Secret or
    ConfigMap here would be an object nothing reads -- and the keys that
    authenticate a person are resolved at the edge and never reach a tenant."""
    docs = _render(chart)
    owned = _ssh_objects(docs, {"Secret", "ConfigMap"})
    assert owned == [], (
        f"{chart} renders {[d['kind'] + '/' + d['metadata']['name'] for d in owned]}, "
        "which nothing reads"
    )
    rendered = yaml.safe_dump_all(docs)
    assert "PRIVATE KEY" not in rendered, f"{chart}: private key material in the release"


@pytest.mark.parametrize("chart", WITH_SSH)
def test_the_sidecar_image_is_platform_supplied_and_pinned(chart):
    sidecar = _sidecar(_render(chart))
    image = sidecar["image"]
    assert image.split("/", 1)[0] == "ghcr.io", f"{chart}: {image}"
    assert image.rsplit(":", 1)[1] not in {"latest", "main", "master"}, (
        f"{chart}: {image} is a moving tag, so the version a pod runs would become "
        "a function of when it last restarted and what its node had cached"
    )
    assert sidecar["imagePullPolicy"] == "IfNotPresent"


@pytest.mark.parametrize("chart", WITH_SSH)
def test_the_referenced_tag_is_one_that_was_built(chart):
    """Without this a chart can reference a version nobody published, which
    fails tenant-side as an `ImagePullBackOff` naming no cause."""
    version = (PRODUCTS / "_lib" / "ssh-sidecar-image" / "VERSION").read_text().strip()
    assert _sidecar(_render(chart))["image"].endswith(f":{version}"), (
        f"{chart} references a sidecar version other than VERSION ({version})"
    )


# --- what a volume session root renders ------------------------------------

@pytest.mark.parametrize("chart", VOLUME_ROOTED)
def test_a_volume_root_is_mounted_read_only_inside_the_session_jail(chart):
    """Read-only is a property of the **mount**, not a setting inside the
    sidecar: a write is EROFS regardless of the uid the session runs as, and
    remounting needs `CAP_SYS_ADMIN`, which Pod Security `baseline` refuses at
    admission. Nothing inside the container is trusted to provide it."""
    sidecar = _sidecar(_render(chart))
    mounts = sidecar.get("volumeMounts") or []
    assert mounts, f"{chart}: a volume-rooted sidecar mounts nothing"

    declared = SESSION_ROOTS[chart].removeprefix("volume:")
    paths = [m["mountPath"] for m in mounts]
    assert f"{SESSION_JAIL}{declared}" in paths, (
        f"{chart}: declares {declared} but mounts {paths}. The session would open "
        "on an empty directory, which reads like missing data"
    )
    for mount in mounts:
        assert mount.get("readOnly") is True, f"{chart}: {mount['mountPath']} is writable"
        assert mount["mountPath"].startswith(SESSION_JAIL), (
            f"{chart}: {mount['mountPath']} is outside the session jail, so the "
            "session cannot reach it"
        )


@pytest.mark.parametrize("chart", VOLUME_ROOTED)
def test_a_volume_root_carries_no_database_and_forwards_nowhere(chart):
    """It serves file transfer and nothing else, so it is given nothing else.
    An absent allowlist is written by the image as `PermitOpen none`."""
    sidecar = _sidecar(_render(chart))
    env = _env(sidecar)
    assert "FREEPOD_PERMIT_OPEN" not in env, f"{chart}: a volume-rooted sidecar may forward"
    assert not sidecar.get("envFrom"), (
        f"{chart}: takes {sidecar.get('envFrom')!r}; a volume-rooted session has no "
        "database tooling to connect with"
    )


@pytest.mark.parametrize("chart", VOLUME_ROOTED)
def test_a_volume_root_is_given_no_uid_to_match(chart):
    """The session runs as root and reads the tree whatever the application
    wrote it as, which removes the per-product uid the old profile needed and
    the coupling to uid conventions inside upstream images. It is sound only
    because nothing writes."""
    sidecar = _sidecar(_render(chart))
    ctx = sidecar.get("securityContext") or {}
    assert ctx.get("runAsUser") == 0, f"{chart}: the sidecar does not run as root"
    rendered = yaml.safe_dump(sidecar)
    assert "internalUid" not in rendered and "internalGid" not in rendered


# --- what an application-container session root requires -------------------

@pytest.mark.parametrize("chart", [c for c, v in SESSION_ROOTS.items() if v == "app-container"])
def test_an_application_root_shares_the_pods_process_namespace_and_not_the_nodes(chart):
    for doc in _render(chart):
        if doc.get("kind") != "Deployment":
            continue
        pod = doc["spec"]["template"]["spec"]
        if not any(c.get("name") == "ssh" for c in pod.get("containers") or []):
            continue
        assert pod.get("shareProcessNamespace") is True, (
            f"{chart}: without it the sidecar cannot reach the application's "
            "filesystem at /proc/<pid>/root -- silently, since it still serves"
        )
        assert pod.get("hostPID") is not True, (
            f"{chart}: hostPID shares the NODE's process namespace, which would let "
            "this tenant's sidecar address processes in every other tenant's pod"
        )


@pytest.mark.parametrize("chart", [c for c, v in SESSION_ROOTS.items() if v == "app-container"])
def test_an_application_root_mounts_no_tenant_volume(chart):
    """File transfer lands in the application container's own filesystem; a
    mounted view beside it would be a second, weaker answer."""
    assert not _sidecar(_render(chart)).get("volumeMounts")


@pytest.mark.parametrize("chart", sorted(SESSION_ROOTS))
def test_no_container_takes_an_added_capability(chart):
    """Tenant namespaces enforce Pod Security `baseline`, which refuses every
    non-default capability at admission -- a pod asking for one never schedules,
    and the Helm upgrade fails with `violates PodSecurity "baseline:latest"`
    rather than anything naming the chart."""
    for container in _containers(_render(chart)):
        ctx = container.get("securityContext") or {}
        added = (ctx.get("capabilities") or {}).get("add") or []
        assert added == [], f"{chart}: {container['name']} requests {added!r}"
        assert ctx.get("privileged") is not True, f"{chart}: {container['name']} is privileged"


# --- the Service every deployment presents to the edge ---------------------

@pytest.mark.parametrize("chart", WITH_SSH)
def test_the_ssh_service_publishes_not_ready_addresses(chart):
    """The endpoints include the pod whenever it exists, ready or not."""
    service = _ssh_service(_render(chart))
    assert service["spec"].get("publishNotReadyAddresses") is True, (
        f"{chart}: the SSH Service does not publish not-ready addresses, so a "
        "deployment whose app container is crash-looping is unreachable"
    )


def test_every_deployment_presents_the_same_service_to_the_edge():
    """The edge derives an upstream address by convention and knows nothing
    about session roots, so the Services must differ only in their selectors."""
    services = {chart: _ssh_service(_render(chart)) for chart in WITH_SSH}
    for chart, service in services.items():
        assert service["metadata"]["name"] == "t-ssh", f"{chart}: {service['metadata']['name']}"
    reference = services["custom"]
    for chart, service in services.items():
        assert service["spec"]["ports"] == reference["spec"]["ports"], chart
        assert service["metadata"]["labels"] == reference["metadata"]["labels"], chart


@pytest.mark.parametrize("chart", WITH_SSH)
def test_the_sidecar_is_probed_on_its_ssh_port(chart):
    """Both probes are plain TCP checks on 2222 -- no exec, no credentials."""
    sidecar = _sidecar(_render(chart))
    for probe_name in ("startupProbe", "livenessProbe"):
        probe = sidecar.get(probe_name)
        assert probe, f"{chart}: the sidecar declares no {probe_name}"
        assert set(probe) & {"exec", "httpGet"} == set(), (
            f"{chart}: the {probe_name} must be a bare TCP check -- an exec probe "
            "couples liveness to the container's own state"
        )
        assert probe.get("tcpSocket", {}).get("port") == SSH_PORT


@pytest.mark.parametrize("chart", WITH_SSH)
def test_no_other_container_is_probed_on_the_ssh_port(chart):
    """The probes belong to the sidecar and were not spliced anywhere else."""
    for container in _containers(_render(chart)):
        if container.get("name") == "ssh":
            continue
        for probe_name in ("startupProbe", "livenessProbe", "readinessProbe"):
            probe = container.get(probe_name) or {}
            assert probe.get("tcpSocket", {}).get("port") != SSH_PORT, (
                f"{chart}: container {container.get('name')!r} carries a {probe_name} "
                "on the SSH port"
            )


@pytest.mark.parametrize("chart", sorted(SESSION_ROOTS))
def test_no_routing_object_is_rendered(chart):
    """Routing is resolved per connection; nothing describes it as an object."""
    for doc in _render(chart):
        assert doc.get("kind") != "Pipe", (
            f"{chart}: renders a Pipe. The edge resolves routing from the platform "
            "database, so a routing object here is state nothing reads and nothing reaps"
        )


# --- the inputs the chart supplies -----------------------------------------

@pytest.mark.parametrize("chart", WITH_SSH)
def test_the_chart_supplies_every_input_the_image_requires(chart):
    """Missing any of these is a pod that will not start -- the image exits
    naming the offending variable rather than serving misconfigured."""
    env = _env(_sidecar(_render(chart)))

    assert env["FREEPOD_AUTHORIZED_KEYS"]["value"] == PLATFORM_KEY
    assert env["FREEPOD_LOGIN_USER"]["value"] == "t", (
        f"{chart}: the sidecar must accept the release name as a login account; the "
        "edge has one username convention and will not send root"
    )

    # Both spellings straight from the reconciler's values. Not from a pod
    # label: that would be the same fact by a longer route, and would change the
    # pod-template hash on every apply -- see the test below.
    assert env["FREEPOD_RELEASE_ID"]["value"] == RELEASE_ID
    assert env["FREEPOD_RELEASE_NUMBER"]["value"] == RELEASE_NUMBER
    for name in ("FREEPOD_RELEASE_ID", "FREEPOD_RELEASE_NUMBER"):
        assert "valueFrom" not in env[name], f"{chart}: {name} is read from the pod"


@pytest.mark.parametrize("chart", WITH_SSH)
def test_ssh_access_does_not_make_a_redeploy_cycle_the_pod(chart):
    """A release identity reaches the sidecar as a value, never as a pod label.

    A label would be the same fact by a longer route and would put the release
    identity into the pod-template hash, so a redeploy with identical values
    would cycle the deployment's pod instead of being a Helm no-op. `custom`
    renders such a label for its log pipeline and accepts that cost for its own
    reasons; no product should pay it merely for having SSH access.

    Asserted on the pod template rather than the whole render, because several
    of these charts generate a random secret on every render.
    """
    def templates(release_id: str) -> list[dict]:
        args = ["helm", "template", "t", str(PRODUCTS / chart / "chart"),
                "--set-string", f"caelus.ssh.platformPublicKey={PLATFORM_KEY}",
                "--set-string", f"caelus.releaseId={release_id}",
                "--set-string", f"caelus.releaseNumber={RELEASE_NUMBER}"]
        for key, value in EXTRA_VALUES.get(chart, {}).items():
            args += ["--set", f"{key}={value}"]
        result = subprocess.run(args, capture_output=True, text=True)
        assert result.returncode == 0, f"{chart}: {result.stderr}"
        out = []
        for doc in yaml.safe_load_all(result.stdout):
            if not isinstance(doc, dict) or doc.get("kind") not in {"Deployment", "StatefulSet"}:
                continue
            out.append((doc["spec"]["template"].get("metadata") or {}).get("labels") or {})
        return out

    first, second = templates(RELEASE_ID), templates("00000000-0000-4000-8000-000000000002")
    assert first, f"{chart} rendered no workload pod template to compare"

    if chart in CHARTS_RENDERING_THEIR_OWN_RELEASE_LABEL:
        pytest.skip(f"{chart} renders the label for its own log pipeline")
    assert first == second, (
        f"{chart}: the release identity reached a pod template label, so every "
        "redeploy now cycles this deployment's pods"
    )


# --- the gate the API hides the feature on ---------------------------------

@pytest.mark.parametrize("chart", WITH_SSH)
def test_the_api_finds_the_object_it_gates_file_access_on(chart):
    """The deployment card's Files panel is hidden when the API answers 404,
    and the API answers 404 when it cannot find this object in the namespace.

    Every test of that endpoint stubs the lookup, so nothing else ties it to
    what a chart renders: the gate once named an object the charts stopped
    rendering, and the only symptom was a button quietly vanishing from the UI.
    """
    from app.provisioner import Provisioner

    kind = Provisioner.SSH_ACCESS_KIND
    wanted = dict(
        pair.split("=", 1) for pair in Provisioner.ssh_access_selector("t").split(",")
    )

    matches = [
        doc
        for doc in _render(chart)
        if doc.get("kind", "").lower() == kind
        and wanted.items() <= ((doc.get("metadata") or {}).get("labels") or {}).items()
    ]
    assert matches, (
        f"{chart}: renders no {kind} matching {wanted}, so the API reports no file "
        "access for it and the UI hides the Files panel"
    )


@pytest.mark.parametrize("chart", WITHOUT_SSH)
def test_a_product_with_no_ssh_renders_nothing_the_gate_would_find(chart):
    from app.provisioner import Provisioner

    kind = Provisioner.SSH_ACCESS_KIND
    wanted = dict(
        pair.split("=", 1) for pair in Provisioner.ssh_access_selector("t").split(",")
    )
    for doc in _render(chart):
        if doc.get("kind", "").lower() != kind:
            continue
        labels = (doc.get("metadata") or {}).get("labels") or {}
        assert not wanted.items() <= labels.items(), (
            f"{chart}: renders a {kind} the gate would find, so the UI would offer "
            "file access for a deployment that has none"
        )
