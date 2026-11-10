"""Notices to administrators about new accounts and new deployments."""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.config import get_settings
from app.models import NotificationORM, UserORM
from app.models.core import _utcnow
from app.services.notifications import md
from tests.conftest import (
    ADMIN_EMAIL,
    auth_header,
    create_free_plan_template,
    create_paid_plan_template,
    create_user,
    subject_for,
)


def _notices(db_session, kind: str) -> list[NotificationORM]:
    return db_session.exec(select(NotificationORM).where(NotificationORM.kind == kind)).all()


def _admin_id(db_session, email: str = ADMIN_EMAIL) -> int:
    return db_session.exec(select(UserORM.id).where(UserORM.email == email)).one()


def _add_user(db_session, email: str, **kwargs) -> UserORM:
    user = UserORM(email=email, **kwargs)
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def https_base_url(monkeypatch):
    monkeypatch.setenv("CAELUS_BASE_URL", "https://freepod.example")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_a_new_account_notifies_every_live_admin(client, db_session, https_base_url):
    second = _add_user(db_session, "second-admin@example.com", is_admin=True)
    _add_user(db_session, "gone-admin@example.com", is_admin=True, deleted_at=_utcnow())
    _add_user(db_session, "plain@example.com")

    assert client.get("/api/me", headers=auth_header("ana@example.com")).status_code == 200

    rows = _notices(db_session, "admin.account_created")
    assert {r.recipient_user_id for r in rows} == {_admin_id(db_session), second.id}
    row = rows[0]
    assert row.subject == "New account: ana@example.com"
    assert md("ana@example.com") in row.body
    assert md(subject_for("ana@example.com")) in row.body
    assert "**IP address:** testclient" in row.body
    assert (row.action_label, row.action_url) == ("View users", "https://freepod.example/admin/users")


def test_a_returning_or_adopted_account_queues_nothing(client, db_session):
    _add_user(db_session, "ana@example.com")
    client.get("/api/me", headers=auth_header("ana@example.com"))
    client.get("/api/me", headers=auth_header("ana@example.com"))
    assert _notices(db_session, "admin.account_created") == []


def test_a_new_deployment_notifies_admins(paid_client, db_session, https_base_url):
    product_id = paid_client.post("/api/products", json={"name": "notepad", "description": "d"}).json()["id"]
    template_id = paid_client.post(
        f"/api/products/{product_id}/templates",
        json={"chart_ref": "oci://test/chart", "chart_version": "1.0.0",
              "values_schema_json": {"type": "object", "additionalProperties": False}},
    ).json()["id"]
    paid_client.put(f"/api/products/{product_id}", json={"template_id": template_id})
    ana = create_user(paid_client, "ana@example.com")
    paid = create_paid_plan_template(db_session, product_id, price_cents=450, name="Personal")
    free = create_free_plan_template(db_session, product_id)

    for plan in (paid, free):
        resp = paid_client.post(
            f"/api/users/{ana['id']}/deployments",
            json={"desired_template_id": template_id, "plan_template_id": plan},
            headers=auth_header("ana@example.com"),
        )
        assert resp.status_code == 201, resp.text

    first, second = sorted(_notices(db_session, "admin.deployment_created"), key=lambda r: r.created_at)
    assert first.recipient_user_id == _admin_id(db_session)
    assert first.subject == "New deployment: notepad by ana@example.com"
    assert "**Plan:** Personal, €4.50 a month" in first.body
    assert "**Status:** awaiting payment" in first.body
    assert f"**Owner:** {md('ana@example.com')} (ana)" in first.body
    assert (first.action_label, first.action_url) == ("View deployments", "https://freepod.example/admin/deployments")
    assert "**Plan:** Free, €0.00 a month" in second.body
    assert "**Status:** provisioning" in second.body


def test_an_admins_own_deployment_notifies_only_the_other_admins(client, db_session):
    second = _add_user(db_session, "second-admin@example.com", is_admin=True)
    product_id = client.post("/api/products", json={"name": "notepad", "description": "d"}).json()["id"]
    template_id = client.post(
        f"/api/products/{product_id}/templates",
        json={"chart_ref": "oci://test/chart", "chart_version": "1.0.0",
              "values_schema_json": {"type": "object", "additionalProperties": False}},
    ).json()["id"]
    client.put(f"/api/products/{product_id}", json={"template_id": template_id})

    resp = client.post(
        f"/api/users/{_admin_id(db_session)}/deployments",
        json={"desired_template_id": template_id, "plan_template_id": create_free_plan_template(db_session, product_id)},
    )
    assert resp.status_code == 201, resp.text
    assert [r.recipient_user_id for r in _notices(db_session, "admin.deployment_created")] == [second.id]
