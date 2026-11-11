"""Vars through the deployment create/update path, and what reads report.

The design's rule for this path is that vars are *desired state*: they are
recorded whether or not the rollout that carries them succeeds, exactly as
`user_values_json` already is, and each release freezes what it was created
with.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlmodel import select

from app.models import DeploymentORM, DeploymentReconcileJobORM, DeploymentVarORM
from app.services import vars as vars_service
from app.services.jobs import JobService
from app.services.reconcile_constants import DEPLOYMENT_STATUS_READY
from tests.conftest import (  # noqa: F401
    USER_AUTH_HEADER,
    client,
    create_free_plan_template,
    create_user,
    db_session,
)

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "host": {"type": "string", "title": "hostname"},
        "LOG_LEVEL": {"type": "string", "x-caelus-target": "runtime"},
        "ADMIN_TOKEN": {
            "type": "string",
            "x-caelus-target": "runtime",
            "x-caelus-sensitive": True,
        },
    },
    "required": ["host"],
}

SECRET = "hunter2-swordfish"


@pytest.fixture
def project(client, db_session):
    """A user, a product with a vars-declaring template, and a free plan."""
    user_id = create_user(client, "lifecycle@example.com")["id"]
    product_id = client.post(
        "/api/products", json={"name": "vaultish", "description": "d"}
    ).json()["id"]
    template_id = client.post(
        f"/api/products/{product_id}/templates",
        json={
            "chart_ref": "registry.home/vaultish/",
            "chart_version": "1.0.0",
            "values_schema_json": SCHEMA,
        },
    ).json()["id"]
    client.put(f"/api/products/{product_id}", json={"template_id": template_id})
    plan_template_id = create_free_plan_template(db_session, product_id)
    return {
        "client": client,
        "session": db_session,
        "user_id": user_id,
        "product_id": product_id,
        "template_id": template_id,
        "plan_template_id": plan_template_id,
    }


def _create(project, *, vars=None, host="vault.example.test"):
    body = {
        "desired_template_id": project["template_id"],
        "plan_template_id": project["plan_template_id"],
        "user_values_json": {"host": host},
    }
    if vars is not None:
        body["vars"] = vars
    response = project["client"].post(
        f"/api/users/{project['user_id']}/deployments", json=body
    )
    return response


def _ready(project, deployment_id):
    """Finish the create job the way the reconciler would, and apply it."""
    deployment_id = UUID(deployment_id) if isinstance(deployment_id, str) else deployment_id
    session = project["session"]
    job = session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == deployment_id,
            DeploymentReconcileJobORM.reason == "create",
        )
    ).one()
    JobService(session).mark_job_done(job_id=job.id)
    deployment = session.get(DeploymentORM, deployment_id)
    deployment.status = DEPLOYMENT_STATUS_READY
    deployment.applied_release_id = deployment.desired_release_id
    session.add(deployment)
    session.commit()
    return deployment


def _update(project, deployment_id, **body):
    return project["client"].put(
        f"/api/users/{project['user_id']}/deployments/{deployment_id}",
        json={"desired_template_id": project["template_id"], **body},
    )


def _rows(project, deployment_id):
    return project["session"].exec(
        select(DeploymentVarORM)
        .where(DeploymentVarORM.deployment_id == UUID(str(deployment_id)))
        .order_by(DeploymentVarORM.id)
    ).all()


# ── Create ────────────────────────────────────────────────────────────────


def test_creating_with_vars_gives_the_first_release_a_non_empty_snapshot(project):
    response = _create(
        project,
        vars={"LOG_LEVEL": {"value": "debug"}, "ADMIN_TOKEN": {"value": SECRET}},
    )
    assert response.status_code == 201, response.text
    deployment = response.json()["deployment"]

    session = project["session"]
    row = session.get(DeploymentORM, UUID(deployment["id"]))
    snapshot = vars_service.read_snapshot(session, row.desired_release_id)
    assert set(snapshot) == {"LOG_LEVEL", "ADMIN_TOKEN"}
    # The very first release rolls out with the environment it was asked for,
    # rather than an empty one to be fixed up by a second deploy.
    assert snapshot["LOG_LEVEL"].value == "debug"


def test_the_create_response_reports_head_and_never_the_submitted_secret(project):
    response = _create(project, vars={"ADMIN_TOKEN": {"value": SECRET}})
    assert SECRET not in response.text
    entry = response.json()["deployment"]["vars"]["ADMIN_TOKEN"]
    assert entry["sensitive"] is True
    assert "value" not in entry


def test_creating_without_vars_stores_none(project):
    response = _create(project)
    assert response.status_code == 201
    assert response.json()["deployment"]["vars"] == {}
    assert _rows(project, response.json()["deployment"]["id"]) == []


def test_a_rejected_var_fails_the_whole_create(project):
    response = _create(project, vars={"PORT": {"value": "8080"}})
    assert response.status_code == 400
    assert project["session"].exec(select(DeploymentORM)).all() == []


# ── Update ────────────────────────────────────────────────────────────────


def test_an_update_omitting_vars_leaves_head_intact_and_is_captured(project):
    created = _create(project, vars={"LOG_LEVEL": {"value": "debug"}}).json()["deployment"]
    _ready(project, created["id"])

    response = _update(project, created["id"], user_values_json={"host": "vault.example.test"})

    assert response.status_code == 200, response.text
    assert set(response.json()["vars"]) == {"LOG_LEVEL"}
    assert len(_rows(project, created["id"])) == 1

    session = project["session"]
    deployment = session.get(DeploymentORM, UUID(created["id"]))
    snapshot = vars_service.read_snapshot(session, deployment.desired_release_id)
    assert snapshot["LOG_LEVEL"].value == "debug"


def test_an_update_merges_vars_rather_than_replacing_them(project):
    created = _create(
        project, vars={"LOG_LEVEL": {"value": "debug"}, "ADMIN_TOKEN": {"value": SECRET}}
    ).json()["deployment"]
    _ready(project, created["id"])

    response = _update(project, created["id"], vars={"LOG_LEVEL": {"value": "info"}})

    assert set(response.json()["vars"]) == {"LOG_LEVEL", "ADMIN_TOKEN"}
    assert response.json()["vars"]["LOG_LEVEL"]["value"] == "info"


def test_a_redeploy_submitting_head_verbatim_writes_no_new_rows(project):
    created = _create(project, vars={"LOG_LEVEL": {"value": "debug"}}).json()["deployment"]
    _ready(project, created["id"])
    before = [row.id for row in _rows(project, created["id"])]

    response = _update(project, created["id"], vars={"LOG_LEVEL": {"value": "debug"}})

    assert response.status_code == 200
    assert [row.id for row in _rows(project, created["id"])] == before


def test_update_never_derives_vars_from_user_values_json(project):
    """design.md D3, asserted because the failure mode is silent.

    A runtime property submitted as a chart value is rejected by the chart
    projection -- it is never quietly re-routed into the vars store.
    """
    created = _create(project).json()["deployment"]
    _ready(project, created["id"])

    response = _update(
        project,
        created["id"],
        user_values_json={"host": "vault.example.test", "LOG_LEVEL": "debug"},
    )

    assert response.status_code == 409, response.text
    assert _rows(project, created["id"]) == []

    # And a legal update writes chart values only.
    ok = _update(project, created["id"], user_values_json={"host": "other.example.test"})
    assert ok.status_code == 200
    assert _rows(project, created["id"]) == []
    assert ok.json()["vars"] == {}


def test_a_failed_rollout_leaves_head_and_reports_pending(project):
    """design.md D9: vars are desired state, including after a failure."""
    created = _create(project, vars={"LOG_LEVEL": {"value": "debug"}}).json()["deployment"]
    deployment = _ready(project, created["id"])
    session = project["session"]

    _update(project, created["id"], vars={"LOG_LEVEL": {"value": "trace"}})

    # The rollout never succeeded, so `applied_release_id` still names the
    # release before it -- which is exactly the state `pending` must catch.
    deployment = session.get(DeploymentORM, UUID(created["id"]))
    assert deployment.applied_release_id != deployment.desired_release_id

    read = project["client"].get(
        f"/api/users/{project['user_id']}/deployments/{created['id']}"
    ).json()
    assert read["vars"]["LOG_LEVEL"]["value"] == "trace"
    assert read["pending"] is True


# ── Read models ───────────────────────────────────────────────────────────


def test_a_deployment_read_reports_head_not_the_applied_snapshot(project):
    created = _create(project, vars={"LOG_LEVEL": {"value": "debug"}}).json()["deployment"]
    _ready(project, created["id"])
    url = f"/api/users/{project['user_id']}/deployments/{created['id']}"

    assert project["client"].get(url).json()["pending"] is False

    # Stage a change without deploying it.
    project["client"].patch(
        f"{url}/vars/runtime", json={"vars": {"LOG_LEVEL": {"value": "trace"}}}
    )

    read = project["client"].get(url).json()
    assert read["vars"]["LOG_LEVEL"]["value"] == "trace"
    assert read["pending"] is True
    # ...while the applied release still reports what it shipped.
    session = project["session"]
    applied = session.get(DeploymentORM, UUID(created["id"])).applied_release_id
    assert vars_service.read_snapshot(session, applied)["LOG_LEVEL"].value == "debug"


def test_a_release_read_reports_its_own_snapshot_after_head_moves(project):
    created = _create(project, vars={"LOG_LEVEL": {"value": "debug"}}).json()["deployment"]
    _ready(project, created["id"])
    base = f"/api/users/{project['user_id']}/deployments/{created['id']}"

    project["client"].patch(
        f"{base}/vars/runtime", json={"vars": {"LOG_LEVEL": {"value": "trace"}}}
    )

    release = project["client"].get(f"{base}/releases/1").json()
    assert release["vars"]["LOG_LEVEL"]["value"] == "debug"
    assert project["client"].get(base).json()["vars"]["LOG_LEVEL"]["value"] == "trace"


def test_a_release_read_omits_a_sensitive_value(project):
    created = _create(project, vars={"ADMIN_TOKEN": {"value": SECRET}}).json()["deployment"]
    base = f"/api/users/{project['user_id']}/deployments/{created['id']}"

    response = project["client"].get(f"{base}/releases/1")

    assert SECRET not in response.text
    assert "value" not in response.json()["vars"]["ADMIN_TOKEN"]


def test_the_deployment_list_carries_no_vars_and_queries_none(project):
    """Head is a query per deployment; a listing must not fan out into them."""
    from sqlalchemy import event

    _create(project, vars={"LOG_LEVEL": {"value": "debug"}})
    _create(project, vars={"LOG_LEVEL": {"value": "info"}}, host="two.example.test")

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = project["session"].get_bind()
    event.listen(engine, "after_cursor_execute", record)
    try:
        listed = project["client"].get(f"/api/users/{project['user_id']}/deployments").json()
    finally:
        event.remove(engine, "after_cursor_execute", record)

    assert len(listed) == 2
    for entry in listed:
        assert entry["vars"] is None
        assert entry["pending"] is None
    assert [s for s in statements if "deployment_var" in s] == []


def test_the_release_list_carries_no_vars(project):
    created = _create(project, vars={"LOG_LEVEL": {"value": "debug"}}).json()["deployment"]
    base = f"/api/users/{project['user_id']}/deployments/{created['id']}"

    listed = project["client"].get(f"{base}/releases").json()

    assert [entry["vars"] for entry in listed] == [None]
    # The single read does report it.
    assert project["client"].get(f"{base}/releases/1").json()["vars"] != {}


# ── Storage class (openspec deployment-storage-class) ─────────────────────


def _settle(project, deployment_id):
    session = project["session"]
    deployment_id = UUID(str(deployment_id))
    jobs = JobService(session)
    for job in session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == deployment_id,
            DeploymentReconcileJobORM.status.in_(("queued", "running")),
        )
    ).all():
        jobs.mark_job_done(job_id=job.id)
    deployment = session.get(DeploymentORM, deployment_id)
    deployment.status = DEPLOYMENT_STATUS_READY
    deployment.applied_release_id = deployment.desired_release_id
    session.add(deployment)
    session.commit()


def test_a_recorded_storage_class_survives_every_change(project, monkeypatch):
    from app.config import get_settings
    from app.models import UserORM

    settings = get_settings().model_copy(update={"storage_classes": ["ceph-freepod"]})
    monkeypatch.setattr("app.services.deployments.get_settings", lambda: settings)
    session = project["session"]
    owner = session.get(UserORM, project["user_id"])
    owner.storage_class = "ceph-freepod"
    session.add(owner)
    session.commit()

    client = project["client"]
    created = _create(project).json()["deployment"]
    dep_id = created["id"]
    url = f"/api/users/{project['user_id']}/deployments/{dep_id}"
    _ready(project, dep_id)

    def recorded():
        session.expire_all()
        return session.get(DeploymentORM, UUID(dep_id)).storage_class

    assert client.patch(f"{url}/vars/runtime", json={"vars": {"LOG_LEVEL": {"value": "trace"}}}).status_code == 200
    assert recorded() == "ceph-freepod"

    assert _update(project, dep_id, user_values_json={"host": "vault.example.test"}).status_code == 200
    assert recorded() == "ceph-freepod"
    _settle(project, dep_id)

    moved_to = client.post(
        f"/api/products/{project['product_id']}/templates",
        json={"chart_ref": "registry.home/vaultish/", "chart_version": "1.0.1", "values_schema_json": SCHEMA},
    ).json()["id"]
    client.put(f"/api/products/{project['product_id']}", json={"template_id": moved_to})
    moved = client.put(url, json={"desired_template_id": moved_to, "user_values_json": {"host": "vault.example.test"}})
    assert moved.status_code == 200
    assert recorded() == "ceph-freepod"
    _settle(project, dep_id)

    assert client.post(f"{url}/stop").status_code == 200
    assert recorded() == "ceph-freepod"
    _settle(project, dep_id)
    assert client.post(f"{url}/start").status_code == 200
    assert recorded() == "ceph-freepod"

    assert "storage_class" not in client.get(url).json()
