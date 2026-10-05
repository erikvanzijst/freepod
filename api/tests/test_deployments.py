from uuid import UUID

from app.services.reconcile_constants import (
    DEPLOYMENT_STATUS_PROVISIONING,
    DEPLOYMENT_STATUS_DELETING,
    DEPLOYMENT_STATUS_DELETED,
    DEPLOYMENT_STATUS_READY,
)
from tests.conftest import client, db_session, user_client, USER_AUTH_HEADER
from tests.conftest import create_free_plan_template, create_user
from sqlmodel import select

from app.models import DeploymentORM, DeploymentReconcileJobORM, UserORM
from app.services.jobs import JobService


def _finish_create_job(db_session, deployment_id):
    """Mark the create job as done and set deployment to ready (simulates reconciler)."""
    deployment_id = UUID(deployment_id) if isinstance(deployment_id, str) else deployment_id
    create_job = db_session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == deployment_id,
            DeploymentReconcileJobORM.reason == "create",
        )
    ).one()
    JobService(db_session).mark_job_done(job_id=create_job.id)
    deployment = db_session.get(DeploymentORM, deployment_id)
    deployment.status = DEPLOYMENT_STATUS_READY
    db_session.add(deployment)
    db_session.commit()


def test_delete_deployment_flow(client, db_session):
    # Setup: create user, product, template, deployment
    user_id = create_user(client, "deldep@example.com")["id"]

    product_resp = client.post(
        "/api/products", json={"name": "nextcloud", "description": "Nextcloud app"}
    )
    assert product_resp.status_code == 201
    product_id = product_resp.json()["id"]

    template_resp = client.post(
        f"/api/products/{product_id}/templates",
        json={
            "chart_ref": "registry.home/nextcloud/",
            "chart_version": "1.0.0",
            "values_schema_json": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ingress": {
                        "type": "object",
                        "properties": {"host": {"type": "string", "title": "hostname"}},
                    }
                },
            },
        },
    )
    assert template_resp.status_code == 201
    template_id = template_resp.json()["id"]

    # Make it the canonical template
    client.put(f"/api/products/{product_id}", json={"template_id": template_id})

    ptv_id = create_free_plan_template(db_session, product_id)

    deployment_resp = client.post(
        f"/api/users/{user_id}/deployments",
        json={"desired_template_id": template_id, "user_values_json": {"ingress": {"host": "cloud.example.com"}}, "plan_template_id": ptv_id},
    )
    assert deployment_resp.status_code == 201
    deployment_id = UUID(deployment_resp.json()["deployment"]["id"])
    assert deployment_resp.json()["deployment"]["status"] == DEPLOYMENT_STATUS_PROVISIONING
    assert deployment_resp.json()["deployment"]["generation"] == 1
    create_jobs = db_session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == deployment_id,
            DeploymentReconcileJobORM.reason == "create",
        )
    ).all()
    assert len(create_jobs) == 1
    JobService(db_session).mark_job_done(job_id=create_jobs[0].id)

    # Delete the deployment
    del_resp = client.delete(f"/api/users/{user_id}/deployments/{deployment_id}")
    assert del_resp.status_code == 204
    deleted = db_session.get(DeploymentORM, deployment_id)
    assert deleted is not None
    assert deleted.status == DEPLOYMENT_STATUS_DELETING
    delete_jobs = db_session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == deployment_id,
            DeploymentReconcileJobORM.reason == "delete",
        )
    ).all()
    assert len(delete_jobs) == 1

    # Verify its status is "deleting"
    list_resp = client.get(f"/api/users/{user_id}/deployments")
    assert list_resp.status_code == 200
    deleting_dep = next(filter(lambda d: d["id"] == str(deployment_id), list_resp.json()))
    assert deleting_dep.get("status") == DEPLOYMENT_STATUS_DELETING

    # Deleting a non‑existent deployment should return 404
    not_found_resp = client.delete(f"/api/users/{user_id}/deployments/00000000-0000-0000-0000-000000000000")
    assert not_found_resp.status_code == 404

    # Re-deleting an already deleted/deleting deployment should be idempotent
    resp = client.delete(f"/api/users/{user_id}/deployments/{deleted.id}")
    assert resp.status_code == 204


