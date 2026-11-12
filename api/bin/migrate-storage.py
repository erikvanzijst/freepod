#!/usr/bin/env python3
"""Moves existing deployments' volumes from local-path onto the environment's
Ceph class, one deployment per run (migrate-deployment-storage). Run it in the
reconcile worker's pod, which has helm, kubectl and the database:

  kubectl exec -it -n caelus deploy/caelus-worker -- python /app/bin/migrate-storage.py plan

Every step works out where it stands from the cluster and the database, so a
`migrate` or `rollback` that stopped part way is finished by running it again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Iterator
from uuid import UUID

import yaml
from sqlalchemy import text
from sqlmodel import select

from app import post_render
from app.config import get_settings
from app.db import get_engine, session_scope
from app.models import DeploymentORM
from app.provisioner import _with_optional_digest
from app.services import power
from app.services.errors import CaelusException
from app.services.jobs import JobService
from app.services.reconcile_constants import (
    DEPLOYMENT_STATUS_DELETED,
    DEPLOYMENT_STATUS_ERROR,
    DEPLOYMENT_STATUS_READY,
    JOB_REASON_UPDATE,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    POWER_REASON_MAINTENANCE,
    POWER_STATE_RUNNING,
    POWER_STATE_STOPPED,
)

LABEL = "caelus.dev/migration"
ROLE = "caelus.dev/migration-role"
CLAIM = "caelus.dev/migration-claim"
RELEASED_AT = "caelus.dev/migration-released-at"
SOURCE, COPY = "source", "copy"
LOCAL_PATH = "local-path"
SINGLE_POD = "ReadWriteOncePod"
RSYNC_IMAGE = (
    "instrumentisto/rsync-ssh:alpine3.23-r3"
    "@sha256:6cbad37c2fbdca4ac7ad9d1c1bb8990af9efd4dc76321b349935876cbb1e9e4a"
)
TENANT_TAINT = "caelus.dev/node-pool"
FILL_LIMIT = 0.8
POLL = 3

_UNITS = {
    "": 1, "k": 10**3, "M": 10**6, "G": 10**9, "T": 10**12, "P": 10**15,
    "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40, "Pi": 2**50,
}


class Fail(Exception):
    pass


def log(message: str) -> None:
    print(f"{datetime.now(UTC):%H:%M:%S} {message}", flush=True)


def quantity(value: str) -> int:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([kMGTP]i?|Ki)?", value.strip())
    if not match:
        raise Fail(f"unreadable quantity {value!r}")
    return int(float(match[1]) * _UNITS[match[2] or ""])


def human(size: int) -> str:
    for unit in ("Ti", "Gi", "Mi", "Ki"):
        if size >= _UNITS[unit]:
            return f"{size / _UNITS[unit]:.1f}{unit}"
    return f"{size}B"


def wait_for(what: str, check: Callable[[], Any], timeout: float) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() > deadline:
            raise Fail(f"timed out after {int(timeout)}s waiting for {what}")
        time.sleep(POLL)


# ── kubectl / helm ───────────────────────────────────────────────────────


def run(cmd: list[str], *, input: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, input=input, capture_output=True, text=True)


def kubectl(*args: str, input: str | None = None) -> str:
    proc = run(["kubectl", *args], input=input)
    if proc.returncode:
        raise Fail(f"kubectl {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def get(kind: str, name: str, ns: str | None = None) -> dict[str, Any] | None:
    proc = run(["kubectl", "get", kind, name, *(["-n", ns] if ns else []), "-o", "json"])
    if proc.returncode:
        if "NotFound" in proc.stderr:
            return None
        raise Fail(f"kubectl get {kind} {name}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def items(kind: str, *, ns: str | None = None, selector: str | None = None) -> list[dict[str, Any]]:
    args = ["get", kind, *(["-n", ns] if ns else ["-A"])]
    if selector:
        args += ["-l", selector]
    return json.loads(kubectl(*args, "-o", "json"))["items"]


def create(obj: dict[str, Any]) -> None:
    kubectl("create", "-f", "-", input=json.dumps(obj))


def patch(kind: str, name: str, body: dict[str, Any], ns: str | None = None) -> None:
    kubectl("patch", kind, name, *(["-n", ns] if ns else []), "--type", "merge", "-p", json.dumps(body))


def delete(kind: str, name: str, ns: str, *extra: str) -> None:
    kubectl("delete", kind, name, "-n", ns, "--ignore-not-found", "--wait=true", *extra)


def meta(obj: dict[str, Any]) -> dict[str, Any]:
    return obj.get("metadata") or {}


def spec(obj: dict[str, Any]) -> dict[str, Any]:
    return obj.get("spec") or {}


# ── The database ─────────────────────────────────────────────────────────


@dataclass
class Snapshot:
    id: UUID
    user_id: int
    owner: str
    product: str
    release: str
    namespace: str
    status: str
    last_error: str | None
    storage_class: str | None
    desired_state: str
    applied_state: str
    reason: str | None
    settled: bool
    chart_ref: str
    chart_version: str
    chart_digest: str | None

    @property
    def under_maintenance(self) -> bool:
        return self.reason == POWER_REASON_MAINTENANCE

    @property
    def label(self) -> str:
        return f"{self.product} {self.release} ({self.owner}, {self.id})"


def _snapshot(session, deployment: DeploymentORM) -> Snapshot:
    template = deployment.desired_template
    product = template.product
    desired, applied = deployment.desired_power, deployment.applied_power
    open_jobs = JobService(session).list_jobs(
        statuses=[JOB_STATUS_QUEUED, JOB_STATUS_RUNNING], deployment_id=deployment.id
    )
    return Snapshot(
        id=deployment.id,
        user_id=deployment.user_id,
        owner=deployment.user.email if deployment.user else str(deployment.user_id),
        product=product.slug or product.name,
        release=deployment.name,
        namespace=deployment.namespace,
        status=deployment.status,
        last_error=deployment.last_error,
        storage_class=deployment.storage_class,
        desired_state=desired.state if desired else POWER_STATE_RUNNING,
        applied_state=applied.state if applied else POWER_STATE_RUNNING,
        reason=desired.reason if desired else None,
        settled=not open_jobs and deployment.desired_power_id == deployment.applied_power_id,
        chart_ref=template.chart_ref,
        chart_version=template.chart_version,
        chart_digest=template.chart_digest,
    )


def load(deployment_id: UUID) -> Snapshot:
    with session_scope() as session:
        deployment = session.get(DeploymentORM, deployment_id)
        if deployment is None or deployment.status == DEPLOYMENT_STATUS_DELETED:
            raise Fail(f"no deployment {deployment_id}")
        return _snapshot(session, deployment)


def deployments() -> Iterator[Snapshot]:
    with session_scope() as session:
        rows = session.exec(
            select(DeploymentORM)
            .where(DeploymentORM.deleted_at.is_(None), DeploymentORM.status != DEPLOYMENT_STATUS_DELETED)
            .order_by(DeploymentORM.created_at)
        ).all()
        for row in rows:
            yield _snapshot(session, row)


def set_storage_class(deployment_id: UUID, storage_class: str | None) -> None:
    with session_scope() as session:
        row = session.get(DeploymentORM, deployment_id)
        row.storage_class = storage_class
        session.add(row)
        session.commit()
    log(f"recorded storage class {storage_class or 'none'}")


def enqueue_reconcile(deployment_id: UUID) -> None:
    with session_scope() as session:
        JobService(session).enqueue_job(deployment_id=deployment_id, reason=JOB_REASON_UPDATE)
        session.commit()


def settle(deployment_id: UUID, what: str, timeout: float) -> Snapshot:
    def check() -> Snapshot | None:
        snap = load(deployment_id)
        if not snap.settled:
            return None
        if snap.status == DEPLOYMENT_STATUS_ERROR:
            raise Fail(f"{what} failed: {snap.last_error}")
        return snap if snap.status == DEPLOYMENT_STATUS_READY else None

    snap = wait_for(what, check, timeout)
    log(f"{what}: done")
    return snap


class Lock:
    """One run per deployment, across pods: a session advisory lock."""

    def __init__(self, deployment_id: UUID):
        self._key = int.from_bytes(hashlib.sha256(str(deployment_id).encode()).digest()[:8], "big", signed=True)
        self._conn = None

    def __enter__(self) -> Lock:
        self._conn = get_engine().connect()
        if not self._conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": self._key}).scalar():
            self._conn.close()
            raise Fail("another run is already working on this deployment")
        return self

    def __exit__(self, *_: Any) -> None:
        self._conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": self._key})
        self._conn.close()


# ── What the release renders against what the namespace holds ───────────


@dataclass
class Claim:
    name: str
    size: str
    statefulset: str | None
    live: dict[str, Any] | None

    @property
    def volume(self) -> str | None:
        return spec(self.live).get("volumeName") if self.live else None

    @property
    def live_class(self) -> str | None:
        return spec(self.live).get("storageClassName") if self.live else None


@dataclass
class Inspection:
    claims: list[Claim] = field(default_factory=list)
    statefulsets: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def moving(self) -> list[Claim]:
        return [c for c in self.claims if c.live is not None]


def render(snap: Snapshot) -> list[dict[str, Any]]:
    got = run(["helm", "get", "values", snap.release, "-n", snap.namespace, "-o", "json"])
    if got.returncode:
        raise Fail(f"helm get values: {got.stderr.strip()}")
    values = json.loads(got.stdout or "null")
    with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
        json.dump(values or {}, f)
        f.flush()
        cmd = [
            "helm", "template", snap.release,
            _with_optional_digest(chart_ref=snap.chart_ref, chart_digest=snap.chart_digest),
            "-n", snap.namespace, "-f", f.name,
        ]
        if not snap.chart_digest:
            cmd += ["--version", snap.chart_version]
        proc = run(cmd)
    if proc.returncode:
        raise Fail(f"helm template: {proc.stderr.strip()}")
    return [doc for doc in yaml.safe_load_all(proc.stdout) if isinstance(doc, dict)]


def inspect(snap: Snapshot, allowed: set[str], known: set[str] = frozenset()) -> Inspection:
    """The release's claims, with what the namespace holds for each. A live
    claim must be on one of `allowed`; `known` names claims an earlier run
    removed, which count although nothing holds them now."""
    out = Inspection()
    docs = render(snap)
    try:
        post_render.refuse_shared_claims(docs)
    except post_render.SharedClaim as exc:
        out.problems.append(f"the release cannot be single-pod: {exc}")

    helm_claims: dict[str, str] = {}
    templates: list[tuple[str, str, str]] = []
    for doc in docs:
        if doc.get("kind") == "PersistentVolumeClaim":
            helm_claims[meta(doc)["name"]] = spec(doc)["resources"]["requests"]["storage"]
        elif doc.get("kind") == "StatefulSet" and spec(doc).get("volumeClaimTemplates"):
            out.statefulsets.append(meta(doc)["name"])
            for tmpl in spec(doc)["volumeClaimTemplates"]:
                templates.append((meta(doc)["name"], meta(tmpl)["name"], spec(tmpl)["resources"]["requests"]["storage"]))
        sts = get("statefulset", meta(doc)["name"], snap.namespace) if doc.get("kind") == "StatefulSet" else None
        if sts and (spec(sts).get("persistentVolumeClaimRetentionPolicy") or {}).get("whenDeleted") == "Delete":
            out.problems.append(f"StatefulSet {meta(sts)['name']} deletes its claims with it")

    live = {meta(pvc)["name"]: pvc for pvc in items("pvc", ns=snap.namespace) if LABEL not in meta(pvc).get("labels", {})}
    for name, size in helm_claims.items():
        out.claims.append(Claim(name, size, None, live.pop(name, None)))
    for name in sorted(set(live) | (set(known) - set(helm_claims))):
        owner = next(
            ((sts, size) for sts, tmpl, size in templates if re.fullmatch(rf"{re.escape(tmpl)}-{re.escape(sts)}-\d+", name)),
            None,
        )
        if owner is None:
            if name in live:
                out.problems.append(f"claim {name} is not rendered by the release; delete it or leave the deployment")
            continue
        out.claims.append(Claim(name, owner[1], owner[0], live.get(name)))

    for claim in out.moving:
        if claim.live_class not in allowed:
            out.problems.append(f"claim {claim.name} is on {claim.live_class}, which this run does not move")
        if spec(claim.live).get("volumeMode", "Filesystem") != "Filesystem":
            out.problems.append(f"claim {claim.name} is a block volume")
        if (claim.live.get("status") or {}).get("phase") != "Bound":
            out.problems.append(f"claim {claim.name} is not bound")
    return out


# ── Pods ─────────────────────────────────────────────────────────────────


def run_pod(snap: Snapshot, purpose: str, mounts: list[tuple[str, str, bool]], script: str, timeout: float) -> str:
    """Run `script` as root in the deployment's namespace with each
    `(path, claim, read_only)` mounted, and return its output."""
    name = f"caelus-migrate-{hashlib.sha1((purpose + script).encode()).hexdigest()[:10]}"
    pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "namespace": snap.namespace, "labels": {LABEL: str(snap.id)}},
        "spec": {
            "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "enableServiceLinks": False,
            "tolerations": [{"key": TENANT_TAINT, "operator": "Exists", "effect": "NoSchedule"}],
            "securityContext": {"runAsUser": 0, "runAsGroup": 0, "seccompProfile": {"type": "RuntimeDefault"}},
            "containers": [{
                "name": "migrate",
                "image": RSYNC_IMAGE,
                "command": ["sh", "-c", script],
                "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"memory": "1Gi"}},
                "volumeMounts": [
                    {"name": f"v{i}", "mountPath": path, "readOnly": ro} for i, (path, _, ro) in enumerate(mounts)
                ],
            }],
            "volumes": [
                {"name": f"v{i}", "persistentVolumeClaim": {"claimName": claim, "readOnly": ro}}
                for i, (_, claim, ro) in enumerate(mounts)
            ],
        },
    }
    delete("pod", name, snap.namespace)
    create(pod)
    try:
        def finished() -> str | None:
            phase = ((get("pod", name, snap.namespace) or {}).get("status") or {}).get("phase")
            return phase if phase in ("Succeeded", "Failed") else None

        phase = wait_for(purpose, finished, timeout)
        output = run(["kubectl", "logs", "-n", snap.namespace, name]).stdout
        if phase != "Succeeded":
            raise Fail(f"{purpose} failed:\n{output.strip()}")
        return output
    finally:
        delete("pod", name, snap.namespace)


def used_bytes(snap: Snapshot, claim: Claim) -> int:
    out = run_pod(snap, f"measure {claim.name}", [("/v", claim.name, True)], "du -sk /v | cut -f1", 300)
    return int(out.strip().splitlines()[-1]) * 1024


COPY_SCRIPT = r"""
set -eu
need=$(du -sk /src | cut -f1)
room=$(( $(df -Pk /dst | awk 'NR==2 {print $4}') + $(du -sk /dst | cut -f1) ))
if [ "$need" -gt "$room" ]; then echo "needs ${need}K, the new volume holds ${room}K"; exit 3; fi
rsync -aHAX --numeric-ids --delete /src/ /dst/
diff=$(rsync -aHAXc --numeric-ids --delete --dry-run --itemize-changes /src/ /dst/)
if [ -n "$diff" ]; then echo "verification found differences:"; echo "$diff" | head -50; exit 4; fi
sync
echo "copied ${need}K"
"""


def pods_using(ns: str, claims: set[str]) -> list[str]:
    using = []
    for pod in items("pod", ns=ns):
        if (pod.get("status") or {}).get("phase") in ("Succeeded", "Failed"):
            continue
        names = {(v.get("persistentVolumeClaim") or {}).get("claimName") for v in spec(pod).get("volumes") or []}
        if names & claims:
            using.append(meta(pod)["name"])
    return using


# ── Volumes ──────────────────────────────────────────────────────────────


def tagged(deployment_id: UUID, role: str) -> dict[str, dict[str, Any]]:
    """This deployment's PVs in `role`, by the claim they belong to."""
    found: dict[str, dict[str, Any]] = {}
    for pv in items("pv", selector=f"{LABEL}={deployment_id},{ROLE}={role}"):
        claim = meta(pv).get("annotations", {}).get(CLAIM)
        if claim in found:
            raise Fail(f"two {role} volumes for claim {claim}: {meta(found[claim])['name']}, {meta(pv)['name']}")
        found[claim] = pv
    return found


