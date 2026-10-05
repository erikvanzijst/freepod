from uuid import UUID

from sqlmodel import select

from app.models import DeploymentReconcileJobORM
from app.services.jobs import JobService
from app.services.reconcile_constants import DEPLOYMENT_STATUS_DELETING
from tests.conftest import client
from tests.conftest import create_free_plan_template, create_user


def test_delete_deployment_flow(client, db_session):
    # create user
    user_id = create_user(client, "deldep@example.com")["id"]
    # create product
    prod_resp = client.post("/api/products", json={"name": "prod1", "description": "desc"})
    assert prod_resp.status_code == 201
    prod_id = prod_resp.json()["id"]
    # create template
    tmpl_resp = client.post(
        f"/api/products/{prod_id}/templates",
        json={
            "chart_ref": "registry.home/nextcloud/",
            "chart_version": "1.0.0",
            "values_schema_json": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"domain": {"type": "string", "title": "hostname"}},
            },
        },
    )
    assert tmpl_resp.status_code == 201
    tmpl_id = tmpl_resp.json()["id"]
    # Make it the canonical template
    client.put(f"/api/products/{prod_id}", json={"template_id": tmpl_id})
    ptv_id = create_free_plan_template(db_session, prod_id)
    # create deployment
    dep_resp = client.post(
        f"/api/users/{user_id}/deployments",
        json={"desired_template_id": tmpl_id, "user_values_json": {"domain": "example.com"}, "plan_template_id": ptv_id},
    )
    assert dep_resp.status_code == 201
    dep_id = dep_resp.json()["deployment"]["id"]
    create_job = db_session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == UUID(dep_id),
            DeploymentReconcileJobORM.reason == "create",
        )
    ).one()
    JobService(db_session).mark_job_done(job_id=create_job.id)
    # delete deployment
    del_resp = client.delete(f"/api/users/{user_id}/deployments/{dep_id}")
    assert del_resp.status_code == 204
    # After deletion, the deployment can still be retrieved:
    get_resp = client.get(f"/api/users/{user_id}/deployments/{dep_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == DEPLOYMENT_STATUS_DELETING

    # And also still present in listing:
    list_resp = client.get(f"/api/users/{user_id}/deployments")
    assert list_resp.status_code == 200
    assert dep_id in {d["id"] for d in list_resp.json()}
