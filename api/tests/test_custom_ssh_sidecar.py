"""`custom` declares an application-container session root, and what that grants
is load-bearing.

It puts a shell in the tenant's own application container, and file transfer
into it, from one container beside it. Three properties make that acceptable
rather than alarming, and each is one field that would fail silently if it were
dropped:

* the shared process namespace is the **pod's**, never the node's -- process
  identifiers resolve within the namespace that shares them, so this is what
  bounds the sidecar to the tenant's own containers;
* the application container gains **nothing** from the declaration, and no
  container takes an added capability;
* the image reference is a **system value pinned to an exact version**, because
  that container holds the platform's trusted key.

None of the three has a runtime symptom when wrong -- a `hostPID` pod works, an
application container with extra capabilities works, a moving tag works until
two nodes disagree -- so they are asserted here.

What every product's chart must render, and the classification of the catalog
that keeps a product from acquiring SSH access by omission, live in
`test_ssh_chart_contract.py`. This file is only about what `custom` gets that a
curated product does not.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from app.services.template_values import validate_user_values

REPO = Path(__file__).resolve().parents[2]
CHART = REPO / "products" / "custom" / "chart"
PRODUCTS = REPO / "products"
SSH_PORT = 2222

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

PLATFORM_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIV5/SURDe/M7JtAheJuxURSGgpFB8Yfrd/LY6c9+DzR platform"
POOLER = "caelus-tenant-pooler.caelus.svc.cluster.local"

# What the reconciler projects for a real `custom` deployment. Every one of
# these is a system value or a reconciler override; none is tenant-supplied.
BASE = {
    "hostname": "app.example.test",
    "caelus.owner.id": "1",
    "relationalStorage.enabled": "true",
    "caelus.database.host": POOLER,
    "caelus.database.port": "6432",
    "caelus.database.secretName": "t-db",
}
STRINGS = {
    "caelus.releaseId": "42",
    "caelus.releaseNumber": "7",
    "caelus.ssh.platformPublicKey": PLATFORM_KEY,
}


@pytest.fixture(scope="module", autouse=True)
def _resolved_dependencies():
    """`charts/` is a gitignored build artifact; vendor before rendering."""
    result = subprocess.run(
        ["helm", "dependency", "build", str(CHART)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def _render(**overrides: str) -> list[dict]:
    values = {**BASE, **overrides}
    args = ["helm", "template", "t", str(CHART)]
    for key, value in values.items():
        args += ["--set", f"{key}={value}"]
    for key, value in STRINGS.items():
        args += ["--set-string", f"{key}={value}"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]


def _pod(docs: list[dict]) -> dict:
    deployment = next(d for d in docs if d["kind"] == "Deployment")
    return deployment["spec"]["template"]["spec"]


def _container(docs: list[dict], name: str) -> dict:
    return next(c for c in _pod(docs)["containers"] if c["name"] == name)


def test_it_renders_a_sidecar_and_a_service_and_nothing_else():
    """The chart renders no Secret and no ConfigMap.

    The sidecar takes every input as an environment variable and writes its own
    `authorized_keys`, `sshd_config` and host key at startup, so an object of
    either kind would be one nothing reads.
    """
    docs = _render()

    ssh_services = [
        d
        for d in docs
        if d["kind"] == "Service"
        and any(p.get("port") == SSH_PORT for p in d["spec"].get("ports") or [])
    ]
    assert len(ssh_services) == 1, "expected exactly one Service fronting the sidecar"
    assert ssh_services[0]["metadata"]["name"] == "t-ssh"

    assert _container(docs, "ssh"), "no sidecar container"
    ssh_owned = [
        d
        for d in docs
        if d["kind"] in {"Secret", "ConfigMap"}
        and (d["metadata"].get("labels") or {}).get("caelus.dev/component") == "ssh"
    ]
    assert ssh_owned == [], (
        f"the chart rendered {[d['kind'] for d in ssh_owned]}, which nothing reads"
    )


def test_the_pod_shares_its_own_process_namespace_and_not_the_nodes():
    """Pod-scoped is what bounds `CAP_SYS_PTRACE` to this tenant's containers."""
    pod = _pod(_render())
    assert pod.get("shareProcessNamespace") is True, (
        "without a shared process namespace the sidecar cannot reach the "
        "application's filesystem at /proc/<pid>/root, and an application-container "
        "session root is gone -- silently, since the container still serves"
    )
    assert pod.get("hostPID") is not True, (
        "hostPID shares the NODE's process namespace, which would let this "
        "tenant's sidecar address processes in every other tenant's pod"
    )