def tag(pv: str, deployment_id: UUID, role: str, claim: str) -> None:
    patch("pv", pv, {
        "metadata": {"labels": {LABEL: str(deployment_id), ROLE: role}, "annotations": {CLAIM: claim}},
        "spec": {"persistentVolumeReclaimPolicy": "Retain"},
    })


def reserve(pv: str, ns: str, claim: str) -> None:
    """Point `pv` at `claim` by name only, so the claim of that name binds to it
    once it exists and nothing else does."""
    patch("pv", pv, {"spec": {"claimRef": {
        "apiVersion": "v1", "kind": "PersistentVolumeClaim", "namespace": ns, "name": claim,
        "uid": None, "resourceVersion": None,
    }}})

    def available() -> bool:
        current = get("pv", pv) or {}
        return (current.get("status") or {}).get("phase") in ("Available", "Bound")

    wait_for(f"volume {pv} to be reserved for {claim}", available, 120)


def bound(ns: str, claim: str, pv: str, timeout: float = 120) -> None:
    def check() -> bool:
        pvc = get("pvc", claim, ns)
        if pvc is None or (pvc.get("status") or {}).get("phase") != "Bound":
            return False
        if spec(pvc).get("volumeName") != pv:
            raise Fail(f"claim {claim} bound to {spec(pvc).get('volumeName')}, not {pv}")
        return True

    wait_for(f"claim {claim} to bind {pv}", check, timeout)


