"""Per-deployment object storage: provisioning, quota resolution and teardown.

The Garage admin API is faked at the *transport* boundary rather than at the
client's method boundary, so these exercise the real request paths, bodies and
read-before-write logic in `services/garage.py`. The fake is a dict of routes,
which is also what makes call ordering assertable — and ordering is load-bearing
in teardown.
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4

import httpx
import pytest

from app.config import CaelusSettings
from app.services import object_storage
from app.services.errors import IntegrityException
from app.services.garage import GarageAdminClient, GarageException

ADMIN_URL = "http://garage.invalid:3903"
BUCKET_ID = "0e53294303e88a1973d7d097f132d95931fd100d4f3711ef1d84c650b100634d"
ACCESS_KEY_ID = "GK556711a33725c0e01434a711"
SECRET_KEY = "s3cr3t"


class FakeGarage:
    """A minimal in-memory Garage admin API over an httpx transport."""

    def __init__(self) -> None:
        self.buckets: list[dict] = []
        self.keys: list[dict] = []
        self.secrets: dict[str, str] = {}
        self.grants: list[dict] = []
        self.updates: list[dict] = []
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        query = dict(request.url.params)
        body = json.loads(request.content) if request.content else {}
        self.requests.append(f"{request.method} {path}")

        if path == "/v2/ListBuckets":
            return httpx.Response(200, json=self.buckets)
        if path == "/v2/ListKeys":
            return httpx.Response(200, json=self.keys)
        if path == "/v2/CreateBucket":
            bucket = {"id": BUCKET_ID, "globalAliases": [body["globalAlias"]]}
            self.buckets.append(bucket)
            return httpx.Response(200, json=bucket)
        if path == "/v2/CreateKey":
            self.keys.append({"id": ACCESS_KEY_ID, "name": body["name"]})
            self.secrets[ACCESS_KEY_ID] = SECRET_KEY
            return httpx.Response(
                200, json={"accessKeyId": ACCESS_KEY_ID, "secretAccessKey": SECRET_KEY}
            )
        if path == "/v2/GetKeyInfo":
            return httpx.Response(
                200, json={"secretAccessKey": self.secrets.get(query["id"], "")}
            )
        if path == "/v2/DeleteKey":
            self.keys = [k for k in self.keys if k["id"] != query["id"]]
            return httpx.Response(200)
        if path == "/v2/AllowBucketKey":
            self.grants.append(body)
            return httpx.Response(200, json={})
        if path == "/v2/GetBucketInfo":
            return httpx.Response(200, json=self._bucket(query["id"]))
        if path == "/v2/UpdateBucket":
            self.updates.append(body)
            if "lifecycleRules" in body:
                self._bucket(query["id"])["lifecycleRules"] = body["lifecycleRules"] or None
            return httpx.Response(200, json={})
        return httpx.Response(404, text="unhandled")

    def _bucket(self, bucket_id: str) -> dict:
        return next(b for b in self.buckets if b["id"] == bucket_id)

    def client(self) -> GarageAdminClient:
        transport = httpx.MockTransport(self.handler)
        return GarageAdminClient(
            base_url=ADMIN_URL, token="t", client=httpx.Client(transport=transport)
        )


class FakePlanTemplate:
    def __init__(self, storage_bytes):
        self.storage_bytes = storage_bytes


class FakeSubscription:
    def __init__(self, storage_bytes):
        self.plan_template = FakePlanTemplate(storage_bytes)


class FakeTemplate:
    def __init__(self, system_values):
        self.system_values_json = system_values


class FakeDeployment:
    def __init__(self, *, storage_bytes=1073741824, storage_enabled=True, subscription=True):
        self.id = uuid4()
        self.name = "custom-user-app-abc123"
        self.namespace = "tenant-xyz"
        self.subscription = FakeSubscription(storage_bytes) if subscription else None
        self.desired_template = FakeTemplate(
            {"objectStorage": {"enabled": True}} if storage_enabled else {}
        )


@pytest.fixture
def settings():
    return CaelusSettings(
        garage_admin_url=ADMIN_URL,
        garage_admin_token="t",
        deployment_bucket_max_objects=1_000_000,
        deployment_bucket_expiry_days=1,
    )


# --- opt-in -----------------------------------------------------------------


def test_storage_is_off_unless_the_product_template_opts_in():
    assert object_storage.is_enabled(FakeDeployment(storage_enabled=True)) is True
    assert object_storage.is_enabled(FakeDeployment(storage_enabled=False)) is False


def test_opt_in_is_read_from_system_values_not_user_values():
    """A tenant cannot enable storage: the flag is read off the template's
    system values, which user values never reach."""
    deployment = FakeDeployment(storage_enabled=False)
    deployment.user_values_json = {"objectStorage": {"enabled": True}}
    assert object_storage.is_enabled(deployment) is False


# --- naming -----------------------------------------------------------------


def test_bucket_is_named_for_the_deployment_with_an_explicit_prefix():
    deployment = FakeDeployment()
    assert object_storage.bucket_name(deployment) == f"dep-{deployment.id}"
    # The prefix is what lets a sweep select deployment buckets explicitly
    # rather than guessing from the shape of a name.
    assert object_storage.bucket_name(deployment).startswith("dep-")


# --- quota resolution -------------------------------------------------------


def test_quota_comes_from_the_plan():
    assert object_storage.resolve_quota_bytes(FakeDeployment(storage_bytes=1073741824)) == 1073741824


@pytest.mark.parametrize("storage_bytes", [None, 0])
def test_absent_or_zero_plan_allowance_fails_rather_than_defaulting(storage_bytes):
    with pytest.raises(IntegrityException, match="no storage allowance"):
        object_storage.resolve_quota_bytes(FakeDeployment(storage_bytes=storage_bytes))


def test_no_subscription_fails_rather_than_defaulting():
    with pytest.raises(IntegrityException, match="no subscription"):
        object_storage.resolve_quota_bytes(FakeDeployment(subscription=False))


def test_quota_failure_provisions_nothing(settings):
    """Resolved before anything is created, so a misconfigured plan cannot leave
    a half-provisioned bucket behind."""
    garage = FakeGarage()
    with pytest.raises(IntegrityException):
        object_storage.ensure_object_storage(
            FakeDeployment(storage_bytes=0), client=garage.client(), settings=settings
        )
    assert garage.buckets == []
    assert garage.keys == []


# --- provisioning -----------------------------------------------------------


def test_provisioning_creates_key_bucket_grant_and_quota(settings):
    deployment = FakeDeployment()
    garage = FakeGarage()
    creds = object_storage.ensure_object_storage(
        deployment, client=garage.client(), settings=settings
    )

    assert creds.bucket == f"dep-{deployment.id}"
    assert creds.access_key_id == ACCESS_KEY_ID
    assert creds.secret_access_key == SECRET_KEY
    assert garage.grants == [
        {
            "bucketId": BUCKET_ID,
            "accessKeyId": ACCESS_KEY_ID,
            "permissions": {"read": True, "write": True},
        }
    ]
    # Never `owner`: that carries bucket administration, which the platform does
    # over the admin API instead.
    assert "owner" not in garage.grants[0]["permissions"]


def test_key_is_created_without_the_bucket_creation_permission(settings):
    """The injected credential must not be able to make more buckets."""
    garage = FakeGarage()
    object_storage.ensure_object_storage(
        FakeDeployment(), client=garage.client(), settings=settings
    )
    # `allow` is never sent, so Garage defaults the key to createBucket: false.
    assert "POST /v2/CreateKey" in garage.requests


def test_quota_and_cors_are_set_in_one_call(settings):
    garage = FakeGarage()
    object_storage.ensure_object_storage(
        FakeDeployment(storage_bytes=2147483648), client=garage.client(), settings=settings
    )
    assert len(garage.updates) == 1
    update = garage.updates[0]
    assert update["quotas"] == {"maxSize": 2147483648, "maxObjects": 1_000_000}
    # Both quotas together: Garage rejects changing one without the other.
    assert set(update["quotas"]) == {"maxSize", "maxObjects"}
    # ETag exposure is not optional — multipart uploads read it and CORS hides
    # it by default, and the failure is silent in the browser.
    assert update["corsRules"][0]["ExposeHeader"] == ["ETag"]
    # S3's XML field names, not camelCase.
    assert "AllowedOrigin" in update["corsRules"][0]


def test_provisioning_is_idempotent_and_never_rotates_a_live_key(settings):
    deployment = FakeDeployment()
    garage = FakeGarage()
    first = object_storage.ensure_object_storage(
        deployment, client=garage.client(), settings=settings
    )
    second = object_storage.ensure_object_storage(
        deployment, client=garage.client(), settings=settings
    )

    assert first == second
    assert len(garage.keys) == 1
    assert len(garage.buckets) == 1
    assert garage.requests.count("POST /v2/CreateKey") == 1
    assert garage.requests.count("POST /v2/CreateBucket") == 1


def test_provisioning_resumes_from_a_key_without_a_bucket(settings):
    """An interrupted run leaves a key with no bucket. The next run must finish
    the job, not conclude from the key's existence that it is done."""
    deployment = FakeDeployment()
    garage = FakeGarage()
    garage.keys.append({"id": ACCESS_KEY_ID, "name": object_storage.key_name(deployment)})
    garage.secrets[ACCESS_KEY_ID] = SECRET_KEY

    creds = object_storage.ensure_object_storage(
        deployment, client=garage.client(), settings=settings
    )

    assert len(garage.buckets) == 1
    assert creds.access_key_id == ACCESS_KEY_ID
    assert garage.requests.count("POST /v2/CreateKey") == 0
    assert garage.grants


