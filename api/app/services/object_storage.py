"""Per-deployment object storage: policy on top of the Garage admin API.

Everything here is about *a deployment* — what its bucket is called, how much it
may store, what happens to it when the deployment is deleted. The transport it
sits on knows none of that; see ``garage.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from app.config import CaelusSettings, get_settings
from app.models import DeploymentORM
from app.services.errors import IntegrityException
from app.services.garage import GarageAdminClient

logger = logging.getLogger(__name__)

BUCKET_PREFIX = "dep-"
KEY_PREFIX = "app-"

# Browser-direct uploads need a CORS rule on the bucket, and a tenant cannot set
# one: PutBucketCors requires `owner`, which no tenant key is granted. So the
# platform sets it.
#
# `*` is safe on this endpoint because every request is authenticated by
# signature and there is no ambient authority — no cookies, no session, and `*`
# cannot be combined with Access-Control-Allow-Credentials. A caller still needs
# a valid presigned URL or signing key, and CORS was never what stopped one that
# had it.
#
# ExposeHeader/ETag is not optional: multipart uploads read the per-part ETag,
# CORS hides it by default, and the failure is silent in the browser.
#
# S3's XML field names, not camelCase. See garage.update_bucket.
BUCKET_CORS_RULES: list[dict[str, object]] = [
    {
        "ID": "caelus-browser-access",
        "AllowedOrigin": ["*"],
        "AllowedMethod": ["GET", "PUT", "POST", "DELETE", "HEAD"],
        "AllowedHeader": ["*"],
        "ExposeHeader": ["ETag"],
    }
]

# Abandoned multipart uploads hold disk while never appearing in a listing or in
# the bucket's size, so neither the quota nor metering sees them. Garage runs
# lifecycle once a day at midnight UTC and counts days from the midnight after
# initiation, so 1 aborts an upload 24–48 hours after it began.
#
# A default, not a policy: the tenant's key can replace the whole lifecycle
# configuration, so this is only applied to a bucket that has none, and never
# overwrites the tenant's own rules.
ABORT_INCOMPLETE_UPLOAD_DAYS = 1
BUCKET_DEFAULT_LIFECYCLE_RULES: list[dict[str, object]] = [
    {
        "ID": "caelus-abort-incomplete-multipart-uploads",
        "Status": "Enabled",
        "Filter": {"Prefix": ""},
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": ABORT_INCOMPLETE_UPLOAD_DAYS},
    }
]


@dataclass(frozen=True)
class ObjectStorageCredentials:
    """What a provisioned deployment needs to reach its bucket."""

    bucket: str
    access_key_id: str
    secret_access_key: str


def is_enabled(deployment: DeploymentORM) -> bool:
    """Whether this deployment's product opts into object storage.

    Product-level platform policy, read from the template's system values —
    never from user values, which a tenant controls. `merge_values_scoped`
    applies system overrides last precisely so a tenant cannot shadow them, but
    this does not go through merged values at all: it reads the template
    directly, so there is no merge order to reason about.

    ``system_values`` **are** the chart's default Helm values, handed to Helm
    verbatim, so this flag must be a property the chart's own
    ``values.schema.json`` declares — a top-level platform key that the schema
    does not know about is rejected outright by any chart setting
    ``additionalProperties: false``.

    Deliberately *not* under ``caelus``: that namespace is for values the
    reconciler injects per deployment, and this is a static product declaration,
    identical for every deployment of the product. It is a real chart input, so
    it belongs in the chart's schema alongside ``registry`` and
    ``placeholderImage`` — the other system values a tenant cannot set.
    """
    template = deployment.desired_template
    if template is None:
        return False
    storage = (template.system_values_json or {}).get("objectStorage")
    return bool(isinstance(storage, dict) and storage.get("enabled"))


def bucket_name(deployment: DeploymentORM) -> str:
    return f"{BUCKET_PREFIX}{deployment.id}"


def key_name(deployment: DeploymentORM) -> str:
    return f"{KEY_PREFIX}{deployment.id}"


def resolve_quota_bytes(deployment: DeploymentORM) -> int:
    """The deployment's storage allowance, from its plan.

    Fail-closed and with no fallback. Every plan declares an allowance, so a
    storage-enabled deployment always has one to read; a quota that cannot be
    resolved is a misconfigured plan or a bug, and provisioning fails rather
    than inventing an allowance no plan authorized.

    This is deliberately the opposite of how the same field is projected into
    Helm values, where absent means "the chart falls back to its own default".
    That is safe because chart defaults are platform-written and bounded. An
    unset quota on a shared object store is neither.
    """
    subscription = deployment.subscription
    if subscription is None or subscription.plan_template is None:
        raise IntegrityException(
            f"Deployment {deployment.id} has object storage enabled but no subscription, "
            "so no storage allowance can be resolved"
        )
    storage_bytes = subscription.plan_template.storage_bytes
    if not storage_bytes or storage_bytes <= 0:
        raise IntegrityException(
            f"Deployment {deployment.id} has object storage enabled but its plan declares no "
            "storage allowance; refusing to provision an unbounded bucket"
        )
    return int(storage_bytes)


def ensure_object_storage(
    deployment: DeploymentORM,
    *,
    client: GarageAdminClient | None = None,
    settings: CaelusSettings | None = None,
) -> ObjectStorageCredentials:
    """Provision (or repair) this deployment's bucket, key, grant and quota.

    Every step reads before it writes and is verified **independently**. A run
    interrupted between creating the key and creating the bucket leaves a key
    with no bucket, and the next run must finish the job rather than conclude
    from the key's existence that provisioning is done.
    """
    settings = settings or get_settings()
    client = client or GarageAdminClient.from_settings(settings)

    # Resolved before anything is created, so a misconfigured plan fails without
    # leaving a half-provisioned bucket behind.
    quota_bytes = resolve_quota_bytes(deployment)

    alias = bucket_name(deployment)
    name = key_name(deployment)

    # 1. Access key. Garage mints the material — it cannot be pre-generated,
    #    because ImportKey rejects keys Garage did not create. The secret is
    #    returned once at creation and readable afterwards through GetKeyInfo,
    #    which is what makes the re-run path below possible without rotating.
    key = client.find_key(name)
    if key is None:
        created = client.create_key(name)
        access_key_id = created["accessKeyId"]
        secret_access_key = created["secretAccessKey"]
        logger.info(
            "Created object storage key deployment_id=%s access_key_id=%s",
            deployment.id,
            access_key_id,
        )
    else:
        access_key_id = key["id"]
        secret_access_key = client.get_key_secret(access_key_id)

    # 2. Bucket, checked on its own rather than inferred from the key.
    bucket = client.find_bucket(alias)
    if bucket is None:
        bucket = client.create_bucket(alias)
        logger.info(
            "Created object storage bucket deployment_id=%s bucket=%s", deployment.id, alias
        )
    bucket_id = bucket["id"]

    # 3. Grant. Re-asserted every time: this only ever widens (Garage ignores
    #    false flags rather than revoking), so re-applying repairs a grant
    #    removed out of band and can never narrow one by accident.
    client.allow_bucket_key(bucket_id=bucket_id, access_key_id=access_key_id)

    # 4. Quota, CORS and the default lifecycle rule, one call. Quota and CORS
    #    are re-asserted so a plan change takes effect on the next reconcile
    #    with no separate migration; lifecycle only fills a gap.
    has_lifecycle = bool(client.get_bucket(bucket_id).get("lifecycleRules"))
    client.update_bucket(
        bucket_id,
        quotas={
            "maxSize": quota_bytes,
            "maxObjects": settings.deployment_bucket_max_objects,
        },
        cors_rules=BUCKET_CORS_RULES,
        lifecycle_rules=None if has_lifecycle else BUCKET_DEFAULT_LIFECYCLE_RULES,
    )

    return ObjectStorageCredentials(
        bucket=alias,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
    )


def teardown_object_storage(
    deployment: DeploymentORM,
    *,
    client: GarageAdminClient | None = None,
    settings: CaelusSettings | None = None,
) -> None:
    """Revoke access to this deployment's bucket and hand reclamation to Garage.

    **Order is load-bearing.** The key is deleted first: a key with write access
    can call PutBucketLifecycleConfiguration on its own bucket — that operation
    rides along with `write` and Garage offers no finer grant to withhold it —
    and it replaces the whole configuration. Setting the expiry rule before
    revoking would leave a window in which the tenant could strip it back off.

    The bucket is deliberately not deleted. Garage refuses to delete a non-empty
    bucket, and enumerating an unbounded, tenant-controlled object set inside the
    delete reconcile's budget is not viable. What is left is a drained bucket no
    credential can reach, still carrying its `dep-<id>` alias, which is what
    makes it attributable to this deployment for any later sweep.

    Tolerant of a deployment that never had storage: both steps are skipped when
    there is nothing there.
    """
    settings = settings or get_settings()
    client = client or GarageAdminClient.from_settings(settings)

    key = client.find_key(key_name(deployment))
    if key is not None:
        client.delete_key(key["id"])
        logger.info(
            "Revoked object storage key deployment_id=%s access_key_id=%s",
            deployment.id,
            key["id"],
        )

    bucket = client.find_bucket(bucket_name(deployment))
    if bucket is None:
        return

    days = settings.deployment_bucket_expiry_days
    # Both actions Garage implements, for different residue: Expiration reclaims
    # completed objects, AbortIncompleteMultipartUpload reclaims parts of uploads
    # that never finished. The second is not optional — abandoned parts consume
    # disk while never appearing in a bucket listing, which is exactly how
    # storage leaks invisibly on a node with a history of disk pressure.
    client.update_bucket(
        bucket["id"],
        lifecycle_rules=[
            {
                "ID": "caelus-expire-deleted-deployment",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "Expiration": {"Days": days},
            },
            {
                "ID": "caelus-abort-incomplete-multipart-uploads",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": days},
            },
        ],
    )
    logger.info(
        "Set expiry on deleted deployment's bucket deployment_id=%s bucket=%s days=%s",
        deployment.id,
        bucket_name(deployment),
        days,
    )