def stage(snap: Snapshot, claim: Claim, target: str, timeout: float) -> str:
    """Copy `claim` onto a volume of `target` reserved for its name, reusing and
    re-syncing the copy an earlier run left. Returns the volume."""
    temp = f"{claim.name}-migrate"
    tag(claim.volume, snap.id, SOURCE, claim.name)
    copy = tagged(snap.id, COPY).get(claim.name)
    if get("pvc", temp, snap.namespace) is None:
        pvc: dict[str, Any] = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": temp, "namespace": snap.namespace, "labels": {LABEL: str(snap.id)}},
            "spec": {
                "storageClassName": target,
                "accessModes": [SINGLE_POD],
                "resources": {"requests": {"storage": claim.size}},
            },
        }
        if copy is not None:
            reserve(meta(copy)["name"], snap.namespace, temp)
            pvc["spec"]["volumeName"] = meta(copy)["name"]
        create(pvc)
    def bound_volume() -> str | None:
        pvc = get("pvc", temp, snap.namespace)
        if pvc and (pvc.get("status") or {}).get("phase") == "Bound":
            return spec(pvc)["volumeName"]
        return None

    pv = wait_for(f"claim {temp} to bind", bound_volume, 300)
    tag(pv, snap.id, COPY, claim.name)
    log(f"{claim.name}: copying {claim.volume} -> {pv}")
    out = run_pod(snap, f"copy {claim.name}", [("/src", claim.name, True), ("/dst", temp, False)], COPY_SCRIPT, timeout)
    log(f"{claim.name}: {out.strip().splitlines()[-1]}, verified")
    delete("pvc", temp, snap.namespace)
    reserve(pv, snap.namespace, claim.name)
    return pv


