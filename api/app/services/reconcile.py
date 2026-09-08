from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from uuid import UUID

from sqlmodel import Session

from app.config import get_settings
from app.models import DeploymentORM, DeploymentReleaseORM, ProductTemplateVersionORM
from app.provisioner import Provisioner, provisioner as default_provisioner
from app.services import (
    deployment_logs,
    dns,
    object_storage,
    relational_storage,
    template_values,
    var_crypto,
)
from app.services import vars as vars_service
from app.services.loki import DIRECTION_BACKWARD, LokiQueryClient
from app.services.template_values import bytes_to_k8s_size
from app.services.deployments import _get_deployment_orm
from app.services.errors import IntegrityException
from app.services.reconcile_constants import (
    DEPLOYMENT_STATUS_DELETED,
    DEPLOYMENT_STATUS_ERROR,
    DEPLOYMENT_STATUS_PENDING,
    DEPLOYMENT_STATUS_READY,
)

logger = logging.getLogger(__name__)

# Wall-clock budget handed to Helm for install/upgrade/uninstall waits. Chart
# readiness behavior is the chart's own concern, so this is a single
# platform-level timeout rather than a per-template knob.
HELM_TIMEOUT_SEC = 300


def storage_secret_name(deployment: DeploymentORM) -> str:
    """Name of the Secret holding a deployment's object-storage credentials.

    Derived from the release name, so it is stable across reconciles (the Secret
    is updated in place rather than churned) and unique within the namespace.
    """
    return f"{deployment.name}-object-storage"


def database_secret_name(deployment: DeploymentORM) -> str:
    """Name of the Secret holding a deployment's database credentials.

    Stable across reconciles, like the object-storage one, so the Secret is
    updated in place rather than churned.
    """
    return f"{deployment.name}-database"


VARS_SECRET_COMPONENT = "vars"


def vars_secret_labels(deployment: DeploymentORM) -> dict[str, str]:
    return {
        "app.kubernetes.io/managed-by": "caelus",
        "app.kubernetes.io/instance": deployment.name,
        "caelus.dev/component": VARS_SECRET_COMPONENT,
    }


def vars_secret_selector(deployment: DeploymentORM) -> str:
    """Scoped by instance too: a namespace may hold more than one deployment."""
    return (
        f"caelus.dev/component={VARS_SECRET_COMPONENT},"
        f"app.kubernetes.io/instance={deployment.name}"
    )


def vars_secret_name(deployment: DeploymentORM, release: DeploymentReleaseORM) -> str:
    """Name of the Secret holding one release's vars.

    Per `deployment_release`, not per deployment, so a Helm rollback lands on a
    Secret this apply never touched. See design.md D10.
    """
    return f"{deployment.name}-vars-{release.number}"


@dataclass(frozen=True)
class ReconcileResult:
    status: str
    applied_template_id: int | None
    last_error: str | None
    last_reconcile_at: datetime | None
    # Helm's revision number for the release this reconcile applied, recorded
    # on the `deployment_release` row. None on the delete path and on any
    # failure that never reached Helm.
    helm_revision: int | None = None


