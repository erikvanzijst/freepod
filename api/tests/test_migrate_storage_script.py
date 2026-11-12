"""`api/bin/migrate-storage.py` against a fake cluster: which claims it moves,
what it refuses, and the order of a switch (migrate-deployment-storage D3)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "migrate-storage.py"


@pytest.fixture(scope="module")
def ms():
    spec = importlib.util.spec_from_file_location("migrate_storage", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules[spec.name]


def _pvc(name, cls="local-path", volume=None, phase="Bound", labels=None):
    return {
        "metadata": {"name": name, "labels": labels or {}},
        "spec": {"storageClassName": cls, "volumeName": volume or f"pv-{name}", "resources": {"requests": {"storage": "1Gi"}}},
        "status": {"phase": phase},
    }


def _helm_pvc(name, size="2Gi"):
    return {"kind": "PersistentVolumeClaim", "metadata": {"name": name}, "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": size}}}}


def _sts(name, template, size="8Gi"):
    return {
        "kind": "StatefulSet",
        "metadata": {"name": name},
        "spec": {
            "replicas": 1,
            "volumeClaimTemplates": [{"metadata": {"name": template}, "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": size}}}}],
        },
    }


def _deployment(name, claim):
    return {
        "kind": "Deployment",
        "metadata": {"name": name},
        "spec": {
            "strategy": {"type": "Recreate"},
            "template": {"spec": {"containers": [{"name": "c"}], "volumes": [{"name": "d", "persistentVolumeClaim": {"claimName": claim}}]}},
        },
    }


@pytest.fixture
def snap(ms):
    return SimpleNamespace(id=uuid4(), namespace="ns", release="app", storage_class=None)


@pytest.fixture
def cluster(ms, monkeypatch):
    state = SimpleNamespace(docs=[], pvcs=[], statefulsets={})
    monkeypatch.setattr(ms, "render", lambda snap, plan=None: state.docs)
    monkeypatch.setattr(ms, "items", lambda kind, **_: list(state.pvcs) if kind == "pvc" else [])
    monkeypatch.setattr(ms, "get", lambda kind, name, ns=None: state.statefulsets.get(name) if kind == "statefulset" else None)
    return state


def test_quantities(ms):
    assert ms.quantity("1Gi") == 2**30
    assert ms.quantity("500Mi") == 500 * 2**20
    assert ms.quantity("2G") == 2 * 10**9
    assert ms.quantity("1.5Gi") == int(1.5 * 2**30)
    with pytest.raises(ms.Fail):
        ms.quantity("lots")


def test_claims_are_sized_from_the_render_and_owned_by_helm_or_a_statefulset(ms, cluster, snap):
    cluster.docs = [_helm_pvc("data"), _deployment("web", "data"), _sts("db", "pg")]
    cluster.pvcs = [_pvc("data"), _pvc("pg-db-0"), _pvc("data-migrate", labels={ms.LABEL: "x"})]
    found = ms.inspect(snap, {"local-path"})
    assert found.problems == []
    assert [(c.name, c.size, c.statefulset) for c in found.claims] == [("data", "2Gi", None), ("pg-db-0", "8Gi", "db")]
    assert found.statefulsets == ["db"]


def test_a_rendered_claim_not_created_yet_has_nothing_to_move(ms, cluster, snap):
    cluster.docs = [_helm_pvc("new"), _deployment("web", "new")]
    found = ms.inspect(snap, {"local-path"})
    assert [c.name for c in found.claims] == ["new"]
    assert found.moving == []


def test_a_claim_an_earlier_run_removed_still_counts(ms, cluster, snap):
    cluster.docs = [_sts("db", "pg")]
    found = ms.inspect(snap, {"local-path"}, {"pg-db-0"})
    assert [(c.name, c.live) for c in found.claims] == [("pg-db-0", None)]


@pytest.mark.parametrize(
    "docs, pvcs, statefulsets, problem",
    [
        ([], [_pvc("stray")], {}, "not rendered by the release"),
        ([_helm_pvc("data"), _deployment("web", "data")], [_pvc("data", cls="nfs")], {}, "on nfs"),
        ([_helm_pvc("data"), _deployment("web", "data")], [_pvc("data", phase="Pending")], {}, "not bound"),
        (
            [_helm_pvc("data"), {**_deployment("web", "data"), "spec": {**_deployment("web", "data")["spec"], "strategy": {}}}],
            [_pvc("data")], {}, "cannot be single-pod",
        ),
        (
            [_sts("db", "pg")], [_pvc("pg-db-0")],
            {"db": {"metadata": {"name": "db"}, "spec": {"persistentVolumeClaimRetentionPolicy": {"whenDeleted": "Delete"}}}},
            "deletes its claims",
        ),
    ],
    ids=["stray", "foreign class", "unbound", "rolling", "retention"],
)
def test_refusals(ms, cluster, snap, docs, pvcs, statefulsets, problem):
    cluster.docs, cluster.pvcs, cluster.statefulsets = docs, pvcs, statefulsets
    found = ms.inspect(snap, {"local-path"})
    assert any(problem in p for p in found.problems), found.problems


def test_switch_records_the_class_before_releasing_anything(ms, monkeypatch, snap):
    calls = []
    live = {"data": _pvc("data", volume="old-data"), "pg-db-0": _pvc("pg-db-0", volume="old-pg")}
    sts = _sts("db", "pg")
    sts["spec"]["selector"] = {"matchLabels": {"app": "db"}}
    created = {}

    def get(kind, name, ns=None):
        if kind == "pvc":
            return created.get(name) or live.get(name)
        return sts if kind == "statefulset" else None

    def delete(kind, name, ns, *extra):
        calls.append(("delete", kind, name, *extra))
        live.pop(name, None)

    def create(obj):
        calls.append(("create", obj["kind"], obj["metadata"]["name"], obj["spec"]["volumeName"]))
        created[obj["metadata"]["name"]] = {**obj, "status": {"phase": "Bound"}}

    monkeypatch.setattr(ms, "get", get)
    monkeypatch.setattr(ms, "delete", delete)
    monkeypatch.setattr(ms, "create", create)
    monkeypatch.setattr(ms, "items", lambda kind, **_: [sts] if kind == "statefulset" else [])
    monkeypatch.setattr(ms, "patch", lambda kind, name, body, ns=None: calls.append(("patch", kind, name)))
    monkeypatch.setattr(ms, "set_storage_class", lambda _id, cls: calls.append(("class", cls)))
    monkeypatch.setattr(ms, "enqueue_reconcile", lambda _id: calls.append(("reconcile",)))

    def settle(_id, what, timeout):
        calls.append(("settled",))
        live["data"] = _pvc("data", volume="new-data")

    monkeypatch.setattr(ms, "settle", settle)
    claims = [ms.Claim("data", "1Gi", None, live["data"]), ms.Claim("pg-db-0", "8Gi", "db", live["pg-db-0"])]

    ms.switch(snap, claims, {"data": "new-data", "pg-db-0": "new-pg"}, "ceph", 5)

    assert calls == [
        ("class", "ceph"),
        ("delete", "statefulset", "db", "--cascade=orphan"),
        ("patch", "pv", "old-data"),
        ("delete", "pvc", "data", "--timeout=120s"),
        ("patch", "pv", "old-pg"),
        ("delete", "pvc", "pg-db-0", "--timeout=120s"),
        ("reconcile",),
        ("settled",),
        ("create", "PersistentVolumeClaim", "pg-db-0", "new-pg"),
    ]
    assert created["pg-db-0"]["metadata"]["labels"] == {"app": "db"}


def test_switch_moves_the_plan_once_the_old_claims_are_gone(ms, monkeypatch, snap):
    calls = []
    live = {"data": _pvc("data", volume="old-data")}
    monkeypatch.setattr(ms, "get", lambda kind, name, ns=None: live.get(name) if kind == "pvc" else None)
    monkeypatch.setattr(ms, "delete", lambda kind, name, ns, *extra: (calls.append(("delete", kind, name)), live.pop(name, None)))
    monkeypatch.setattr(ms, "items", lambda kind, **_: [])
    monkeypatch.setattr(ms, "patch", lambda *a, **k: None)
    monkeypatch.setattr(ms, "set_storage_class", lambda *a: None)
    monkeypatch.setattr(ms, "set_plan_template", lambda _id, tv: calls.append(("plan", tv)))
    monkeypatch.setattr(ms, "enqueue_reconcile", lambda _id: calls.append(("reconcile",)))
    monkeypatch.setattr(ms, "settle", lambda *a: live.update(data=_pvc("data", volume="new-data")))

    ms.switch(snap, [ms.Claim("data", "10Gi", None, live["data"])], {"data": "new-data"}, "ceph", 5, 44)

    assert calls == [("delete", "pvc", "data"), ("plan", 44), ("reconcile",)]


def test_switch_keeps_a_claim_already_on_its_volume(ms, monkeypatch, snap):
    calls = []
    live = {"data": _pvc("data", volume="new-data")}
    monkeypatch.setattr(ms, "get", lambda kind, name, ns=None: live.get(name) if kind == "pvc" else None)
    monkeypatch.setattr(ms, "delete", lambda *a: calls.append(("delete", *a)))
    monkeypatch.setattr(ms, "items", lambda kind, **_: [])
    monkeypatch.setattr(ms, "set_storage_class", lambda *a: calls.append(("class",)))
    monkeypatch.setattr(ms, "enqueue_reconcile", lambda _id: calls.append(("reconcile",)))
    monkeypatch.setattr(ms, "settle", lambda *a: None)
    snap.storage_class = "ceph"

    ms.switch(snap, [ms.Claim("data", "1Gi", None, live["data"])], {"data": "new-data"}, "ceph", 5)

    assert calls == [("reconcile",)]


def _pod(name, phase, claim):
    return {
        "metadata": {"name": name},
        "spec": {"volumes": [{"name": "v", "persistentVolumeClaim": {"claimName": claim}}]},
        "status": {"phase": phase},
    }


def test_quiet_deletes_finished_pods_that_name_a_claim(ms, monkeypatch, snap):
    pods = [
        _pod("done", "Succeeded", "data"),
        _pod("crashed", "Failed", "data"),
        _pod("other", "Succeeded", "unrelated"),
    ]
    deleted = []
    monkeypatch.setattr(ms, "items", lambda kind, **_: list(pods) if kind == "pod" else [])
    monkeypatch.setattr(ms, "delete", lambda kind, name, ns, *extra: deleted.append((kind, name)))

    ms.quiet(snap, [ms.Claim("data", "1Gi", None, None)], 5)

    assert deleted == [("pod", "done"), ("pod", "crashed")]


def test_quiet_waits_for_a_live_pod(ms, monkeypatch, snap):
    pods = [_pod("app", "Running", "data")]
    monkeypatch.setattr(ms, "items", lambda kind, **_: list(pods))
    monkeypatch.setattr(ms, "POLL", 0)
    with pytest.raises(ms.Fail, match="no pod to use data"):
        ms.quiet(snap, [ms.Claim("data", "1Gi", None, None)], 0)


def _pv(name, deployment, phase, released=None):
    annotations = {"caelus.dev/migration-claim": "data"}
    if released:
        annotations["caelus.dev/migration-released-at"] = released
    return {
        "metadata": {"name": name, "labels": {"caelus.dev/migration": deployment}, "annotations": annotations},
        "spec": {"storageClassName": "local-path"},
        "status": {"phase": phase},
    }


def test_kept_volumes_are_this_environments_and_unclaimed(ms, monkeypatch):
    mine, theirs = str(uuid4()), str(uuid4())
    volumes = [
        _pv("old", mine, "Released", "2026-11-01T00:00:00+00:00"),
        _pv("live-copy", mine, "Bound"),
        _pv("reserved-copy", mine, "Available"),
        _pv("other-env", theirs, "Released", "2026-11-01T00:00:00+00:00"),
    ]
    monkeypatch.setattr(ms, "items", lambda kind, **_: list(volumes))
    monkeypatch.setattr(ms, "known_ids", lambda: {mine})

    assert [v["metadata"]["name"] for v in ms.kept()] == ["old", "reserved-copy"]
    assert [v["metadata"]["name"] for v in ms.kept(ms.UUID(mine))] == ["old", "reserved-copy"]
    with pytest.raises(ms.Fail, match="in this environment"):
        ms.kept(ms.UUID(theirs))


def test_only_released_volumes_past_the_cutoff_expire(ms):
    from datetime import datetime, UTC

    volumes = [
        _pv("old", "d", "Released", "2026-11-01T00:00:00+00:00"),
        _pv("recent", "d", "Released", "2026-11-12T00:00:00+00:00"),
        _pv("reserved", "d", "Available"),
        _pv("unstamped", "d", "Released"),
    ]
    expired = ms.expired(volumes, datetime(2026, 11, 5, tzinfo=UTC))
    assert [v["metadata"]["name"] for v in expired] == ["old"]


def test_the_target_defaults_to_the_only_allowed_class(ms, monkeypatch):
    monkeypatch.setattr(ms, "get_settings", lambda: SimpleNamespace(storage_classes=["ceph-freepod-dev"]))
    assert ms.check_target(None) == "ceph-freepod-dev"
    with pytest.raises(ms.Fail, match="not allowed"):
        ms.check_target("ceph-freepod")
    monkeypatch.setattr(ms, "get_settings", lambda: SimpleNamespace(storage_classes=[]))
    with pytest.raises(ms.Fail, match="--to"):
        ms.check_target(None)


def test_render_uses_the_plan_the_next_reconcile_applies(ms, monkeypatch):
    import json

    rendered = []

    def run(cmd, **_):
        if cmd[:3] == ["helm", "get", "values"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps({"caelus": {"plan": {"storageSize": "1Gi"}, "releaseId": "r"}}))
        rendered.append(json.loads(Path(cmd[cmd.index("-f") + 1]).read_text()))
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(ms, "run", run)
    snap = SimpleNamespace(release="app", namespace="ns", chart_ref="oci://c", chart_digest="sha256:x", chart_version="1", plan=None)
    ms.render(snap)
    snap.plan = {"storageSize": "5Gi"}
    ms.render(snap)
    ms.render(snap, {"storageSize": "10Gi"})

    assert [v["caelus"]["plan"] for v in rendered] == [{"storageSize": "1Gi"}, {"storageSize": "5Gi"}, {"storageSize": "10Gi"}]
    assert all(v["caelus"]["releaseId"] == "r" for v in rendered)


@pytest.fixture
def plans(ms, monkeypatch):
    templates = {
        27: SimpleNamespace(id=27, plan_id=2, price_cents=0, billing_interval="monthly", storage_bytes=2**30, deleted_at=None),
        44: SimpleNamespace(id=44, plan_id=2, price_cents=0, billing_interval="monthly", storage_bytes=10 * 2**30, deleted_at=None),
        45: SimpleNamespace(id=45, plan_id=14, price_cents=0, billing_interval="monthly", storage_bytes=10 * 2**30, deleted_at=None),
        46: SimpleNamespace(id=46, plan_id=2, price_cents=500, billing_interval="monthly", storage_bytes=10 * 2**30, deleted_at=None),
    }

    class Session:
        def get(self, _model, key):
            return templates.get(key)

    class Scope:
        def __enter__(self):
            return Session()

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(ms, "session_scope", Scope)
    return SimpleNamespace(plan_template_id=27)


def test_a_plan_change_stays_within_the_plan_and_its_price(ms, plans):
    assert ms.plan_change(plans, None) is None
    assert ms.plan_change(plans, 27) is None
    assert ms.plan_change(plans, 44) == {"storageBytes": 10 * 2**30, "storageSize": "10Gi"}
    with pytest.raises(ms.Fail, match="belongs to plan 14"):
        ms.plan_change(plans, 45)
    with pytest.raises(ms.Fail, match="another price"):
        ms.plan_change(plans, 46)
    with pytest.raises(ms.Fail, match="no plan template 99"):
        ms.plan_change(plans, 99)


def test_rollback_records_a_local_volume_as_big_as_its_grown_claim(ms, monkeypatch):
    patched = []
    monkeypatch.setattr(ms, "patch", lambda kind, name, body, ns=None: patched.append((name, body)))
    pv = {"metadata": {"name": "old"}, "spec": {"capacity": {"storage": "1Gi"}}}

    ms.fit(pv, ms.Claim("data", "10Gi", None, None))
    ms.fit(pv, ms.Claim("data", "512Mi", None, None))

    assert patched == [("old", {"spec": {"capacity": {"storage": "10Gi"}}})]