def release_volume(pv: str) -> None:
    patch("pv", pv, {
        "metadata": {"annotations": {RELEASED_AT: datetime.now(UTC).isoformat(timespec="seconds")}},
        "spec": {"persistentVolumeReclaimPolicy": "Retain"},
    })


def keep_volume(pv: str) -> None:
    """Give a volume its class's reclaim policy back, now that a claim holds it."""
    volume = get("pv", pv)
    sc = get("storageclass", spec(volume).get("storageClassName"))
    policy = (sc or {}).get("reclaimPolicy", "Delete")
    patch("pv", pv, {"metadata": {"annotations": {RELEASED_AT: None}}, "spec": {"persistentVolumeReclaimPolicy": policy}})


# ── Switching a deployment onto a set of volumes ─────────────────────────


def switch(snap: Snapshot, claims: list[Claim], volumes: dict[str, str], storage_class: str | None, timeout: float) -> None:
    """With the deployment stopped and every volume reserved for its claim:
    record the class, remove what pins the old volumes, and have the release
    claim the reserved ones."""
    if snap.storage_class != storage_class:
        set_storage_class(snap.id, storage_class)
    for sts in inspect_statefulsets(snap):
        log(f"removing StatefulSet {sts}; the release recreates it")
        delete("statefulset", sts, snap.namespace, "--cascade=orphan")
    for claim in claims:
        live = get("pvc", claim.name, snap.namespace)
        if live is not None and spec(live).get("volumeName") != volumes[claim.name]:
            release_volume(spec(live)["volumeName"])
            log(f"{claim.name}: releasing {spec(live)['volumeName']}")
            delete("pvc", claim.name, snap.namespace)
    enqueue_reconcile(snap.id)
    settle(snap.id, "re-rendering the release", timeout)
    for claim in claims:
        if claim.statefulset and get("pvc", claim.name, snap.namespace) is None:
            create_statefulset_claim(snap, claim, volumes[claim.name])
    for claim in claims:
        bound(snap.namespace, claim.name, volumes[claim.name])
    log("every claim is bound to its volume")