def test_upgrade_deployment_endpoint_sets_state_and_enqueues_job(client, db_session):
    user_id = create_user(client, "upgrade-api@example.com")["id"]

    product_resp = client.post(
        "/api/products", json={"name": "upgrade-api-prod", "description": "desc"}
    )
    assert product_resp.status_code == 201
    product_id = product_resp.json()["id"]

    tmpl1_resp = client.post(
        f"/api/products/{product_id}/templates",
        json={
            "chart_ref": "oci://example/chart",
            "chart_version": "1.0.0",
            "values_schema_json": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "user": {
                        "type": "object",
                        "properties": {"domain": {"type": "string", "title": "hostname"}},
                    }
                },
            },
        },
    )
    assert tmpl1_resp.status_code == 201
    tmpl1_id = tmpl1_resp.json()["id"]

    # Make it the canonical template
    client.put(f"/api/products/{product_id}", json={"template_id": tmpl1_id})

    tmpl2_resp = client.post(
        f"/api/products/{product_id}/templates",
        json={
            "chart_ref": "oci://example/chart",
            "chart_version": "2.0.0",
            "values_schema_json": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "user": {
                        "type": "object",
                        "properties": {"domain": {"type": "string", "title": "hostname"}},
                    }
                },
            },
        },
    )
    assert tmpl2_resp.status_code == 201
    tmpl2_id = tmpl2_resp.json()["id"]

    ptv_id = create_free_plan_template(db_session, product_id)

    dep_resp = client.post(
        f"/api/users/{user_id}/deployments",
        json={
            "desired_template_id": tmpl1_id,
            "user_values_json": {"user": {"domain": "upgrade-api.example.test"}},
            "plan_template_id": ptv_id,
        },
    )
    assert dep_resp.status_code == 201
    dep_id = dep_resp.json()["deployment"]["id"]
    _finish_create_job(db_session, dep_id)

    upgrade_resp = client.put(
        f"/api/users/{user_id}/deployments/{dep_id}",
        json={"desired_template_id": tmpl2_id},
    )
    assert upgrade_resp.status_code == 200
    assert upgrade_resp.json()["status"] == DEPLOYMENT_STATUS_PROVISIONING
    assert upgrade_resp.json()["desired_template_id"] == tmpl2_id
    assert upgrade_resp.json()["generation"] == 2

    update_jobs = db_session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == UUID(dep_id),
            DeploymentReconcileJobORM.reason == "update",
        )
    ).all()
    assert len(update_jobs) == 1


def test_create_deployment_user_values_with_empty_schema(client, db_session):
    user_id = create_user(client, "noscope@example.com")["id"]

    product_resp = client.post(
        "/api/products", json={"name": "noscope-prod", "description": "desc"}
    )
    assert product_resp.status_code == 201
    product_id = product_resp.json()["id"]

    tmpl_resp = client.post(
        f"/api/products/{product_id}/templates",
        json={
            "chart_ref": "oci://example/chart",
            "chart_version": "1.0.0",
            "values_schema_json": {"type": "object", "additionalProperties": False},
        },
    )
    assert tmpl_resp.status_code == 201
    tmpl_id = tmpl_resp.json()["id"]

    # Make it the canonical template
    client.put(f"/api/products/{product_id}", json={"template_id": tmpl_id})

    ptv_id = create_free_plan_template(db_session, product_id)

    dep_resp = client.post(
        f"/api/users/{user_id}/deployments",
        json={
            "desired_template_id": tmpl_id,
            # A closed, property-less schema accepts empty user values.
            "user_values_json": {},
            "plan_template_id": ptv_id,
        },
    )
    assert dep_resp.status_code == 201