def test_provisioning_repairs_a_grant_removed_out_of_band(settings):
    deployment = FakeDeployment()
    garage = FakeGarage()
    object_storage.ensure_object_storage(deployment, client=garage.client(), settings=settings)
    garage.grants.clear()
    object_storage.ensure_object_storage(deployment, client=garage.client(), settings=settings)
    assert len(garage.grants) == 1


def test_quota_is_reasserted_when_the_plan_changes(settings):
    deployment = FakeDeployment(storage_bytes=1073741824)
    garage = FakeGarage()
    object_storage.ensure_object_storage(deployment, client=garage.client(), settings=settings)
    deployment.subscription = FakeSubscription(5368709120)
    object_storage.ensure_object_storage(deployment, client=garage.client(), settings=settings)
    assert garage.updates[-1]["quotas"]["maxSize"] == 5368709120


def test_provisioning_sets_the_default_abort_rule_on_a_bucket_without_lifecycle(settings):
    garage = FakeGarage()
    object_storage.ensure_object_storage(
        FakeDeployment(), client=garage.client(), settings=settings
    )
    rules = garage.updates[-1]["lifecycleRules"]
    assert [r["AbortIncompleteMultipartUpload"] for r in rules] == [{"DaysAfterInitiation": 1}]
    # Never Expiration on a live bucket: that would delete the tenant's objects.
    assert not any("Expiration" in r for r in rules)