def inspect_statefulsets(snap: Snapshot) -> list[str]:
    return [
        meta(sts)["name"]
        for sts in items("statefulset", ns=snap.namespace)
        if spec(sts).get("volumeClaimTemplates")
    ]


def create_statefulset_claim(snap: Snapshot, claim: Claim, pv: str) -> None:
    sts = get("statefulset", claim.statefulset, snap.namespace)
    if sts is None:
        raise Fail(f"the release did not recreate StatefulSet {claim.statefulset}")
    for tmpl in spec(sts)["volumeClaimTemplates"]:
        if re.fullmatch(rf"{re.escape(meta(tmpl)['name'])}-{re.escape(claim.statefulset)}-\d+", claim.name):
            labels = {**(meta(tmpl).get("labels") or {}), **(spec(sts)["selector"].get("matchLabels") or {})}
            create({
                "apiVersion": "v1",
                "kind": "PersistentVolumeClaim",
                "metadata": {
                    "name": claim.name,
                    "namespace": snap.namespace,
                    "labels": labels,
                    "annotations": meta(tmpl).get("annotations") or {},
                },
                "spec": {**spec(tmpl), "volumeName": pv},
            })
            log(f"{claim.name}: created from StatefulSet {claim.statefulset}'s template")
            return
    raise Fail(f"StatefulSet {claim.statefulset} has no template for claim {claim.name}")