class DeploymentReconciler:
    """Reconcile a single deployment state against Kubernetes/Helm."""

    def __init__(
        self,
        *,
        session: Session,
        provisioner: Provisioner | None = None,
        dns_provider: dns.DnsProvider | None = None,
    ) -> None:
        self._session = session
        self._provisioner = provisioner or default_provisioner
        self._dns_provider = dns_provider

    def _dns(self) -> dns.DnsProvider:
        if self._dns_provider is None:
            self._dns_provider = dns.from_settings()
        return self._dns_provider

    def reconcile(self, deployment_id: UUID) -> ReconcileResult:
        logger.info("Starting reconcile for deployment_id=%s", deployment_id)
        deployment = _get_deployment_orm(self._session, deployment_id=deployment_id)
        release: DeploymentReleaseORM | None = None
        try:
            # The reconciler creates no releases. It applies the one the request
            # that asked for this rollout already recorded, and is
            # level-triggered: it reads `desired_release_id` as it stands now,
            # not as it stood when the request landed.
            #
            # Nothing is claimed on the delete path -- an uninstall is not a
            # rollout of a release, and the desired release must not be marked
            # as having been applied by one.
            if deployment.deleted_at is None:
                release = self._claim_desired_release(deployment)
            self._validate_input_state(deployment)
            if deployment.deleted_at is not None:
                result = self._reconcile_delete(deployment)
            else:
                assert release is not None
                result = self._reconcile_apply(deployment, release)
        except Exception as exc:
            logger.exception("Reconcile failed for deployment_id=%s", deployment_id)
            last_error = str(exc)
            if release is not None:
                last_error = self._with_release_output(last_error, deployment, release)
            result = ReconcileResult(
                status=DEPLOYMENT_STATUS_ERROR,
                applied_template_id=deployment.applied_template_id,
                last_error=last_error,
                last_reconcile_at=datetime.now(UTC),
            )
        # Both paths, success and failure, in the same transaction as the
        # deployment's own status below.
        if release is not None:
            self._record_release_outcome(release, result)
        deployment.status = result.status
        deployment.applied_template_id = result.applied_template_id
        deployment.last_error = result.last_error
        deployment.last_reconcile_at = result.last_reconcile_at
        if release is not None and result.status == DEPLOYMENT_STATUS_READY:
            # On success only. On failure this is left untouched, which is
            # *correct* rather than a missed update: `--atomic` has already
            # rolled back to the previously applied release, so the value it
            # still names is the one actually running. Nobody has to notice
            # that a rollback happened and write a transition.
            deployment.applied_release_id = release.id
        self._session.add(deployment)
        self._session.commit()
        self._session.refresh(deployment)
        logger.info(
            "Finished reconcile for deployment_id=%s status=%s applied_template_id=%s "
            "release_id=%s helm_revision=%s",
            deployment_id,
            result.status,
            result.applied_template_id,
            None if release is None else release.id,
            result.helm_revision,
        )
        return result

    @staticmethod
    def _with_release_output(
        message: str, deployment: DeploymentORM, release: DeploymentReleaseORM
    ) -> str:
        """Append the failed release's own output to the error the user will see.

        This works *only* because the lines outlive the pod that wrote them.
        Helm runs with `--atomic`, so a rollout whose pods crash on startup is
        rolled back and those pods deleted before anyone can ask -- reaching for
        the pod here would race the thing it wants to observe and usually lose.
        Promtail shipped the lines seconds earlier, so a query issued *after*
        the rollback still finds them.

        Appended after `str(exc)` rather than folded into it, and that ordering
        matters: `AdapterCommandError._build_message` truncates Helm's own
        detail at 400 characters (`app/proc.py`) while building the exception,
        long before this runs. A tail added here is past that cut and survives
        it.

        Best effort throughout. A log store that is down, unconfigured or empty
        must not turn a reported deployment failure into a different, less
        useful one -- the Helm error is the thing the user actually needs.
        """
        settings = get_settings()
        try:
            started = release.started_at
            if started is None:
                return message
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            target = deployment_logs.LogTarget(
                deployment_id=str(deployment.id),
                namespace=deployment.namespace,
                name=deployment.name,
                # Pinned where the chart labels its pods, so a rollout that
                # overlapped the previous release's still-running pods cannot
                # report the wrong release's output. Where it does not, the
                # deployment selector bounded by this release's start time is
                # the closest honest answer.
                release_id=(
                    str(release.id)
                    if deployment_logs._renders_release_labels(deployment)
                    else None
                ),
            )
            entries = LokiQueryClient.from_settings(settings).query_range(
                query=deployment_logs.build_selector(target),
                start_ns=int(started.timestamp() * deployment_logs.NS_PER_SECOND),
                limit=settings.log_failure_tail_lines,
                direction=DIRECTION_BACKWARD,
            )
        except Exception:
            logger.warning(
                "Could not fetch failed release output for deployment_id=%s release=%s",
                deployment.id,
                release.id,
                exc_info=True,
            )
            return message
        if not entries:
            return message
        tail = "\n".join(entry.line for entry in entries)
        return (
            f"{message}\n\n"
            f"Application output (release {release.number}, last {len(entries)} lines):\n"
            f"{tail}"
        )

    def _claim_desired_release(self, deployment: DeploymentORM) -> DeploymentReleaseORM:
        """Mark the desired release as started, and commit that before Helm runs.

        Committed early on purpose. The point of `started_at` is that a worker
        killed mid-Helm leaves a release with a start and no end -- evidence
        that work began and was abandoned. Deferring the write to the end of
        the reconcile would lose exactly the case it exists to record.

        Write-if-null, so a lease reclaim after a worker died records when work
        *first* began rather than when the retry did. How many attempts there
        were is `deployment_reconcile_job.attempt`; it is not something to
        infer from here.
        """
        release = self._session.get(DeploymentReleaseORM, deployment.desired_release_id)
        if release is None:
            # Not a reachable state: `desired_release_id` is NOT NULL behind a
            # foreign key. Loud rather than silently applying nothing.
            raise IntegrityException("Deployment's desired release is missing")
        if release.started_at is None:
            release.started_at = datetime.now(UTC)
            self._session.add(release)
            self._session.commit()
        return release

    @staticmethod
    def _record_release_outcome(
        release: DeploymentReleaseORM, result: ReconcileResult
    ) -> None:
        """Write the release's outcome, once.

        These three are never rewritten: a failed reconcile is terminal
        (`mark_job_failed` never re-enqueues), and a reclaimed job is by
        definition one that never wrote them. `started_at` is deliberately not
        touched here -- see `_claim_desired_release`.
        """
        release.ended_at = result.last_reconcile_at or datetime.now(UTC)
        release.error = result.last_error
        release.helm_revision = result.helm_revision

    @staticmethod
    def _validate_input_state(deployment: DeploymentORM) -> None:
        if deployment.status == DEPLOYMENT_STATUS_PENDING:
            raise IntegrityException("Deployment is awaiting payment and cannot be reconciled")
        if not deployment.name:
            raise IntegrityException("Deployment is missing name")
        if not deployment.namespace:
            raise IntegrityException("Deployment is missing namespace")
        if deployment.user is None:
            raise IntegrityException("Deployment is missing loaded user relationship")
        if not deployment.user.subdomain:
            # No name to issue a certificate for, so no deployment. The API
            # refuses to create one for such an account; reaching here means a
            # row that predates that rule.
            raise IntegrityException(
                "Deployment's owner has not claimed a subdomain, so no certificate "
                "can cover its applications"
            )
        if deployment.desired_template is None:
            raise IntegrityException("Deployment is missing loaded desired_template relationship")
        template = deployment.desired_template
        if template.deleted_at is not None:
            raise IntegrityException("Desired template is deleted")
        if template.chart_ref is None or template.chart_version is None:
            raise IntegrityException("Desired template chart_ref and chart_version are required")
        if template.product is None:
            raise IntegrityException("Desired template is missing loaded product relationship")

    def _reconcile_apply(
        self, deployment: DeploymentORM, release: DeploymentReleaseORM
    ) -> ReconcileResult:
        template = deployment.desired_template
        assert template is not None

        template_values.validate_user_values(deployment.user_values_json, template.values_schema_json)

        logger.debug(
            "Applying deployment_id=%s release=%s namespace=%s template_id=%s",
            deployment.id,
            deployment.name,
            deployment.namespace,
            deployment.desired_template_id,
        )

        self._ensure_account_dns(deployment)

        self._provisioner.ensure_namespace(name=deployment.namespace)
        self._provisioner.ensure_tenant_isolation(namespace=deployment.namespace)

        # After the namespace exists, because the credentials Secret is written
        # into it; after the isolation jail, which nothing may precede; and
        # before Helm, so no pod ever starts expecting a Secret that is not
        # there yet. The values depend on what provisioning returns, so they are
        # built here rather than at the top.
        storage = self._ensure_object_storage(deployment)
        database = self._ensure_database(deployment)
        vars_secret = self._ensure_vars_secret(deployment, release)
        merged_values = self._build_merged_values(
            deployment,
            template,
            release=release,
            storage=storage,
            database=database,
            vars_secret=vars_secret,
        )

        outcome = self._provisioner.helm_upgrade_install(
            release_name=deployment.name,
            namespace=deployment.namespace,
            chart_ref=template.chart_ref,
            chart_version=template.chart_version,
            chart_digest=template.chart_digest,
            values=merged_values,
            timeout=HELM_TIMEOUT_SEC,
            atomic=True,
            wait=True,
        )

        # After Helm succeeds only: a rollback leaves the previous release's
        # Secret live, and reaping here would delete it.
        self._reap_vars_secrets(deployment, keep=vars_secret)

        return ReconcileResult(
            status=DEPLOYMENT_STATUS_READY,
            applied_template_id=deployment.desired_template_id,
            last_error=None,
            last_reconcile_at=datetime.now(UTC),
            # getattr rather than attribute access: a provisioner double may
            # return nothing, and a missing revision is not worth failing an
            # otherwise successful apply over.
            helm_revision=getattr(outcome, "revision", None),
        )

    def _ensure_account_dns(self, deployment: DeploymentORM) -> None:
        """Ensure the wildcard record for the owner's subdomain.

        Kept even though the current provider makes it redundant. Issuing the
        account's certificate writes a challenge record beneath its name, and on
        an RFC 4592-conformant server that stops `*.<domain>` answering for
        anything under it -- leaving only this record. Cloudflare does not apply
        that rule to empty non-terminals (measured 2026-09-08), so the hazard is
        latent, not absent: confirming it does not reproduce today is not a
        reason to remove the record.

        First, and before any certificate work, for the same reason.
        """
        account = self._account_fqdn(deployment)
        self._dns().ensure_wildcard_record(account)

    @staticmethod
    def _account_fqdn(deployment: DeploymentORM) -> str:
        settings = get_settings()
        if not settings.domain:
            raise IntegrityException("No platform domain is configured")
        return f"{deployment.user.subdomain}.{settings.domain}"

    def _reconcile_delete(self, deployment: DeploymentORM) -> ReconcileResult:
        logger.debug(
            "Deleting deployment_id=%s release=%s namespace=%s",
            deployment.id,
            deployment.name,
            deployment.namespace,
        )
        if object_storage.is_enabled(deployment):
            object_storage.teardown_object_storage(deployment)
        if relational_storage.is_enabled(deployment):
            relational_storage.teardown_database(self._session, deployment)

        self._provisioner.helm_uninstall(
            release_name=deployment.name,
            namespace=deployment.namespace,
            timeout=HELM_TIMEOUT_SEC,
            wait=True,
        )
        self._provisioner.delete_namespace(name=deployment.namespace)

        return ReconcileResult(
            status=DEPLOYMENT_STATUS_DELETED,
            applied_template_id=deployment.applied_template_id,
            last_error=None,
            last_reconcile_at=datetime.now(UTC),
        )

    def _ensure_object_storage(
        self, deployment: DeploymentORM
    ) -> object_storage.ObjectStorageCredentials | None:
        """Provision the deployment's bucket and publish its credentials.

        Returns ``None`` for a product that has not opted in, which is what the
        storage overrides key off so that such a deployment carries no storage
        block at all.

        The secret access key goes **straight into a Kubernetes Secret and never
        into the Helm values**. Merged values are logged in full at INFO by the
        provisioner and are persisted by Helm into a release Secret in the
        tenant's own namespace; a credential routed through them would be
        written to the log aggregator and to a tenant-namespace object on every
        reconcile.
        """
        if not object_storage.is_enabled(deployment):
            return None

        credentials = object_storage.ensure_object_storage(deployment)
        settings = get_settings()
        self._provisioner.upsert_secret(
            namespace=deployment.namespace,
            name=storage_secret_name(deployment),
            string_data={
                # The conventional names an S3 SDK already recognizes, so a
                # tenant's default client works with no configuration. Both
                # endpoint spellings because SDKs differ on which they read.
                "AWS_ACCESS_KEY_ID": credentials.access_key_id,
                "AWS_SECRET_ACCESS_KEY": credentials.secret_access_key,
                "AWS_REGION": settings.s3_region,
                "AWS_DEFAULT_REGION": settings.s3_region,
                "AWS_ENDPOINT_URL": settings.s3_endpoint_url,
                "AWS_ENDPOINT_URL_S3": settings.s3_endpoint_url,
                "S3_BUCKET": credentials.bucket,
                "BUCKET_NAME": credentials.bucket,
            },
            labels={
                "app.kubernetes.io/managed-by": "caelus",
                "app.kubernetes.io/instance": deployment.name,
                "caelus.dev/component": "object-storage",
            },
        )
        return credentials

    def _ensure_database(
        self, deployment: DeploymentORM
    ) -> relational_storage.DatabaseCredentials | None:
        """Provision the deployment's database and publish its credentials.

        Returns ``None`` for a product that has not opted in, which is what the
        database overrides key off so such a deployment carries no database
        block at all.

        The password goes straight into a Kubernetes Secret and never into the
        Helm values, for the reason spelled out in ``_ensure_object_storage``.
        """
        if not relational_storage.is_enabled(deployment):
            return None

        credentials = relational_storage.ensure_database(self._session, deployment)
        self._provisioner.upsert_secret(
            namespace=deployment.namespace,
            name=database_secret_name(deployment),
            string_data={
                # The URL covers every ORM; the discrete variables are what
                # libpq, psql and pg_dump read unaided.
                "DATABASE_URL": credentials.url,
                "PGHOST": credentials.host,
                "PGPORT": str(credentials.port),
                "PGUSER": credentials.user,
                "PGPASSWORD": credentials.password,
                "PGDATABASE": credentials.database,
            },
            labels={
                "app.kubernetes.io/managed-by": "caelus",
                "app.kubernetes.io/instance": deployment.name,
                "caelus.dev/component": "database",
            },
        )
        return credentials

    def _ensure_vars_secret(
        self, deployment: DeploymentORM, release: DeploymentReleaseORM
    ) -> str | None:
        """Publish a release's vars as a Secret. Returns its name, or None.

        The release's snapshot, not head. Decrypts everything before writing
        anything, so an unreadable row writes no Secret rather than a partial
        one. Values never enter the Helm values -- see `_ensure_object_storage`.
        """
        snapshot = vars_service.snapshot(self._session, release.id)
        if not snapshot:
            return None

        name = vars_secret_name(deployment, release)
        string_data = {
            row.key: var_crypto.decrypt(row.value_encrypted, row.key_id) for row in snapshot
        }
        self._provisioner.upsert_secret(
            namespace=deployment.namespace,
            name=name,
            string_data=string_data,
            labels=vars_secret_labels(deployment),
        )
        logger.debug(
            "Published %d vars for deployment_id=%s release=%s",
            len(string_data),
            deployment.id,
            release.number,
        )
        return name

    def _reap_vars_secrets(self, deployment: DeploymentORM, keep: str | None) -> None:
        """Drop superseded vars Secrets. Best-effort: leftovers are only litter."""
        try:
            self._provisioner.delete_secrets_by_label(
                namespace=deployment.namespace,
                selector=vars_secret_selector(deployment),
                except_name=keep,
            )
        except Exception:  # noqa: BLE001 - never fail a good rollout over cleanup
            logger.warning(
                "Failed to reap superseded vars Secrets for deployment_id=%s",
                deployment.id,
                exc_info=True,
            )

    def _build_merged_values(
        self,
        deployment: DeploymentORM,
        template: ProductTemplateVersionORM,
        *,
        release: DeploymentReleaseORM,
        storage: object_storage.ObjectStorageCredentials | None = None,
        database: relational_storage.DatabaseCredentials | None = None,
        vars_secret: str | None = None,
    ) -> dict:
        template_values.validate_user_values(deployment.user_values_json, template.values_schema_json)
        system_overrides = self._build_system_overrides(
            deployment,
            release=release,
            storage=storage,
            database=database,
            vars_secret=vars_secret,
        )
        return template_values.merge_values_scoped(
            template.system_values_json,
            deployment.user_values_json,
            system_overrides,
        )

    @classmethod
    def _build_system_overrides(
        cls,
        deployment: DeploymentORM,
        *,
        release: DeploymentReleaseORM,
        storage: object_storage.ObjectStorageCredentials | None = None,
        database: relational_storage.DatabaseCredentials | None = None,
        vars_secret: str | None = None,
    ) -> dict | None:
        """Combine all system-controlled value overrides under the ``caelus`` namespace.

        Each contributor returns a ``{"caelus": {...}}`` fragment; they are deep-merged
        so e.g. ``caelus.plan`` and ``caelus.ingress`` coexist. Returns ``None`` when nothing
        is contributed (preserving prior behaviour for plan-less, hostname-less releases).
        """
        overrides: dict = {}
        for part in (
            cls._build_plan_overrides(deployment),
            cls._build_ingress_overrides(deployment),
            cls._build_owner_overrides(deployment),
            cls._build_object_storage_overrides(deployment, storage),
            cls._build_database_overrides(deployment, database),
            cls._build_vars_overrides(vars_secret),
            cls._build_release_overrides(release),
            cls._build_ssh_overrides(),
        ):
            if part:
                overrides = template_values.deep_merge(overrides, part)
        return overrides or None

    @staticmethod
    def _build_ssh_overrides() -> dict | None:
        """The platform SSH key every sidecar trusts, from per-environment settings."""
        key = get_settings().sftp_platform_public_key.strip()
        return {"caelus": {"ssh": {"platformPublicKey": key}}} if key else None

    @staticmethod
    def _build_vars_overrides(vars_secret: str | None) -> dict | None:
        """Project the Secret's name only; values never enter the Helm values.

        No block at all when the release carries no vars, so a chart that
        requires them fails loudly instead of rendering an empty `envFrom`.
        """
        if vars_secret is None:
            return None
        return {"caelus": {"vars": {"secretName": vars_secret}}}

    @staticmethod
    def _build_release_overrides(release: DeploymentReleaseORM) -> dict:
        return {
            "caelus": {
                "releaseId": str(release.id),
                "releaseNumber": str(release.number),
            }
        }

    @staticmethod
    def _build_object_storage_overrides(
        deployment: DeploymentORM,
        storage: object_storage.ObjectStorageCredentials | None,
    ) -> dict | None:
        """Project object-storage *references* into the ``caelus.objectStorage`` namespace.

        References only — the bucket, the endpoint, the region and the name of
        the Secret holding the credentials. The secret access key is deliberately
        absent: see ``_ensure_object_storage``. A chart reads the Secret by name
        with ``envFrom``; nothing needs the credential to pass through here.

        No ``enabled`` flag here: that is the chart's own top-level
        ``objectStorage.enabled``, a static product declaration coming from the
        catalog's system values. These are the per-deployment runtime facts, and
        keeping the two apart is what makes "what did the platform inject?"
        answerable at a glance.

        Emits no block at all for a product that has not opted in, so such a
        deployment renders exactly as it did before.
        """
        if storage is None:
            return None
        settings = get_settings()
        return {
            "caelus": {
                "objectStorage": {
                    "bucket": storage.bucket,
                    "endpoint": settings.s3_endpoint_url,
                    "region": settings.s3_region,
                    "secretName": storage_secret_name(deployment),
                }
            }
        }

    @staticmethod
    def _build_database_overrides(
        deployment: DeploymentORM,
        database: relational_storage.DatabaseCredentials | None,
    ) -> dict | None:
        """Project database *references* into the ``caelus.database`` namespace.

        References only -- the password is deliberately absent; see
        ``_ensure_database``. The host and port are the pooler's, which is the
        only route a tenant pod has to a database.

        No ``enabled`` flag here: that is the chart's own top-level
        ``relationalStorage.enabled``, a static product declaration from the
        catalog's system values.
        """
        if database is None:
            return None
        return {
            "caelus": {
                "database": {
                    "host": database.host,
                    "port": database.port,
                    "name": database.database,
                    "user": database.user,
                    "secretName": database_secret_name(deployment),
                }
            }
        }

    @staticmethod
    def _build_owner_overrides(deployment: DeploymentORM) -> dict | None:
        """Project the owning user's identity into the ``caelus.owner`` namespace.

        Fields are only included when present, and no block is emitted when neither
        is, so charts that require one fail loudly rather than rendering a blank.
        """
        user = getattr(deployment, "user", None)
        if user is None:
            return None
        owner: dict = {}
        email = getattr(user, "email", None)
        if email:
            owner["email"] = email
        user_id = getattr(user, "id", None)
        if user_id is not None:
            owner["id"] = user_id
        return {"caelus": {"owner": owner}} if owner else None

    @staticmethod
    def _build_ingress_overrides(deployment: DeploymentORM) -> dict | None:
        """Project system ingress + TLS settings into the ``caelus.ingress`` namespace.

        ``caelus.ingress.enabled`` marks that the platform exposes this deployment via an
        Ingress (true for any hostname-bearing deployment); ``caelus.ingress.host`` is the
        routing host and cert SAN. ``caelus.ingress.tls`` carries only the cert strategy:
        hosts under a configured wildcard domain (``*.freepod.eu``) are served by Traefik's
        default certificate store (``wildcard: true``, no per-app cert), while custom
        domains get a per-app HTTP-01 certificate via cert-manager (issuer + secret name
        injected here). Deployments without a hostname get no block at all.
        """
        hostname = deployment.hostname
        if not hostname:
            return None
        settings = get_settings()
        host = hostname.lower()
        is_wildcard = any(
            host == domain or host.endswith(f".{domain}")
            for domain in settings.wildcard_domains
        )
        tls: dict = {"wildcard": is_wildcard}
        if not is_wildcard:
            tls["issuer"] = settings.tls_cluster_issuer
            tls["secretName"] = f"{deployment.name}-tls"
        return {"caelus": {"ingress": {"enabled": True, "host": host, "tls": tls}}}

    @staticmethod
    def _build_plan_overrides(deployment: DeploymentORM) -> dict | None:
        """Project plan-level constraints into the caelus.plan Helm values namespace.

        Always injects ``caelus.plan`` when the deployment has a subscription so
        that chart templates using ``| default`` fail loudly if the key is
        unexpectedly absent (indicating a reconciler bug). Storage fields are
        only included when the plan defines a positive storage quota.
        """
        if not deployment.subscription or not deployment.subscription.plan_template:
            return None
        plan_values: dict = {}
        storage_bytes = deployment.subscription.plan_template.storage_bytes
        if storage_bytes:
            plan_values["storageBytes"] = storage_bytes
            plan_values["storageSize"] = bytes_to_k8s_size(storage_bytes)
        return {"caelus": {"plan": plan_values}}