def test_no_container_takes_an_added_capability():
    """Tenant namespaces enforce Pod Security `baseline`, which refuses every
    non-default capability at admission -- a pod asking for one never schedules,
    and the Helm upgrade fails with `violates PodSecurity "baseline:latest"`
    rather than anything naming the chart.

    So this chart takes none. `CAP_SYS_PTRACE` would buy `strace`, `gdb` and
    `py-spy`; granting it means raising the namespace, which is tracked
    separately. Entering the application container needs only `CAP_SYS_CHROOT`
    from the default set, so the shell, file transfer, the toolbox and
    forwarding are all unaffected.
    """
    docs = _render()

    for container in _pod(docs)["containers"]:
        ctx = container.get("securityContext") or {}
        added = (ctx.get("capabilities") or {}).get("add") or []
        assert added == [], (
            f"{container['name']} requests {added!r}. Pod Security `baseline` "
            "refuses non-default capabilities, so this pod would be rejected at "
            "admission and the deployment would never start"
        )
        assert ctx.get("privileged") is not True, f"{container['name']} is privileged"


def test_the_sidecar_image_is_platform_supplied_and_pinned():
    ssh = _container(_render(), "ssh")
    image = ssh["image"]
    registry = image.split("/", 1)[0]
    assert registry == "ghcr.io", image
    tag = image.rsplit(":", 1)[1]
    assert tag not in {"latest", "main", "master"}, (
        f"{image} is a moving tag: the version a pod runs would become a "
        "function of when it last restarted and what its node had cached"
    )
    assert ssh["imagePullPolicy"] == "IfNotPresent", (
        "the tag is immutable, so tag and content are one to one -- state the "
        "policy rather than inheriting whatever the default is"
    )


def test_a_tenant_cannot_choose_the_sidecar_image_or_the_trusted_key():
    """Rejected at the API, before Helm ever sees the value.

    `custom`'s tenant-facing schema is closed and admits `hostname` and `image`
    only. Every property this guards is one a tenant substituting it would use to
    replace the container holding the platform's private-key counterpart, or to
    change what its sessions are allowed to do.
    """
    catalog = yaml.safe_load((PRODUCTS / "catalog" / "custom" / "custom.yaml").read_text())
    schema = catalog["template"]["values_schema"]
    assert schema.get("additionalProperties") is False

    for attempt in (
        {"hostname": "a.example.test", "sshSidecarImage": "evil/sidecar:1"},
        {"hostname": "a.example.test", "caelus": {"ssh": {"platformPublicKey": "ssh-ed25519 AAAA attacker"}}},
        {"hostname": "a.example.test", "sessionRoot": "app-container"},
    ):
        with pytest.raises(Exception):
            validate_user_values(attempt, schema)


def test_the_sidecar_receives_every_input_the_image_requires():
    """Missing any of these is a pod that will not start -- the image exits
    naming the offending variable rather than serving misconfigured."""
    ssh = _container(_render(), "ssh")
    env = {e["name"]: e for e in ssh.get("env") or []}

    assert env["FREEPOD_AUTHORIZED_KEYS"]["value"] == PLATFORM_KEY
    assert env["FREEPOD_PERMIT_OPEN"]["value"] == f"{POOLER}:6432"

    # Both spellings straight from the reconciler's values. `custom` also stamps
    # `caelus.dev/release-id` on its pod for the log pipeline, but the sidecar
    # does not read it from there: a chart that had to render a label to get SSH
    # access would put the release identity into every pod-template hash.
    assert env["FREEPOD_RELEASE_ID"]["value"] == "42"
    assert env["FREEPOD_RELEASE_NUMBER"]["value"] == "7"
    for name in ("FREEPOD_RELEASE_ID", "FREEPOD_RELEASE_NUMBER"):
        assert "valueFrom" not in env[name], f"{name} is read from the pod"

    # The account the edge authenticates as upstream. It has one username
    # convention -- the deployment name -- and knows nothing about profiles, so
    # a sidecar without this account refuses every connection with `Invalid
    # user`, which reads at the client as an authorization failure.
    assert env["FREEPOD_SESSION_ROOT"]["value"] == "app-container", (
        "the session root is what grants the shell, the remote commands and the "
        "database tooling; the sidecar checks the declaration and never the pod"
    )
    assert env["FREEPOD_LOGIN_USER"]["value"] == "t", (
        "the sidecar must accept the release name as a login account; the edge "
        "has one username convention and will not send root"
    )

    # The database variables reach the sidecar's OWN environment: a developer
    # connects precisely when the application is broken.
    sources = [s["secretRef"]["name"] for s in ssh.get("envFrom") or []]
    assert "t-db" in sources