def test_create_deployment_rejects_unknown_user_keys_against_schema(client, db_session):
    user_id = create_user(client, "unknownkeys@example.com")["id"]

    product_resp = client.post(
        "/api/products", json={"name": "unknownkeys-prod", "description": "desc"}
    )
    assert product_resp.status_code == 201
    product_id = product_resp.json()["id"]

    schema = {
        "type": "object",
        "properties": {
            "user": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "additionalProperties": False,
            }
        },
        "additionalProperties": False,
    }
    tmpl_resp = client.post(
        f"/api/products/{product_id}/templates",
        json={
            "chart_ref": "oci://example/chart",
            "chart_version": "1.0.0",
            "values_schema_json": schema,
        },
    )
    assert tmpl_resp.status_code == 201
    tmpl_id = tmpl_resp.json()["id"]

    # Make it the canonical template
    client.put(f"/api/products/{product_id}", json={"template_id": tmpl_id})

    ptv_id = create_free_plan_template(db_session, product_id)

    dep_resp = client.post(
        f"/api/users/{user_id}/deployments",
        json={
            "desired_template_id": tmpl_id,
            "user_values_json": {"message": "hello", "extra": True},
            "plan_template_id": ptv_id,
        },
    )
    assert dep_resp.status_code == 409
    assert "invalid" in dep_resp.json()["detail"]


def test_create_deployment_derives_hostname_recursively_case_insensitive_and_first_match(client, db_session):
    user_id = create_user(client, "recursive@example.com")["id"]

    product_resp = client.post(
        "/api/products", json={"name": "recursive-prod", "description": "desc"}
    )
    assert product_resp.status_code == 201
    product_id = product_resp.json()["id"]

    tmpl_resp = client.post(
        f"/api/products/{product_id}/templates",
        json={
            "chart_ref": "oci://example/chart",
            "chart_version": "1.0.0",
            "values_schema_json": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "outer_first": {"type": "string", "title": "Hostname"},
                    "nested": {
                        "type": "object",
                        "properties": {
                            "inner": {"type": "string", "title": "hostname"},
                        },
                    },
                },
            },
        },
    )
    assert tmpl_resp.status_code == 201
    tmpl_id = tmpl_resp.json()["id"]

    # Make it the canonical template
    client.put(f"/api/products/{product_id}", json={"template_id": tmpl_id})

    ptv_id = create_free_plan_template(db_session, product_id)

    dep_resp = client.post(
        f"/api/users/{user_id}/deployments",
        json={
            "desired_template_id": tmpl_id,
            "user_values_json": {"outer_first": "first.example.test", "nested": {"inner": "second.example.test"}},
            "plan_template_id": ptv_id,
        },
    )
    assert dep_resp.status_code == 201
    assert dep_resp.json()["deployment"]["hostname"] == "first.example.test"