def hold(snap: Snapshot, timeout: float) -> Snapshot:
    if not snap.under_maintenance:
        with session_scope() as session:
            power.begin_maintenance(session, deployment_id=snap.id)
        log("maintenance begun")
    elif snap.status == DEPLOYMENT_STATUS_ERROR and snap.settled:
        log(f"resuming after a failed reconcile: {snap.last_error}")
        enqueue_reconcile(snap.id)
    snap = settle(snap.id, "stopping for maintenance", timeout)
    if snap.applied_state != POWER_STATE_STOPPED:
        raise Fail("the deployment is not stopped")
    return snap


def lift(snap: Snapshot, timeout: float) -> Snapshot:
    with session_scope() as session:
        power.end_maintenance(session, deployment_id=snap.id)
    log("maintenance ended")
    try:
        return settle(snap.id, "returning to its power before maintenance", timeout)
    except Fail as exc:
        raise Fail(
            f"{exc}\nThe volumes are switched and the deployment is held for maintenance again. "
            "Fix the cause, then run the same command again to finish, or rollback."
        ) from None


def quiet(snap: Snapshot, claims: list[Claim], timeout: float) -> None:
    names = {c.name for c in claims}
    wait_for(f"no pod to use {', '.join(sorted(names))}", lambda: not pods_using(snap.namespace, names), timeout)


def check_target(target: str | None) -> str:
    allowed = get_settings().storage_classes
    if target is None:
        if len(allowed) != 1:
            raise Fail(f"name the class with --to; this environment allows {allowed or 'none'}")
        target = allowed[0]
    if target not in allowed:
        raise Fail(f"{target} is not allowed in this environment ({allowed or 'none'})")
    return target


def confirm(question: str, yes: bool) -> None:
    if yes:
        return
    try:
        with open("/dev/tty") as tty:
            print(f"{question} [y/N] ", end="", flush=True)
            if tty.readline().strip().lower() not in ("y", "yes"):
                raise Fail("declined")
    except OSError:
        raise Fail("no terminal to confirm on (kubectl exec -it), or pass --yes") from None


# ── Commands ─────────────────────────────────────────────────────────────