def test_provisioning_never_overwrites_the_tenant_s_own_lifecycle_rules(settings):
    """The tenant's key can replace the lifecycle configuration, and one it set
    is theirs: re-asserting the default on reconcile would silently drop it."""
    deployment = FakeDeployment()
    garage = FakeGarage()
    object_storage.ensure_object_storage(deployment, client=garage.client(), settings=settings)
    tenant_rules = [
        {"ID": "tmp", "Status": "Enabled", "Filter": {"Prefix": "tmp/"}, "Expiration": {"Days": 7}}
    ]
    garage.buckets[0]["lifecycleRules"] = tenant_rules

    object_storage.ensure_object_storage(deployment, client=garage.client(), settings=settings)

    assert "lifecycleRules" not in garage.updates[-1]
    assert garage.buckets[0]["lifecycleRules"] == tenant_rules


def test_the_default_abort_rule_returns_once_the_tenant_removes_theirs(settings):
    deployment = FakeDeployment()
    garage = FakeGarage()
    object_storage.ensure_object_storage(deployment, client=garage.client(), settings=settings)
    garage.buckets[0].pop("lifecycleRules")

    object_storage.ensure_object_storage(deployment, client=garage.client(), settings=settings)

    assert garage.updates[-1]["lifecycleRules"] == object_storage.BUCKET_DEFAULT_LIFECYCLE_RULES


