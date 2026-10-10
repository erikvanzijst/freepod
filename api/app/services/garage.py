"""Thin transport over the Garage administration API.

Deliberately free of deployment and reconcile concepts: this module knows about
buckets, access keys, grants, quotas and rules, and nothing about who they are
for. The per-deployment policy — naming, quota resolution, teardown ordering —
lives in ``object_storage.py``.

Two shapes to be aware of, both of which cost real time to rediscover:

* **Request bodies are not uniformly camelCase.** Top-level fields are
  (``globalAlias``, ``lifecycleRules``, ``corsRules``), but the *contents* of
  lifecycle and CORS rules are the S3 XML shapes verbatim — ``AllowedOrigin``,
  ``Expiration``, ``ID``. Garage passes them straight through to the same
  structures the S3 API uses.

* **Not every credential can be read back.** An access key's secret can
  (``GetKeyInfo?showSecretKey=true``), which is what makes provisioning
  re-runnable without rotating anything. An admin token's cannot — it is shown
  once at creation — which is why this module never tries to.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import CaelusSettings, get_settings
from app.services.errors import CaelusException

logger = logging.getLogger(__name__)

# The admin API is plain HTTP on an in-cluster Service and every call here is a
# small JSON document, so this only ever has to cover a hung node, not a slow
# transfer. Short enough that a reconcile fails inside its own budget rather
# than being killed by the lease.
ADMIN_TIMEOUT_SEC = 15.0


class GarageException(CaelusException):
    """An admin API call failed, or the store is not configured."""


class GarageAdminClient:
    """Client for the Garage v2 administration API.

    Every lookup returns ``None`` for "not there" rather than raising, because
    provisioning reads before it writes at each step and absence is the normal
    first-run answer, not an error.
    """

    def __init__(self, *, base_url: str, token: str, client: httpx.Client | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = client

    @classmethod
    def from_settings(cls, settings: CaelusSettings | None = None) -> GarageAdminClient:
        settings = settings or get_settings()
        missing = [
            name
            for name in ("garage_admin_url", "garage_admin_token")
            if not getattr(settings, name)
        ]
        if missing:
            raise GarageException(
                "Garage admin API is not configured: missing " + ", ".join(sorted(missing))
            )
        return cls(base_url=settings.garage_admin_url, token=settings.garage_admin_token)

    # --- transport ---------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        params: dict[str, str] | None = None,
        missing_ok: bool = False,
    ) -> Any:
        """Issue one admin API call.

        With ``missing_ok``, a 404 answers ``None``: Garage reports a missing
        key or bucket with that status, so it is told apart from an unwell
        store without reading the error text.

        Query parameters go through ``params`` so httpx encodes them, rather
        than being interpolated into ``path``. Every id passed here today is
        minted by Garage and is plain hex, so nothing currently needs escaping —
        but that is a property of the callers, not of this function, and the
        next caller should not have to know it.
        """
        request_args: dict[str, Any] = {
            "headers": {"Authorization": f"Bearer {self._token}"},
        }
        if body is not None:
            request_args["json"] = body
        if params is not None:
            request_args["params"] = params

        try:
            if self._client is not None:
                response = self._client.request(method, f"{self._base_url}{path}", **request_args)
            else:
                with httpx.Client(timeout=ADMIN_TIMEOUT_SEC) as client:
                    response = client.request(method, f"{self._base_url}{path}", **request_args)
        except httpx.HTTPError as exc:
            raise GarageException(f"Garage admin API {method} {path} failed: {exc}") from exc

        if missing_ok and response.status_code == 404:
            return None
        if response.status_code < 200 or response.status_code >= 300:
            # The body carries Garage's own message, which is the only thing that
            # says *why*; without it the caller sees a bare status code and a
            # deployment error nobody can act on.
            raise GarageException(
                f"Garage admin API {method} {path} returned HTTP "
                f"{response.status_code}: {response.text.strip()}"
            )

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise GarageException(
                f"Garage admin API {method} {path} returned a non-JSON body"
            ) from exc

    # --- buckets -----------------------------------------------------------

    def find_bucket(self, global_alias: str) -> dict[str, Any] | None:
        """The bucket carrying ``global_alias``, or ``None``.

        Uses ``ListBuckets`` and filters client-side rather than
        ``GetBucketInfo?globalAlias=``, because the latter answers a missing
        bucket with an error status and this has to distinguish "absent" from
        "the store is unwell" without parsing error text.
        """
        for bucket in self._request("GET", "/v2/ListBuckets") or []:
            if global_alias in (bucket.get("globalAliases") or []):
                return bucket
        return None

    def get_bucket_by_alias(self, global_alias: str) -> dict[str, Any] | None:
        """``GetBucketInfo`` by global alias, or ``None`` when there is none.

        One call, where ``find_bucket`` lists every bucket on the instance.
        """
        return self._request(
            "GET", "/v2/GetBucketInfo", params={"globalAlias": global_alias}, missing_ok=True
        )

    def get_bucket(self, bucket_id: str) -> dict[str, Any]:
        return self._request("GET", "/v2/GetBucketInfo", params={"id": bucket_id})

    def create_bucket(self, global_alias: str) -> dict[str, Any]:
        """Create a bucket with a global alias.

        A *global* alias on purpose. A key-local alias would be deleted along
        with its key, leaving the bucket anonymous exactly when teardown needs
        to identify it — see design D3.
        """
        return self._request("POST", "/v2/CreateBucket", {"globalAlias": global_alias})

    def update_bucket(
        self,
        bucket_id: str,
        *,
        quotas: dict[str, int] | None = None,
        cors_rules: list[dict[str, Any]] | None = None,
        lifecycle_rules: list[dict[str, Any]] | None = None,
    ) -> None:
        """Apply bucket configuration. One call, one round trip.

        All three are siblings in a single request body, which is why quotas and
        CORS are set together at provisioning time rather than in two calls. An
        omitted field is left untouched; a supplied one is assigned **wholesale**
        rather than merged, so re-running converges instead of accumulating
        rules. An empty rule list clears that configuration.

        ``quotas`` must carry both ``maxSize`` and ``maxObjects``: Garage
        rejects changing one without the other.

        Rule contents use S3's XML field names — ``AllowedOrigin``,
        ``ExposeHeader``, ``ID``, ``Expiration`` — not camelCase.
        """
        body: dict[str, Any] = {}
        if quotas is not None:
            body["quotas"] = quotas
        if cors_rules is not None:
            body["corsRules"] = cors_rules
        if lifecycle_rules is not None:
            body["lifecycleRules"] = lifecycle_rules
        if not body:
            return
        self._request("POST", "/v2/UpdateBucket", body, params={"id": bucket_id})

    # --- access keys -------------------------------------------------------

    def find_key(self, name: str) -> dict[str, Any] | None:
        """The access key named ``name``, or ``None``. Does not include the secret."""
        for key in self._request("GET", "/v2/ListKeys") or []:
            if key.get("name") == name:
                return key
        return None

    def get_key_by_name(self, name: str, *, show_secret: bool = False) -> dict[str, Any] | None:
        """``GetKeyInfo`` for the key named ``name``, or ``None``.

        One call, where ``find_key`` lists every key. ``search`` also matches a
        partial name or key id, so the result is only trusted when its name is
        exactly the one asked for.
        """
        params = {"search": name}
        if show_secret:
            params["showSecretKey"] = "true"
        key = self._request("GET", "/v2/GetKeyInfo", params=params, missing_ok=True)
        if key is None or key.get("name") != name:
            return None
        return key

    def get_key_secret(self, access_key_id: str) -> str:
        """Read an existing key's secret back.

        This is what lets provisioning be idempotent without rotating a live
        credential: the secret is returned at creation *and* on demand here, so
        a re-run can rewrite the same Secret rather than mint a new key.
        """
        info = self._request(
            "GET", "/v2/GetKeyInfo", params={"id": access_key_id, "showSecretKey": "true"}
        )
        secret = info.get("secretAccessKey")
        if not secret:
            raise GarageException(
                f"Garage did not return a secret for access key {access_key_id}"
            )
        return secret

    def create_key(self, name: str) -> dict[str, Any]:
        """Create a non-expiring access key.

        ``allow`` is deliberately not sent, so the key is created with
        ``createBucket: false`` — it can use the buckets it is granted and
        cannot make more.
        """
        return self._request("POST", "/v2/CreateKey", {"name": name, "neverExpires": True})

    def delete_key(self, access_key_id: str) -> None:
        self._request("POST", "/v2/DeleteKey", params={"id": access_key_id})

    def allow_bucket_key(
        self, *, bucket_id: str, access_key_id: str, read: bool = True, write: bool = True
    ) -> None:
        """Grant permissions on a bucket to a key.

        **This can only widen a grant.** Garage documents the endpoint's
        semantics as unconventional: flags set ``true`` are activated and flags
        set ``false`` are *ignored*, not revoked. Do not call this with ``false``
        expecting to take a permission away — that is ``DenyBucketKey``.

        ``owner`` is never granted: it carries bucket administration, and the
        platform administers buckets through the admin API instead.
        """
        self._request(
            "POST",
            "/v2/AllowBucketKey",
            {
                "bucketId": bucket_id,
                "accessKeyId": access_key_id,
                "permissions": {"read": read, "write": write},
            },
        )