def cmd_plan(args: argparse.Namespace) -> None:
    claims: dict[str, list[dict[str, Any]]] = {}
    for pvc in items("pvc"):
        if LABEL not in meta(pvc).get("labels", {}):
            claims.setdefault(meta(pvc)["namespace"], []).append(pvc)
    rows, claimless = [], 0
    for snap in deployments():
        if args.user and snap.owner.lower() not in args.user and str(snap.user_id) not in args.user:
            continue
        if args.product and snap.product not in args.product:
            continue
        mine = claims.get(snap.namespace, [])
        local = [c for c in mine if spec(c).get("storageClassName") == LOCAL_PATH]
        if snap.storage_class is None and not mine:
            claimless += 1
        if snap.storage_class or not local:
            continue
        power_text = snap.desired_state + (f" ({snap.reason})" if snap.reason and snap.desired_state == POWER_STATE_STOPPED else "")
        volumes = ", ".join(f"{meta(c)['name']} {spec(c)['resources']['requests']['storage']}" for c in local)
        rows.append(f"  {snap.product:<14} {snap.owner:<32} {snap.status:<8} {power_text:<22} {snap.id}\n      {volumes}")
    print(f"{len(rows)} deployment(s) with volumes on {LOCAL_PATH}:")
    print("\n".join(rows) if rows else "  none")
    if claimless:
        print(f"\n{claimless} deployment(s) without volumes record no class; migrate only records it for them.")
    left = items("pv", selector=LABEL)
    if left:
        print("\nVolumes kept by earlier runs:")
        for pv in left:
            ann = meta(pv).get("annotations", {})
            print(
                f"  {meta(pv)['name']:<42} {meta(pv)['labels'].get(ROLE):<6} {pv['status']['phase']:<9} "
                f"{meta(pv)['labels'][LABEL]} {ann.get(CLAIM)} released {ann.get(RELEASED_AT, '-')}"
            )
    print("\nStatus and plan of one deployment, changing nothing: migrate --dry-run DEPLOYMENT_ID")


def cmd_migrate(args: argparse.Namespace) -> None:
    target = check_target(args.to)
    with Lock(args.deployment):
        snap = load(args.deployment)
        log(f"deployment {snap.label}: {snap.status}, {snap.desired_state}"
            f"{f' ({snap.reason})' if snap.reason else ''}, class {snap.storage_class or 'none'}")
        if snap.storage_class not in (None, target):
            raise Fail(f"the deployment records {snap.storage_class}, not {target}")
        if snap.storage_class == target and not snap.under_maintenance:
            finish(snap, target)
            return
        copies = tagged(snap.id, COPY)
        resuming = snap.under_maintenance
        found = inspect(snap, {LOCAL_PATH} if snap.storage_class is None else {LOCAL_PATH, target}, set(copies))
        for claim in found.claims:
            where = f"{claim.live_class} {claim.volume}" if claim.live else "not created yet"
            log(f"  {claim.name}: {claim.size}, {where}"
                f"{f', StatefulSet {claim.statefulset}' if claim.statefulset else ''}")
        if found.problems:
            raise Fail("refusing:\n  " + "\n  ".join(found.problems))
        if snap.storage_class is None:
            moving = [c for c in found.moving if c.live_class == LOCAL_PATH]
        else:
            moving = [c for c in found.claims if c.name in copies or c.live_class == LOCAL_PATH]

        if not moving and not found.statefulsets:
            if args.dry_run:
                log(f"would record {target}: nothing to copy")
                return
            set_storage_class(snap.id, target)
            log("no volumes to move; new ones will be created on the new class")
            return

        if not resuming:
            for claim in moving:
                used = used_bytes(snap, claim)
                log(f"  {claim.name}: {human(used)} used of {claim.size}")
                if used > FILL_LIMIT * quantity(claim.size):
                    raise Fail(f"{claim.name} uses {human(used)}, over {FILL_LIMIT:.0%} of its {claim.size}; "
                               "grow the claim in the chart or plan first")
            if args.dry_run:
                log("dry run: would stop for maintenance, copy and switch the volumes above")
                return
            confirm(f"Stop {snap.label} and move {len(moving)} volume(s) to {target}?", args.yes)
        elif args.dry_run:
            log("dry run: an earlier run is in progress; migrate resumes it")
            return
        else:
            log("resuming an earlier run")

        snap = hold(snap, args.timeout)
        quiet(snap, found.claims, args.timeout)
        volumes: dict[str, str] = {}
        if snap.storage_class is None:
            try:
                for claim in moving:
                    volumes[claim.name] = stage(snap, claim, target, args.copy_timeout)
            except Exception:
                log("copy failed; the deployment goes back to how it was, and the copies are kept")
                lift(snap, args.timeout)
                raise
        else:
            for claim in moving:
                if claim.name not in copies:
                    raise Fail(f"class already recorded, but no copy of {claim.name}; run rollback")
                volumes[claim.name] = meta(copies[claim.name])["name"]
        switch(snap, moving, volumes, target, args.timeout)
        lift(snap, args.timeout)
        finish(load(snap.id), target)