def test_the_forward_allowlist_is_spelled_as_a_client_will_write_it():
    """`PermitOpen` matches the destination as the client wrote it and resolves
    afterwards, so the rendered value and the documented address are one fact."""
    ssh = _container(_render(), "ssh")
    env = {e["name"]: e.get("value") for e in ssh.get("env") or []}
    permit = env["FREEPOD_PERMIT_OPEN"]

    assert permit == f"{POOLER}:6432"
    assert "*" not in permit, "a wildcard port is not an allowlist"

    # The pooler lives in each environment's own namespace, so the address is
    # per environment and the docs must carry every spelling the chart can
    # render -- not one of them as though it were universal.
    documented = (PRODUCTS / "custom" / "README.md").read_text()
    for namespace in ("caelus", "caelus-dev"):
        rendered = _container(
            _render(**{"caelus.database.host": f"caelus-tenant-pooler.{namespace}.svc.cluster.local"}),
            "ssh",
        )
        value = next(
            e["value"] for e in rendered["env"] if e["name"] == "FREEPOD_PERMIT_OPEN"
        )
        assert value in documented, (
            f"products/custom/README.md does not contain {value!r} verbatim. A "
            "documented address that differs by so much as a search domain "
            "produces a refusal that reads like an authorization failure"
        )


def test_a_deployment_with_no_database_still_gets_a_session():
    """The toolbox is a facility the sidecar offers, not a precondition it
    imposes.

    `custom` has relational storage today, but that is a property of the product
    rather than of the session root: a shell in the application container is
    worth having with or without a database. Coupling the two would surface as a
    pod that never starts, for the first product to declare an application root
    without one -- and `custom` will not stay the only such product.

    So the chart renders the sidecar either way, with the two database-derived
    pieces absent together. The image then writes `PermitOpen none` and declines
    the database tools by name; every other session path is unchanged.
    """
    docs = _render(**{"relationalStorage.enabled": "false", "caelus.database": "null"})

    ssh = _container(docs, "ssh")
    env = {e["name"] for e in ssh.get("env") or []}

    assert "FREEPOD_PERMIT_OPEN" not in env, (
        "an allowlist rendered from an absent database is 'host:port' with both "
        "halves empty, which the image rejects -- a pod that never starts because "
        "of a facility this deployment was not asking for"
    )
    assert not ssh.get("envFrom"), (
        f"the sidecar takes {ssh.get('envFrom')!r} from a deployment with no database"
    )

    # Everything the session root is actually for is still here.
    assert {
        "FREEPOD_SESSION_ROOT",
        "FREEPOD_AUTHORIZED_KEYS",
        "FREEPOD_RELEASE_ID",
        "FREEPOD_RELEASE_NUMBER",
        "FREEPOD_LOGIN_USER",
    } <= env
    assert _pod(docs).get("shareProcessNamespace") is True
    assert any(
        d["kind"] == "Service" and any(p.get("port") == SSH_PORT for p in d["spec"]["ports"])
        for d in docs
    ), "the deployment is unroutable at the SSH edge without its Service"


def test_an_application_session_root_mounts_no_tenant_volume():
    """Nothing of the tenant's is mounted in: the session is rooted at the
    application container's own filesystem, which the sidecar reaches through
    the shared process namespace rather than through a mount."""
    ssh = _container(_render(), "ssh")
    assert not ssh.get("volumeMounts"), (
        f"the sidecar mounts {ssh.get('volumeMounts')!r}. File transfer lands in the "
        "application container's own filesystem; a mounted view beside it would be "
        "a second, weaker answer"
    )