# --- teardown ---------------------------------------------------------------


def test_teardown_deletes_the_key_before_setting_the_expiry_rule(settings):
    """Order is the whole point. A key with write access can replace its own
    bucket's lifecycle configuration, so setting the rule first would leave a
    window in which the tenant could strip it back off."""
    deployment = FakeDeployment()
    garage = FakeGarage()
    object_storage.ensure_object_storage(deployment, client=garage.client(), settings=settings)
    garage.requests.clear()

    object_storage.teardown_object_storage(
        deployment, client=garage.client(), settings=settings
    )

    delete_at = garage.requests.index("POST /v2/DeleteKey")
    update_at = len(garage.requests) - 1 - garage.requests[::-1].index("POST /v2/UpdateBucket")
    assert delete_at < update_at
    assert garage.keys == []


def test_teardown_sets_both_lifecycle_actions_and_keeps_the_bucket(settings):
    deployment = FakeDeployment()
    garage = FakeGarage()
    object_storage.ensure_object_storage(deployment, client=garage.client(), settings=settings)
    object_storage.teardown_object_storage(
        deployment, client=garage.client(), settings=settings
    )

    rules = garage.updates[-1]["lifecycleRules"]
    actions = {k for rule in rules for k in rule if k in ("Expiration", "AbortIncompleteMultipartUpload")}
    # Abandoned multipart parts consume disk while never appearing in a bucket
    # listing, so the second rule is not optional.
    assert actions == {"Expiration", "AbortIncompleteMultipartUpload"}
    assert rules[0]["Expiration"]["Days"] == 1
    # The bucket survives, still carrying its alias, so it stays attributable.
    assert len(garage.buckets) == 1
    assert "POST /v2/DeleteBucket" not in garage.requests


def test_teardown_tolerates_a_deployment_that_never_had_storage(settings):
    garage = FakeGarage()
    object_storage.teardown_object_storage(
        FakeDeployment(), client=garage.client(), settings=settings
    )
    assert garage.updates == []


# --- transport --------------------------------------------------------------


def test_lookups_return_absence_rather_than_raising(settings):
    client = FakeGarage().client()
    assert client.find_bucket("dep-nope") is None
    assert client.find_key("app-nope") is None


def test_a_non_2xx_body_surfaces_garage_s_own_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="<Error><Code>AccessDenied</Code></Error>")

    client = GarageAdminClient(
        base_url=ADMIN_URL, token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(GarageException, match="AccessDenied"):
        client.find_bucket("dep-x")


def test_query_parameters_are_encoded_rather_than_interpolated():
    """Ids reach the wire through httpx's encoder, not an f-string.

    Every id passed today is Garage-minted hex that needs no escaping, so this
    guards the property rather than a live bug: a value carrying `&`, `=` or a
    space must arrive as one parameter, not silently split into several.
    """
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"secretAccessKey": "s"})

    client = GarageAdminClient(
        base_url=ADMIN_URL, token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    hostile = "abc&showSecretKey=false&id=other bucket"
    client.get_key_secret(hostile)

    assert seen["id"] == hostile
    # The smuggled parameter did not take effect.
    assert seen["showSecretKey"] == "true"


def test_unconfigured_settings_fail_only_where_the_client_is_built():
    # Constructing settings must keep working for alembic, tests and the CLI.
    settings = CaelusSettings()
    with pytest.raises(GarageException, match="not configured"):
        GarageAdminClient.from_settings(settings)


def test_the_secret_access_key_is_never_logged(settings, caplog):
    garage = FakeGarage()
    with caplog.at_level(logging.DEBUG):
        object_storage.ensure_object_storage(
            FakeDeployment(), client=garage.client(), settings=settings
        )
    assert SECRET_KEY not in caplog.text