def test_update_deployment_rederives_hostname_from_user_values(client, db_session):
    user_id = create_user(client, "rederive@example.com")["id"]

    product_resp = client.post(
        "/api/products", json={"name": "rederive-prod", "description": "desc"}
    )
    assert product_resp.status_code == 201
    product_id = product_resp.json()["id"]

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "domain": {"type": "string", "title": "hostname"},
            "user": {"type": "object"},
        },
    }
    tmpl1_resp = client.post(
        f"/api/products/{product_id}/templates",
        json={"chart_ref": "oci://example/chart", "chart_version": "1.0.0", "values_schema_json": schema},
    )
    assert tmpl1_resp.status_code == 201
    tmpl1_id = tmpl1_resp.json()["id"]

    # Make it the canonical template
    client.put(f"/api/products/{product_id}", json={"template_id": tmpl1_id})

    tmpl2_resp = client.post(
        f"/api/products/{product_id}/templates",
        json={"chart_ref": "oci://example/chart", "chart_version": "2.0.0", "values_schema_json": schema},
    )
    assert tmpl2_resp.status_code == 201
    tmpl2_id = tmpl2_resp.json()["id"]

    ptv_id = create_free_plan_template(db_session, product_id)

    dep_resp = client.post(
        f"/api/users/{user_id}/deployments",
        json={"desired_template_id": tmpl1_id, "user_values_json": {"domain": "before.example.test", "user": {}}, "plan_template_id": ptv_id},
    )
    assert dep_resp.status_code == 201
    dep_id = dep_resp.json()["deployment"]["id"]
    _finish_create_job(db_session, dep_id)

    update_resp = client.put(
        f"/api/users/{user_id}/deployments/{dep_id}",
        json={"desired_template_id": tmpl2_id, "user_values_json": {"domain": "after.example.test", "user": {}}},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["hostname"] == "after.example.test"


def test_same_version_update_with_new_values(client, db_session):
    """Updating user_values_json without changing template version should succeed."""
    user_id = create_user(client, "same-ver@example.com")["id"]

    product_resp = client.post(
        "/api/products", json={"name": "same-ver-prod", "description": "desc"}
    )
    product_id = product_resp.json()["id"]

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "domain": {"type": "string", "title": "hostname"},
            "color": {"type": "string"},
        },
    }
    tmpl_resp = client.post(
        f"/api/products/{product_id}/templates",
        json={"chart_ref": "oci://example/chart", "chart_version": "1.0.0", "values_schema_json": schema},
    )
    tmpl_id = tmpl_resp.json()["id"]

    # Make it the canonical template
    client.put(f"/api/products/{product_id}", json={"template_id": tmpl_id})

    ptv_id = create_free_plan_template(db_session, product_id)

    dep_resp = client.post(
        f"/api/users/{user_id}/deployments",
        json={"desired_template_id": tmpl_id, "user_values_json": {"domain": "same.example.test", "color": "red"}, "plan_template_id": ptv_id},
    )
    dep_id = dep_resp.json()["deployment"]["id"]
    _finish_create_job(db_session, dep_id)

    # Same template, different values
    update_resp = client.put(
        f"/api/users/{user_id}/deployments/{dep_id}",
        json={"desired_template_id": tmpl_id, "user_values_json": {"domain": "same.example.test", "color": "blue"}},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["desired_template_id"] == tmpl_id
    assert update_resp.json()["user_values_json"]["color"] == "blue"
    assert update_resp.json()["generation"] == 2
    assert update_resp.json()["status"] == DEPLOYMENT_STATUS_PROVISIONING


def test_update_deployment_rejects_non_ready_status(client, db_session):
    """Update should return 409 when deployment is not in ready state."""
    user_id = create_user(client, "notready@example.com")["id"]

    product_resp = client.post(
        "/api/products", json={"name": "notready-prod", "description": "desc"}
    )
    product_id = product_resp.json()["id"]

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"domain": {"type": "string", "title": "hostname"}},
    }
    tmpl_resp = client.post(
        f"/api/products/{product_id}/templates",
        json={"chart_ref": "oci://example/chart", "chart_version": "1.0.0", "values_schema_json": schema},
    )
    tmpl_id = tmpl_resp.json()["id"]

    # Make it the canonical template
    client.put(f"/api/products/{product_id}", json={"template_id": tmpl_id})

    ptv_id = create_free_plan_template(db_session, product_id)

    dep_resp = client.post(
        f"/api/users/{user_id}/deployments",
        json={"desired_template_id": tmpl_id, "user_values_json": {"domain": "notready.example.test"}, "plan_template_id": ptv_id},
    )
    dep_id = dep_resp.json()["deployment"]["id"]

    # Deployment is still in 'provisioning' — update should fail
    update_resp = client.put(
        f"/api/users/{user_id}/deployments/{dep_id}",
        json={"desired_template_id": tmpl_id, "user_values_json": {"domain": "notready.example.test"}},
    )
    assert update_resp.status_code == 409
    assert "not in ready state" in update_resp.json()["detail"]


def test_update_deployment_rejects_non_ready_error_status(client, db_session):
    """Update should return 409 when deployment is in error state."""
    user_id = create_user(client, "errstate@example.com")["id"]

    product_resp = client.post(
        "/api/products", json={"name": "errstate-prod", "description": "desc"}
    )
    product_id = product_resp.json()["id"]

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"domain": {"type": "string", "title": "hostname"}},
    }
    tmpl_resp = client.post(
        f"/api/products/{product_id}/templates",
        json={"chart_ref": "oci://example/chart", "chart_version": "1.0.0", "values_schema_json": schema},
    )
    tmpl_id = tmpl_resp.json()["id"]

    # Make it the canonical template
    client.put(f"/api/products/{product_id}", json={"template_id": tmpl_id})

    ptv_id = create_free_plan_template(db_session, product_id)

    dep_resp = client.post(
        f"/api/users/{user_id}/deployments",
        json={"desired_template_id": tmpl_id, "user_values_json": {"domain": "errstate.example.test"}, "plan_template_id": ptv_id},
    )
    dep_id = UUID(dep_resp.json()["deployment"]["id"])

    # Simulate error state
    deployment = db_session.get(DeploymentORM, dep_id)
    deployment.status = "error"
    db_session.add(deployment)
    db_session.commit()

    update_resp = client.put(
        f"/api/users/{user_id}/deployments/{dep_id}",
        json={"desired_template_id": tmpl_id, "user_values_json": {"domain": "errstate.example.test"}},
    )
    assert update_resp.status_code == 409