def finish(snap: Snapshot, target: str) -> None:
    for claim, pv in tagged(snap.id, COPY).items():
        live = get("pvc", claim, snap.namespace)
        if live and spec(live).get("volumeName") == meta(pv)["name"]:
            keep_volume(meta(pv)["name"])
    log(f"done: {snap.label} is on {target}. The local-path volumes are kept; "
        "rollback restores them, cleanup deletes them")


def cmd_rollback(args: argparse.Namespace) -> None:
    with Lock(args.deployment):
        snap = load(args.deployment)
        if snap.storage_class is None and not snap.under_maintenance:
            raise Fail("the deployment records no class; nothing to roll back")
        sources = tagged(snap.id, SOURCE)
        found = inspect(snap, {LOCAL_PATH, *get_settings().storage_classes}, set(sources))
        if found.problems:
            raise Fail("refusing:\n  " + "\n  ".join(found.problems))
        claims = [c for c in found.claims if c.live is not None or c.name in sources]
        missing = [c.name for c in claims if c.name not in sources]
        if missing:
            raise Fail(f"no local-path volume to go back to for {', '.join(missing)}; created after the migration")
        log(f"rolling {snap.label} back onto {', '.join(meta(pv)['name'] for pv in sources.values())}")
        confirm("Anything written since the migration is lost. Continue?", args.yes)
        snap = hold(snap, args.timeout)
        quiet(snap, claims, args.timeout)
        volumes = {}
        for claim in claims:
            pv = meta(sources[claim.name])["name"]
            if claim.volume != pv:
                if claim.volume:
                    tag(claim.volume, snap.id, COPY, claim.name)
                reserve(pv, snap.namespace, claim.name)
            volumes[claim.name] = pv
        switch(snap, claims, volumes, None, args.timeout)
        lift(snap, args.timeout)
        for pv in volumes.values():
            keep_volume(pv)
        log(f"done: {snap.label} is back on {LOCAL_PATH}; cleanup deletes the Ceph copies")


def cmd_cleanup(args: argparse.Namespace) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=args.older_than)
    doomed = []
    for pv in items("pv", selector=LABEL):
        released = meta(pv).get("annotations", {}).get(RELEASED_AT)
        if pv["status"]["phase"] != "Released" or not released or datetime.fromisoformat(released) > cutoff:
            continue
        doomed.append(pv)
        print(f"  {meta(pv)['name']:<42} {spec(pv).get('storageClassName'):<18} "
              f"{meta(pv)['annotations'].get(CLAIM)} released {released}")
    if not doomed:
        print(f"no released volume older than {args.older_than} days")
        return
    confirm(f"Delete these {len(doomed)} volume(s) and their data?", args.yes)
    for pv in doomed:
        patch("pv", meta(pv)["name"], {"spec": {"persistentVolumeReclaimPolicy": "Delete"}})
        log(f"deleting {meta(pv)['name']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="migrate-storage.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="list deployments with volumes on local-path, and kept volumes")
    plan.add_argument("-u", "--user", action="append", type=str.lower, help="owner email or id (repeatable)")
    plan.add_argument("-p", "--product", action="append", help="product slug (repeatable)")

    for name, help_text in (
        ("migrate", "move one deployment's volumes onto the environment's Ceph class"),
        ("rollback", "put a migrated deployment back on its kept local-path volumes"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("deployment", type=UUID)
        p.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
        p.add_argument("--timeout", type=float, default=1200, help="seconds to wait for each reconcile")
        if name == "migrate":
            p.add_argument("--to", help="target class; defaults to the only one the environment allows")
            p.add_argument("--dry-run", action="store_true", help="check and measure, change nothing")
            p.add_argument("--copy-timeout", type=float, default=7200, help="seconds to allow each copy")

    cleanup = sub.add_parser("cleanup", help="delete volumes runs released longer ago than --older-than")
    cleanup.add_argument("--older-than", type=float, default=14, help="days (default 14)")
    cleanup.add_argument("-y", "--yes", action="store_true")

    args = parser.parse_args(argv)
    try:
        {"plan": cmd_plan, "migrate": cmd_migrate, "rollback": cmd_rollback, "cleanup": cmd_cleanup}[args.command](args)
    except (Fail, CaelusException) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
