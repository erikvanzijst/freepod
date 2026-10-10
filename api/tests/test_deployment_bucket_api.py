"""A deployment's bucket, its credentials and its usage.

Reads only: the endpoint, the `caelus` command and the service under both
answer from Garage's admin API (one key lookup, and one bucket lookup when
usage is asked for) and the platform's S3 settings, and write nothing.

Garage is faked at the transport, with response bodies in the shape a real
v2.3.0 instance returns.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
from sqlmodel import select

from app.config import get_settings
from app.models import (
    BillingInterval,
    PlanORM,
    PlanTemplateVersionORM,
    ProductORM,
    ProductTemplateVersionORM,
    SubscriptionORM,
    UserORM,
)
from app.models.core import _utcnow
from app.services import deployments as deployment_service
from app.services import object_storage
from app.services.garage import GarageAdminClient
from app.services.reconcile_constants import DEPLOYMENT_STATUS_DELETED
from tests.conftest import USER_EMAIL, create_user, make_deployment_with_release

GIGABYTE = 1024 ** 3
ENDPOINT = "https://blob.dev.example.test"
REGION = "garage"
ACCESS_KEY_ID = "GK7336a630a8a03ea0bd05cf73"
SECRET = "3cf36d6b8f77b0c3c1e46ee2db900d9f5d77303366a93d32a00c6aab017f7f41"
BUCKET_ID = "aca9c886bf5f25fd616b5e26dec93fdf544108ec7d5578895c30ce485776831d"


class FakeGarage:
    """The two read calls this capability makes, plus a log of every request."""

    def __init__(self) -> None:
        self.keys: dict[str, dict] = {}
        self.buckets: dict[str, dict] = {}
        self.requests: list[str] = []
        self.down = False

    def provision(self, deployment, *, bytes_=0, objects=0) -> None:
        name = object_storage.key_name(deployment)
        alias = object_storage.bucket_name(deployment)
        self.keys[name] = {
            "accessKeyId": ACCESS_KEY_ID,
            "name": name,
            "expiration": None,
            "expired": False,
            "secretAccessKey": SECRET,
            "permissions": {"createBucket": False},
            "buckets": [{"id": BUCKET_ID, "globalAliases": [alias]}],
        }
        self.buckets[alias] = {
            "id": BUCKET_ID,
            "globalAliases": [alias],
            "objects": objects,
            "bytes": bytes_,
            "unfinishedUploads": 0,
            "quotas": {"maxSize": GIGABYTE, "maxObjects": 1_000_000},
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(f"{request.method} {request.url.path}?{request.url.query.decode()}")
        if self.down:
            return httpx.Response(503, text="unavailable")
        query = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        path = request.url.path
        if path == "/v2/GetKeyInfo":
            key = self.keys.get(query.get("search", ""))
            if key is None:
                return httpx.Response(404, json={"code": "NoSuchAccessKey"})
            body = dict(key)
            if query.get("showSecretKey") != "true":
                body.pop("secretAccessKey")
            return httpx.Response(200, json=body)
        if path == "/v2/GetBucketInfo":
            bucket = self.buckets.get(query.get("globalAlias", ""))
            if bucket is None:
                return httpx.Response(404, json={"code": "NoSuchBucket"})
            return httpx.Response(200, json=bucket)
        return httpx.Response(500, text=f"unexpected call {path}")

    def client(self) -> GarageAdminClient:
        return GarageAdminClient(
            base_url="http://garage.invalid:3903",
            token="t",
            client=httpx.Client(transport=httpx.MockTransport(self.handler)),
        )


@pytest.fixture(autouse=True)
def garage(monkeypatch):
    monkeypatch.setenv("CAELUS_S3_ENDPOINT_URL", ENDPOINT)
    monkeypatch.setenv("CAELUS_S3_REGION", REGION)
    get_settings.cache_clear()
    fake = FakeGarage()
    monkeypatch.setattr(
        object_storage.GarageAdminClient, "from_settings", classmethod(lambda cls, s=None: fake.client())
    )
    yield fake
    get_settings.cache_clear()


def _deployment(session, *, user_id: int, enabled: bool = True):
    """A deployment whose product opts into object storage, or does not."""
    token = uuid4().hex[:8]
    product = ProductORM(name=f"obj-product-{token}", created_at=_utcnow())
    session.add(product)
    session.commit()

    template = ProductTemplateVersionORM(
        product_id=product.id,
        chart_ref="oci://example/chart",
        chart_version="1.0.0",
        system_values_json={"objectStorage": {"enabled": enabled}},
    )
    session.add(template)
    session.commit()

    plan = PlanORM(name=f"obj-plan-{token}", product_id=product.id, created_at=_utcnow())
    session.add(plan)
    session.flush()
    ptv = PlanTemplateVersionORM(
        plan_id=plan.id,
        price_cents=0,
        billing_interval=BillingInterval.MONTHLY,
        storage_bytes=GIGABYTE,
        created_at=_utcnow(),
    )
    session.add(ptv)
    session.flush()
    plan.template_id = ptv.id
    subscription = SubscriptionORM(plan_template_id=ptv.id, user_id=user_id, created_at=_utcnow())
    session.add(subscription)
    session.commit()

    deployment = make_deployment_with_release(
        session,
        user_id=user_id,
        desired_template_id=template.id,
        subscription_id=subscription.id,
        hostname=f"{token}.example.test",
        name=f"app-{token}",
        namespace=f"ns-{token}",
    )
    session.commit()
    session.refresh(deployment)
    return deployment


def _owner(session) -> UserORM:
    owner = UserORM(email=f"owner-{uuid4().hex[:8]}@example.com")
    session.add(owner)
    session.commit()
    return owner


def _user_id(session, email: str) -> int:
    return session.exec(select(UserORM).where(UserORM.email == email)).one().id


def _details(session, deployment, *, viewer_id, usage=True):
    return deployment_service.get_bucket_details(
        session,
        deployment_id=deployment.id,
        user_id=deployment.user_id,
        viewer_id=viewer_id,
        usage=usage,
    )


# ── The read model and the service ────────────────────────────────────────


def test_the_owner_gets_every_field(db_session, garage):
    owner = _owner(db_session)
    deployment = _deployment(db_session, user_id=owner.id)
    garage.provision(deployment, bytes_=5 * 1024, objects=3)

    details = _details(db_session, deployment, viewer_id=owner.id)

    assert details.bucket == f"dep-{deployment.id}"
    assert details.endpoint == ENDPOINT
    assert details.region == REGION
    assert details.access_key_id == ACCESS_KEY_ID
    assert details.secret_access_key == SECRET
    assert details.secret_withheld is False
    assert details.usage.bytes == 5 * 1024
    assert details.usage.objects == 3
    assert details.usage.max_size_bytes == GIGABYTE
    assert details.usage.max_objects == 1_000_000


def test_no_field_carries_the_internal_bucket_id_or_a_composed_url(db_session, garage):
    owner = _owner(db_session)
    deployment = _deployment(db_session, user_id=owner.id)
    garage.provision(deployment)

    dumped = json.dumps(_details(db_session, deployment, viewer_id=owner.id).model_dump())

    assert BUCKET_ID not in dumped
    # The endpoint is the only URL, and nothing is composed onto it.
    assert dumped.count("https://") == 1
    assert f"{ENDPOINT}/" not in dumped


def test_the_secret_is_withheld_from_anyone_but_the_owner(db_session, garage):
    owner = _owner(db_session)
    admin = UserORM(email=f"admin-{uuid4().hex[:8]}@example.com", is_admin=True)
    db_session.add(admin)
    db_session.commit()
    deployment = _deployment(db_session, user_id=owner.id)
    garage.provision(deployment)

    details = _details(db_session, deployment, viewer_id=admin.id)

    assert details.secret_access_key is None
    assert details.secret_withheld is True
    assert details.access_key_id == ACCESS_KEY_ID
    assert SECRET not in json.dumps(details.model_dump())
    # Not merely dropped from the response: never asked of Garage.
    assert not any("showSecretKey" in r for r in garage.requests)


def test_a_caller_that_cannot_say_who_is_asking_gets_no_secret(db_session, garage):
    owner = _owner(db_session)
    deployment = _deployment(db_session, user_id=owner.id)
    garage.provision(deployment)

    details = _details(db_session, deployment, viewer_id=None)
    assert details.secret_access_key is None and details.secret_withheld is True


def test_usage_can_be_skipped_and_is_then_not_read(db_session, garage):
    owner = _owner(db_session)
    deployment = _deployment(db_session, user_id=owner.id)
    garage.provision(deployment, bytes_=0, objects=0)

    details = _details(db_session, deployment, viewer_id=owner.id, usage=False)

    assert details.usage is None
    assert details.secret_access_key == SECRET
    assert not any("GetBucketInfo" in r for r in garage.requests)


def test_an_empty_bucket_is_not_the_same_as_usage_not_requested(db_session, garage):
    owner = _owner(db_session)
    deployment = _deployment(db_session, user_id=owner.id)
    garage.provision(deployment)

    details = _details(db_session, deployment, viewer_id=owner.id)
    assert details.usage is not None and details.usage.bytes == 0


def test_a_product_without_object_storage_asks_garage_nothing(db_session, garage):
    owner = _owner(db_session)
    deployment = _deployment(db_session, user_id=owner.id, enabled=False)

    with pytest.raises(object_storage.ObjectStorageUnavailableException) as raised:
        _details(db_session, deployment, viewer_id=owner.id)

    assert raised.value.code == "object_storage_unavailable"
    assert garage.requests == []


def test_a_bucket_not_yet_provisioned_is_unavailable(db_session, garage):
    owner = _owner(db_session)
    deployment = _deployment(db_session, user_id=owner.id)

    with pytest.raises(object_storage.ObjectStorageUnavailableException):
        _details(db_session, deployment, viewer_id=owner.id)


def test_a_partial_name_match_is_not_trusted(db_session, garage):
    """`search` matches partially; only the exact name counts as this key."""
    owner = _owner(db_session)
    deployment = _deployment(db_session, user_id=owner.id)
    garage.provision(deployment)
    name = object_storage.key_name(deployment)
    garage.keys[name]["name"] = name + "-other"

    with pytest.raises(object_storage.ObjectStorageUnavailableException):
        _details(db_session, deployment, viewer_id=owner.id)


def test_an_unreachable_store_is_not_reported_as_no_bucket(db_session, garage):
    owner = _owner(db_session)
    deployment = _deployment(db_session, user_id=owner.id)
    garage.provision(deployment)
    garage.down = True

    with pytest.raises(Exception) as raised:
        _details(db_session, deployment, viewer_id=owner.id)
    assert not isinstance(raised.value, object_storage.ObjectStorageUnavailableException)


def test_reading_issues_only_reads(db_session, garage):
    owner = _owner(db_session)
    deployment = _deployment(db_session, user_id=owner.id)
    garage.provision(deployment)

    first = _details(db_session, deployment, viewer_id=owner.id)
    second = _details(db_session, deployment, viewer_id=owner.id)

    assert first.secret_access_key == second.secret_access_key == SECRET
    assert all(r.startswith("GET /v2/GetKeyInfo?") or r.startswith("GET /v2/GetBucketInfo?")
               for r in garage.requests)


def test_a_deleted_deployment_is_not_found(db_session, garage):
    owner = _owner(db_session)
    deployment = _deployment(db_session, user_id=owner.id)
    garage.provision(deployment)
    deployment.status = DEPLOYMENT_STATUS_DELETED
    db_session.add(deployment)
    db_session.commit()

    with pytest.raises(Exception) as raised:
        _details(db_session, deployment, viewer_id=owner.id)
    assert not isinstance(raised.value, object_storage.ObjectStorageUnavailableException)
    assert "not found" in str(raised.value).lower()


# ── The endpoint ──────────────────────────────────────────────────────────


def test_the_owner_reads_the_details_through_the_api(user_client, db_session, garage):
    client, _admin = user_client
    owner_id = _user_id(db_session, USER_EMAIL)
    deployment = _deployment(db_session, user_id=owner_id)
    garage.provision(deployment, bytes_=2048, objects=2)

    resp = client.get(f"/api/users/{owner_id}/deployments/{deployment.id}/bucket")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "bucket": f"dep-{deployment.id}",
        "endpoint": ENDPOINT,
        "region": REGION,
        "access_key_id": ACCESS_KEY_ID,
        "secret_access_key": SECRET,
        "secret_withheld": False,
        "usage": {
            "bytes": 2048,
            "objects": 2,
            "max_size_bytes": GIGABYTE,
            "max_objects": 1_000_000,
        },
    }


def test_usage_false_skips_usage_through_the_api(user_client, db_session, garage):
    client, _admin = user_client
    owner_id = _user_id(db_session, USER_EMAIL)
    deployment = _deployment(db_session, user_id=owner_id)
    garage.provision(deployment)

    resp = client.get(
        f"/api/users/{owner_id}/deployments/{deployment.id}/bucket", params={"usage": "false"}
    )

    assert resp.status_code == 200
    assert resp.json()["usage"] is None
    assert not any("GetBucketInfo" in r for r in garage.requests)


def test_an_administrator_reads_everything_but_the_secret(client, db_session, garage):
    owner_id = create_user(client, "bucket-owner@example.com")["id"]
    deployment = _deployment(db_session, user_id=owner_id)
    garage.provision(deployment)

    resp = client.get(f"/api/users/{owner_id}/deployments/{deployment.id}/bucket")

    assert resp.status_code == 200
    body = resp.json()
    assert body["access_key_id"] == ACCESS_KEY_ID
    assert body["secret_access_key"] is None
    assert body["secret_withheld"] is True
    assert SECRET not in resp.text


def test_a_non_owner_is_refused(user_client, db_session, garage):
    client, admin_user = user_client
    deployment = _deployment(db_session, user_id=admin_user.id)
    garage.provision(deployment)

    resp = client.get(f"/api/users/{admin_user.id}/deployments/{deployment.id}/bucket")
    assert resp.status_code == 403


def test_a_product_without_object_storage_answers_with_a_stable_code(user_client, db_session, garage):
    client, _admin = user_client
    owner_id = _user_id(db_session, USER_EMAIL)
    deployment = _deployment(db_session, user_id=owner_id, enabled=False)

    resp = client.get(f"/api/users/{owner_id}/deployments/{deployment.id}/bucket")

    assert resp.status_code == 404
    assert resp.json()["code"] == "object_storage_unavailable"


def test_a_deleted_deployment_answers_the_standard_not_found(user_client, db_session, garage):
    client, _admin = user_client
    owner_id = _user_id(db_session, USER_EMAIL)
    deployment = _deployment(db_session, user_id=owner_id)
    garage.provision(deployment)
    deployment.status = DEPLOYMENT_STATUS_DELETED
    db_session.add(deployment)
    db_session.commit()

    resp = client.get(f"/api/users/{owner_id}/deployments/{deployment.id}/bucket")

    assert resp.status_code == 404
    assert resp.json().get("code") != "object_storage_unavailable"


def test_a_deployment_under_the_wrong_owner_is_not_found(client, db_session, garage):
    owner_id = create_user(client, "bucket-owner-2@example.com")["id"]
    other_id = create_user(client, "bucket-other@example.com")["id"]
    deployment = _deployment(db_session, user_id=owner_id)
    garage.provision(deployment)

    resp = client.get(f"/api/users/{other_id}/deployments/{deployment.id}/bucket")

    assert resp.status_code == 404
    assert resp.json().get("code") != "object_storage_unavailable"


def test_an_unreachable_store_is_a_server_error(user_client, db_session, garage):
    client, _admin = user_client
    owner_id = _user_id(db_session, USER_EMAIL)
    deployment = _deployment(db_session, user_id=owner_id)
    garage.provision(deployment)
    garage.down = True

    resp = client.get(f"/api/users/{owner_id}/deployments/{deployment.id}/bucket")

    assert resp.status_code >= 500
    assert "object_storage_unavailable" not in resp.text


def test_the_secret_never_reaches_a_log(user_client, db_session, garage, caplog):
    client, _admin = user_client
    owner_id = _user_id(db_session, USER_EMAIL)
    deployment = _deployment(db_session, user_id=owner_id)
    garage.provision(deployment)
    # Fail *after* the key, and its secret, came back: the bucket lookup breaks.
    del garage.buckets[object_storage.bucket_name(deployment)]

    with caplog.at_level(logging.DEBUG):
        ok = client.get(
            f"/api/users/{owner_id}/deployments/{deployment.id}/bucket", params={"usage": "false"}
        )
        failed = client.get(f"/api/users/{owner_id}/deployments/{deployment.id}/bucket")

    assert ok.status_code == 200 and failed.status_code == 404
    assert SECRET not in caplog.text
    assert SECRET not in failed.text


# ── `caelus` parity ───────────────────────────────────────────────────────


def _seed_for_cli(garage, *, owner_email: str, enabled: bool = True):
    from app.db import session_scope

    with session_scope() as session:
        owner = UserORM(email=owner_email)
        session.add(owner)
        session.commit()
        session.refresh(owner)
        deployment = _deployment(session, user_id=owner.id, enabled=enabled)
        garage.provision(deployment, bytes_=10, objects=1)
        return owner.id, deployment.id


def test_caelus_reports_the_same_read(cli_runner, garage):
    runner, cli_app = cli_runner
    owner_id, deployment_id = _seed_for_cli(garage, owner_email="cli-bucket-owner@example.com")

    result = runner.invoke(
        cli_app,
        ["--as-user", "cli-bucket-owner@example.com", "get-deployment-bucket",
         str(owner_id), str(deployment_id)],
    )

    assert result.exit_code == 0, result.output
    assert SECRET in result.output
    assert "secret_withheld: false" in result.output.lower()
    assert f"dep-{deployment_id}" in result.output
    assert "max_size_bytes" in result.output


def test_caelus_withholds_the_secret_from_an_operator_who_is_not_the_owner(cli_runner, garage):
    runner, cli_app = cli_runner
    owner_id, deployment_id = _seed_for_cli(garage, owner_email="cli-bucket-owner-2@example.com")

    result = runner.invoke(
        cli_app, ["get-deployment-bucket", str(owner_id), str(deployment_id), "--no-usage"]
    )

    assert result.exit_code == 0, result.output
    assert SECRET not in result.output
    assert "secret_withheld: true" in result.output.lower()
    assert "usage: null" in result.output


def test_caelus_reports_no_bucket_without_a_traceback(cli_runner, garage):
    runner, cli_app = cli_runner
    owner_id, deployment_id = _seed_for_cli(
        garage, owner_email="cli-bucket-owner-3@example.com", enabled=False
    )

    result = runner.invoke(
        cli_app, ["get-deployment-bucket", str(owner_id), str(deployment_id)]
    )

    assert result.exit_code == 1
    assert "Traceback" not in result.output