def _create_deployment_for_user(client, db_session, user_id, product_suffix=""):
    """Helper: create a product, template, and deployment for a user."""
    product_resp = client.post(
        "/api/products",
        json={"name": f"prod{product_suffix}", "description": "desc"},
    )
    product_id = product_resp.json()["id"]
    tmpl_resp = client.post(
        f"/api/products/{product_id}/templates",
        json={
            "chart_ref": "oci://example/chart",
            "chart_version": "1.0.0",
            "values_schema_json": {"type": "object", "additionalProperties": False},
        },
    )
    tmpl_id = tmpl_resp.json()["id"]
    client.put(f"/api/products/{product_id}", json={"template_id": tmpl_id})
    ptv_id = create_free_plan_template(db_session, product_id)
    dep_resp = client.post(
        f"/api/users/{user_id}/deployments",
        json={"desired_template_id": tmpl_id, "plan_template_id": ptv_id},
    )
    assert dep_resp.status_code == 201
    return UUID(dep_resp.json()["deployment"]["id"])


def test_list_deployments_excludes_deleted(client, db_session):
    """User-scoped list should not include deleted deployments."""
    user_id = create_user(client, "excl@example.com")["id"]

    dep_id = _create_deployment_for_user(client, db_session, user_id, "-excl")

    # Mark deployment as deleted
    deployment = db_session.get(DeploymentORM, dep_id)
    deployment.status = DEPLOYMENT_STATUS_DELETED
    db_session.add(deployment)
    db_session.commit()

    list_resp = client.get(f"/api/users/{user_id}/deployments")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 0


def test_list_deployments_includes_deleting(client, db_session):
    """User-scoped list should still include deployments with status 'deleting'."""
    user_id = create_user(client, "deleting@example.com")["id"]

    dep_id = _create_deployment_for_user(client, db_session, user_id, "-deleting")

    deployment = db_session.get(DeploymentORM, dep_id)
    deployment.status = DEPLOYMENT_STATUS_DELETING
    db_session.add(deployment)
    db_session.commit()

    list_resp = client.get(f"/api/users/{user_id}/deployments")
    assert list_resp.status_code == 200
    ids = [d["id"] for d in list_resp.json()]
    assert str(dep_id) in ids


def test_admin_list_all_deployments(client, db_session):
    """Admin endpoint returns deployments from multiple users."""
    user1_id = create_user(client, "admin-list1@example.com")["id"]
    user2_id = create_user(client, "admin-list2@example.com")["id"]

    dep1_id = _create_deployment_for_user(client, db_session, user1_id, "-admin1")
    dep2_id = _create_deployment_for_user(client, db_session, user2_id, "-admin2")

    resp = client.get("/api/deployments")
    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()]
    assert str(dep1_id) in ids
    assert str(dep2_id) in ids


def test_admin_list_deployments_excludes_deleted(client, db_session):
    """Admin endpoint should not include deleted deployments."""
    user_id = create_user(client, "admin-excl@example.com")["id"]

    dep_id = _create_deployment_for_user(client, db_session, user_id, "-admin-excl")

    deployment = db_session.get(DeploymentORM, dep_id)
    deployment.status = DEPLOYMENT_STATUS_DELETED
    db_session.add(deployment)
    db_session.commit()

    resp = client.get("/api/deployments")
    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()]
    assert str(dep_id) not in ids


def test_admin_list_deployments_forbidden_for_non_admin(user_client):
    """Non-admin user gets 403 from the admin deployments endpoint."""
    client, _ = user_client
    resp = client.get("/api/deployments")
    assert resp.status_code == 403
