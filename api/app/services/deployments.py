from __future__ import annotations
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from sqlmodel import Session, select

from app.models import (
    BuildORM,
    DeploymentCreate,
    DeploymentORM,
    DeploymentRead,
    DeploymentReleaseORM,
    DeploymentReleaseWithBuildRead,
    MolliePaymentORM,
    MolliePaymentStatus,
    PaymentStatus,
    PlanTemplateVersionORM,
    DeploymentDatabaseRead,
    ProductTemplateVersionORM,
    SftpCredentialsRead,
    UserORM,
    DeploymentUpdate,
)
from app.services.jobs import JobService
from app.services import relational_storage
from app.services import ssh_keys as ssh_keys_service
from app.services import subscriptions as subscription_service
from app.services import template_values
from app.services import vars as vars_service
from app.services.errors import CaelusException, DeploymentInProgressException, IntegrityException, NotFoundException, ValidationException
from app.services.hostnames import (
    require_owned_subdomain,
    require_valid_hostname_for_deployment,
)
from app.util import set_value_at_path, value_for_path
from app.config import get_settings
from app.provisioner import Provisioner, provisioner as default_provisioner
from app.services.mollie import PaymentProvider
from app.services.reconcile_constants import (
    DEPLOYMENT_STATUS_DELETING,
    DEPLOYMENT_STATUS_ERROR,
    DEPLOYMENT_STATUS_PENDING,
    DEPLOYMENT_STATUS_PROVISIONING,
    DEPLOYMENT_STATUS_READY,
    JOB_REASON_CREATE,
    JOB_REASON_DELETE,
    JOB_REASON_UPDATE,
    DEPLOYMENT_STATUS_DELETED,
)
from app.services.reconcile_naming import generate_deployment_name, generate_deployment_namespace
from app.util import amend_url


@dataclass
class DeploymentCreateResult:
    deployment: DeploymentRead
    checkout_url: str | None = None

logger = logging.getLogger(__name__)


def _enqueue_reconcile_job(session: Session, *, deployment_id: UUID, reason: str) -> None:
    logger.debug("Queueing reconcile job deployment_id=%s reason=%s", deployment_id, reason)
    JobService(session).enqueue_job(deployment_id=deployment_id, reason=reason)


def _get_deployment_orm(
    session: Session,
    *,
    deployment_id: UUID,
    user_id: int | None = None,
) -> DeploymentORM:
    stmt = select(DeploymentORM).where(DeploymentORM.id == deployment_id)
    if user_id is not None:
        stmt = stmt.where(DeploymentORM.user_id == user_id)
    if not (deployment := session.exec(stmt).one_or_none()):
        raise NotFoundException("Deployment not found")
    return deployment


def _validate_build_reference(session: Session, *, user_id: int, build_id: UUID | None) -> None:
    """Reject a build the caller does not own, at the write.

    Ownership is the *only* condition. Nothing here compares the build against
    the deployment's user values: `image` is a value of the `custom` chart
    rather than a platform concept, most products build nothing, and a build or
    release may come to carry more than one image. Tying the ledger to one
    chart's value key would make the release record an artifact of that chart's
    schema. See design § D4.

    "Not yours" and "does not exist" answer identically, so the endpoint cannot
    be used to probe for other users' builds -- the same rule `builds.py`'s
    `_get_build_orm` applies.
    """
    if build_id is None:
        return
    build = session.get(BuildORM, build_id)
    if build is None or build.user_id != user_id:
        raise ValidationException("Unknown build")


def _next_release_number(session: Session, *, deployment_id: UUID) -> int:
    """The next per-deployment release number, 1 for a deployment's first.

    `max + 1` is safe rather than racy because writes against one deployment
    already serialize: `enqueue_job` rejects a second queued-or-running job and
    `update_deployment` requires status ready/error. The unique constraint on
    (deployment_id, number) is what makes that structural instead of a habit --
    a concurrent write loses on the constraint rather than silently reusing a
    number.
    """
    highest = session.exec(
        select(func.max(DeploymentReleaseORM.number)).where(
            DeploymentReleaseORM.deployment_id == deployment_id
        )
    ).one()
    return (highest or 0) + 1


def _validate_user_values(template: ProductTemplateVersionORM, user_values_json: dict[str, Any] | None) -> None:
    template_values.validate_user_values(user_values_json or {}, template.values_schema_json)


def _validate_plan_template(session: Session, plan_template_id: int, product_id: int) -> PlanTemplateVersionORM:
    """Validate that plan_template_id belongs to this product and is canonical.

    Returns the validated PlanTemplateVersionORM so callers can inspect price_cents.
    """
    ptv = session.get(PlanTemplateVersionORM, plan_template_id)
    if not ptv or ptv.deleted_at:
        raise ValidationException(f"Plan template version {plan_template_id} not found or deleted")
    if ptv.plan.product_id != product_id:
        raise ValidationException("Plan template does not belong to this product")
    if ptv.plan.template_id != ptv.id:
        raise ValidationException("Plan template is not the current canonical version for its plan")
    return ptv


def _iter_hostname_paths(schema: Any, path: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    paths: list[tuple[str, ...]] = []
    if isinstance(schema, dict):
        title = schema.get("title")
        if path and isinstance(title, str) and title.lower() == "hostname":
            paths.append(path)

        properties = schema.get("properties")
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if isinstance(key, str):
                    paths.extend(_iter_hostname_paths(child_schema, path + (key,)))

        items = schema.get("items")
        if isinstance(items, dict):
            paths.extend(_iter_hostname_paths(items, path + ("*",)))
        elif isinstance(items, list):
            for child_schema in items:
                paths.extend(_iter_hostname_paths(child_schema, path + ("*",)))

        for schema_key in ("allOf", "anyOf", "oneOf", "prefixItems"):
            variants = schema.get(schema_key)
            if isinstance(variants, list):
                for child_schema in variants:
                    paths.extend(_iter_hostname_paths(child_schema, path))

        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            paths.extend(_iter_hostname_paths(additional, path))

        definitions = schema.get("$defs") or schema.get("definitions")
        if isinstance(definitions, dict):
            for child_schema in definitions.values():
                paths.extend(_iter_hostname_paths(child_schema, path))
    elif isinstance(schema, list):
        for child_schema in schema:
            paths.extend(_iter_hostname_paths(child_schema, path))
    return paths


class SubdomainRequired(ValidationException):
    """Deploying needs the account to hold an address, with a stable `code` so a
    client tells it apart from the Terms of Service refusal."""

    code = "subdomain_required"


def normalize_and_return_hostname(
    *,
    values_schema_json: dict[str, Any] | None,
    user_values_json: dict[str, Any] | None,
) -> str | None:
    """Derive the hostname from user values and normalize it to lowercase.

    When a hostname is found, the lowercased value is written back into
    ``user_values_json`` so that downstream consumers (e.g. the Helm
    reconciler) receive an RFC 1123-compliant value.
    """
    if not isinstance(values_schema_json, dict):
        return None
    for path in _iter_hostname_paths(values_schema_json):
        value = value_for_path(user_values_json, path)
        if value is None:
            return None
        lowered = value.lower() if isinstance(value, str) else str(value).lower()
        set_value_at_path(user_values_json, path, lowered)
        return lowered
    return None


NAMESPACE_ATTEMPTS = 5


def _allocate_namespace(session: Session, *, product_name: str, user_email: str) -> str:
    """A namespace no deployment holds, deleted ones included."""
    for _ in range(NAMESPACE_ATTEMPTS):
        candidate = generate_deployment_namespace(product_name, user_email)
        taken = session.exec(
            select(DeploymentORM.id).where(DeploymentORM.namespace == candidate)
        ).first()
        if taken is None:
            return candidate
        logger.warning("Generated namespace %s is already taken; regenerating", candidate)
    raise CaelusException(
        f"could not allocate a free deployment namespace in {NAMESPACE_ATTEMPTS} attempts"
    )


def create_deployment(
    session: Session,
    *,
    payload: DeploymentCreate,
    payment_provider: PaymentProvider | None = None,
) -> DeploymentCreateResult:
    # ensure that the user exists (need ORM object to read/write mollie_customer_id)
    user = session.get(UserORM, payload.user_id)
    if not user or user.deleted_at:
        raise NotFoundException("User not found")
    # ensure that the template exists and retrieve it to validate product association
    template = session.get(ProductTemplateVersionORM, payload.desired_template_id)
    if not template:
        raise NotFoundException("Template not found")

    # The client must submit the product's current canonical template ID.
    # This acts as a CAS (Compare-And-Swap) guard: the client declares which
    # template schema it built the user_values_json against, and we verify that
    # it's still canonical. Rejects stale submissions if the canonical moved.
    if template.product.template_id != template.id:
        raise IntegrityException(
            "Template is not the current canonical for this product"
        )

    # Pre-flight the user-provided values against the template's schema:
    _validate_user_values(template, payload.user_values_json)
    derived_hostname = normalize_and_return_hostname(
        values_schema_json=template.values_schema_json,
        user_values_json=payload.user_values_json,
    )
    if user.subdomain is None:
        raise SubdomainRequired(
            "An account address must be claimed before deploying"
        )

    if derived_hostname is not None:
        require_owned_subdomain(derived_hostname, subdomain=user.subdomain)
        require_valid_hostname_for_deployment(session, derived_hostname)

    # Validate the plan template: must exist, belong to the same product, and be canonical.
    plan_template: PlanTemplateVersionORM = _validate_plan_template(session, payload.plan_template_id, template.product_id)

    # Terms of Service acceptance is a precondition, recorded separately on the
    # user via POST /api/me/tos-acceptance. Deploying without having accepted is
    # rejected here (defense-in-depth: the two-step flow cannot be skipped by a
    # direct API client).
    if user.tos_accepted_version is None:
        raise ValidationException("Terms of Service must be accepted before deploying")

    # A named build must be the caller's. Ownership only -- see
    # `_validate_build_reference`.
    _validate_build_reference(session, user_id=payload.user_id, build_id=payload.build_id)

    # Determine if this is a paid plan requiring payment.
    is_paid = payment_provider is not None and plan_template.price_cents > 0

    # Pre-generate the deployment UUID so we can use it in the Mollie
    # redirect URL and as an idempotency key before the DB transaction.
    deployment_id = uuid4()
    # ...and the release UUID alongside it, because the two rows reference each
    # other. Knowing both ids up front is what lets the deployment be inserted
    # already naming a release that does not exist yet, with the deferred
    # constraint checked at COMMIT. There is no insert-null-then-update step.
    release_id = uuid4()
    checkout_url: str | None = None

    # --- DB transaction ---
    sub = subscription_service.create_subscription(
        session,
        plan_template_id=payload.plan_template_id,
        user_id=payload.user_id,
        payment_status=PaymentStatus.PENDING if is_paid else PaymentStatus.CURRENT,
        commit=False,
    )
    session.flush()  # ensure sub.id is available

    deployment_name = generate_deployment_name(template.product.name)
    deployment_namespace = _allocate_namespace(
        session, product_name=template.product.name, user_email=user.email
    )
    deployment: DeploymentORM = DeploymentORM.model_validate(
        dict(
            id=deployment_id,
            name=deployment_name,
            namespace=deployment_namespace,
            hostname=derived_hostname,
            status=DEPLOYMENT_STATUS_PENDING if is_paid else DEPLOYMENT_STATUS_PROVISIONING,
            subscription_id=sub.id,
            desired_release_id=release_id,
            # `build_id` and `vars` join `plan_template_id` here: all three are
            # request-only fields that the deployment row does not store. The
            # build lands on the release below; the vars land in their own
            # table, and `vars` never comes back out on a read model.
            **payload.model_dump(exclude={"plan_template_id", "build_id", "vars"}),
        )
    )
    session.add(deployment)
    # The deployment's first release, in this same transaction. Added after the
    # deployment so the flush orders the INSERTs that way: `deployment_release`
    # carries an immediate FK to `deployment`, while the reverse pointer is
    # deferred. Snapshots the *user* values -- system overrides do not exist
    # yet at request time, and the user values are the intent worth keeping.
    session.add(
        DeploymentReleaseORM(
            id=release_id,
            number=1,
            deployment_id=deployment_id,
            template_id=payload.desired_template_id,
            build_id=payload.build_id,
            values_json=payload.user_values_json,
        )
    )
    session.flush()  # ensure deployment.subscription_id is available

    # Vars, and the release's snapshot of them, in this same transaction --
    # which is what stops a first release from rolling out with an empty
    # environment when the caller supplied one. Ahead of the payment call
    # below on purpose: a var the template rejects must not leave a real
    # Mollie payment behind.
    try:
        vars_service.write_vars(
            session, deployment=deployment, actor=user, entries=payload.vars
        )
        vars_service.snapshot_release(
            session, release_id=release_id, deployment_id=deployment_id
        )
    except CaelusException:
        # Explicit rather than relying on the session being closed for us: the
        # deployment and its subscription are already flushed by this point,
        # and a rejected create must leave neither behind.
        session.rollback()
        raise

    if is_paid:
        settings = get_settings()

        # Ensure user has a Mollie customer
        if not user.mollie_customer_id:
            user.mollie_customer_id = payment_provider.ensure_customer(email=user.email,
                                                                       idempotency_key=f"customer_{deployment_id}")

        # Build redirect URL with deployment ID so the dashboard can
        # focus on the new deployment when the user returns from checkout.
        redirect_url = amend_url(settings.mollie_redirect_url, query={"deployment": str(deployment_id)})

        # Create first payment via Mollie
        payment_result = payment_provider.create_first_payment(
            customer_id=user.mollie_customer_id,
            amount_cents=plan_template.price_cents,
            description=deployment.payment_description(),
            redirect_url=redirect_url,
            webhook_url=amend_url(settings.mollie_webhook_base_url, "webhooks/mollie"),
            idempotency_key=f"first_payment_{deployment_id}",
        )
        checkout_url = payment_result.checkout_url
        mollie_payment = MolliePaymentORM(
            subscription_id=sub.id,
            mollie_payment_id=payment_result.payment_id,
            status=MolliePaymentStatus.OPEN,
            sequence_type="first",
            amount_cents=plan_template.price_cents,
        )
        session.add(mollie_payment)


    try:
        session.flush()
        if not is_paid:
            _enqueue_reconcile_job(session, deployment_id=deployment.id, reason=JOB_REASON_CREATE)
        session.commit()
        deployment = _get_deployment_orm(session, deployment_id=deployment.id)
        logger.info(
            "Created deployment id=%s user_id=%s desired_template_id=%s subscription_id=%s paid=%s",
            deployment.id,
            deployment.user_id,
            deployment.desired_template_id,
            deployment.subscription_id,
            is_paid,
        )
        return DeploymentCreateResult(
            deployment=_read_with_vars(session, deployment),
            checkout_url=checkout_url,
        )
    except DeploymentInProgressException:
        session.rollback()
        logger.warning("Create deployment blocked by in-progress reconcile job for user_id=%s", payload.user_id)
        raise
    except IntegrityError as exc:
        session.rollback()
        logger.warning("Deployment create failed due to integrity conflict for user_id=%s", payload.user_id)
        raise IntegrityException("Deployment already exists") from exc


def _read_with_vars(session: Session, deployment: DeploymentORM) -> DeploymentRead:
    """A single-deployment read, carrying head and `pending`.

    Only for reads *of one deployment*. The listing deliberately leaves both
    `None`: head is a query per deployment, and no caller reads vars from a
    listing.
    """
    read = DeploymentRead.model_validate(deployment)
    reported = vars_service.read_vars(session, deployment)
    read.vars = reported.vars
    read.pending = reported.pending
    return read


def list_deployments(session: Session, *, user_id: int | None = None) -> list[DeploymentRead]:
    # Return non-deleted deployments for the given user if provided, otherwise all
    stmt = select(DeploymentORM).where(DeploymentORM.status != DEPLOYMENT_STATUS_DELETED)
    if user_id is not None:
        stmt = stmt.where(DeploymentORM.user_id == user_id)
    return [DeploymentRead.model_validate(d) for d in session.exec(stmt).all()]


def get_deployment(session: Session, *, deployment_id: UUID, user_id: int | None = None) -> DeploymentRead:
    deployment = _get_deployment_orm(
        session,
        user_id=user_id,
        deployment_id=deployment_id,
    )
    if deployment.status == DEPLOYMENT_STATUS_DELETED:
        raise NotFoundException("Deployment not found")
    return _read_with_vars(session, deployment)


def _require_readable_deployment(
    session: Session, *, deployment_id: UUID, user_id: int | None
) -> DeploymentORM:
    """The deployment, or `NotFoundException`.

    Missing, not yours, and deleted answer identically.
    """
    deployment = _get_deployment_orm(session, user_id=user_id, deployment_id=deployment_id)
    if deployment.status == DEPLOYMENT_STATUS_DELETED:
        raise NotFoundException("Deployment not found")
    return deployment


def get_deployment_orm(
    session: Session, *, deployment_id: UUID, user_id: int | None = None
) -> DeploymentORM:
    """The deployment row itself, for callers that need more than a read model.

    Same visibility rules as every other read: missing, not yours, and deleted
    are indistinguishable to the caller.
    """
    return _require_readable_deployment(
        session, deployment_id=deployment_id, user_id=user_id
    )


def list_releases(
    session: Session, *, deployment_id: UUID, user_id: int | None = None
) -> list[DeploymentReleaseWithBuildRead]:
    """A deployment's releases, highest number first, each with its build inlined.

    Every release is returned whatever its outcome. One statement, whatever the
    number of releases.
    """
    _require_readable_deployment(session, deployment_id=deployment_id, user_id=user_id)
    releases = session.exec(
        select(DeploymentReleaseORM)
        .where(DeploymentReleaseORM.deployment_id == deployment_id)
        .order_by(DeploymentReleaseORM.number.desc())  # type: ignore[attr-defined]
        .options(joinedload(DeploymentReleaseORM.build))  # type: ignore[arg-type]
    ).all()
    return [DeploymentReleaseWithBuildRead.model_validate(r) for r in releases]


def get_release(
    session: Session, *, deployment_id: UUID, number: int, user_id: int | None = None
) -> DeploymentReleaseWithBuildRead:
    """One release of a deployment, by its per-deployment number, build inlined.

    A number the deployment has never reached raises `NotFoundException`.
    """
    _require_readable_deployment(session, deployment_id=deployment_id, user_id=user_id)
    release = session.exec(
        select(DeploymentReleaseORM)
        .where(DeploymentReleaseORM.deployment_id == deployment_id)
        .where(DeploymentReleaseORM.number == number)
        .options(joinedload(DeploymentReleaseORM.build))  # type: ignore[arg-type]
    ).one_or_none()
    if release is None:
        raise NotFoundException("Release not found")
    read = DeploymentReleaseWithBuildRead.model_validate(release)
    read.vars = vars_service.read_snapshot(session, release.id)
    return read


def get_sftp_credentials(
    session: Session,
    *,
    deployment_id: UUID,
    user_id: int | None = None,
    provisioner: Provisioner | None = None,
) -> SftpCredentialsRead:
    """Return a deployment's SFTP connection details, or raise NotFoundException.

    Enforces the same ownership rules as ``get_deployment`` (the ORM lookup is
    scoped by ``user_id`` when provided). A 404 covers both "no such deployment"
    and "this product exposes no files", which is what the UI keys on to hide
    the feature.
    """
    prov: Provisioner = default_provisioner if provisioner is None else provisioner

    deployment = _get_deployment_orm(session, user_id=user_id, deployment_id=deployment_id)
    if deployment.status == DEPLOYMENT_STATUS_DELETED:
        raise NotFoundException("Deployment not found")

    if not prov.ssh_access_exists(namespace=deployment.namespace, instance=deployment.name):
        raise NotFoundException("SFTP access is not available for this deployment")

    settings = get_settings()
    return SftpCredentialsRead(
        host=settings.sftp_host,
        port=settings.sftp_port,
        username=str(deployment.id),
        account_has_ssh_key=ssh_keys_service.account_has_key(
            session, user_id=deployment.user_id
        ),
    )


def get_database_details(
    session: Session,
    *,
    deployment_id: UUID,
    user_id: int | None = None,
    viewer_id: int | None = None,
) -> DeploymentDatabaseRead:
    """A deployment's database connection details and quota state.

    The deployment is reached through the platform's readable-deployment rule,
    under which missing, not yours, and deleted answer identically -- so this
    function decides nothing about the deployment's own absence and cannot
    drift from every other deployment sub-resource read.

    Its own absence, "this product has no database", is
    `RelationalStorageUnavailableException`, which carries a stable code
    because it shares 404 with the above.
    """
    deployment = get_deployment_orm(session, deployment_id=deployment_id, user_id=user_id)
    return relational_storage.get_connection_details(
        session, deployment, viewer_id=viewer_id
    )


def delete_deployment(session: Session, *, user_id: int, deployment_id: UUID) -> DeploymentRead:
    """Mark a deployment as deleted.

    Retrieves the deployment ensuring it belongs to the given user. If not found,
    raises NotFoundException. Otherwise, sets the status to ``deleting`` and
    commits the transaction (the reconciler worker will perform the actual deletion).
    """
    deployment = _get_deployment_orm(session, user_id=user_id, deployment_id=deployment_id)
    if deployment.status not in (DEPLOYMENT_STATUS_DELETING, DEPLOYMENT_STATUS_DELETED):
        deployment.status = DEPLOYMENT_STATUS_DELETING
        deployment.generation += 1
        deployment.last_error = None
        deployment.deleted_at = datetime.now(UTC)
        session.add(deployment)
        try:
            _enqueue_reconcile_job(session, deployment_id=deployment_id, reason=JOB_REASON_DELETE)
            session.commit()
        except DeploymentInProgressException:
            session.rollback()
            logger.warning("Delete deployment blocked by in-progress reconcile job deployment_id=%s", deployment_id)
            raise
        logger.info("Marked deployment id=%s user_id=%s for deletion", deployment_id, user_id)
    else:
        logger.info("Deployment id=%s user_id=%s is already marked for deletion or deleted", deployment_id, user_id)
    deployment = _get_deployment_orm(session, deployment_id=deployment_id)
    return DeploymentRead.model_validate(deployment)


def update_deployment(session: Session, update: DeploymentUpdate) -> DeploymentRead:
    deployment = _get_deployment_orm(
        session,
        user_id=update.user_id,
        deployment_id=update.id,
    )
    if update.desired_template_id < deployment.desired_template_id:
        raise IntegrityException("Can only upgrade to newer versions, not downgrade")

    if not (target_template := session.get(ProductTemplateVersionORM, update.desired_template_id)):
        raise NotFoundException("Template not found")

    current_template = session.get(ProductTemplateVersionORM, deployment.desired_template_id)
    if current_template and target_template.product_id != current_template.product_id:
        raise IntegrityException("Upgrade template must belong to the same product")

    # Determine the effective user values for validation
    new_user_values = update.user_values_json if update.user_values_json is not None else deployment.user_values_json

    # Pre-flight the user-provided values against the template's schema:
    _validate_user_values(target_template, new_user_values)
    derived_hostname = normalize_and_return_hostname(
        values_schema_json=target_template.values_schema_json,
        user_values_json=new_user_values,
    )
    if derived_hostname is not None:
        require_owned_subdomain(derived_hostname, subdomain=deployment.user.subdomain)
        require_valid_hostname_for_deployment(
            session, derived_hostname, exclude_deployment_id=deployment.id,
        )

    # A named build must be the caller's. Ownership only -- see
    # `_validate_build_reference`.
    _validate_build_reference(session, user_id=deployment.user_id, build_id=update.build_id)

    # Minted before the guarded UPDATE so the pointer can move in the same
    # statement; the row itself is only inserted once the guard has passed.
    release_id = uuid4()
    release_number = _next_release_number(session, deployment_id=deployment.id)

    # Atomic status guard: only update if deployment is in 'ready' state.
    # This prevents races with the reconciler and concurrent updates.
    # Uses session.execute (not session.exec) because this is a DML UPDATE,
    # not a SELECT — we need result.rowcount, not model instances.
    result = session.execute(
        sa_update(DeploymentORM)
        .where(
            DeploymentORM.id == update.id,
            DeploymentORM.status.in_([DEPLOYMENT_STATUS_READY, DEPLOYMENT_STATUS_ERROR]),
        )
        .values(
            desired_template_id=update.desired_template_id,
            user_values_json=new_user_values,
            hostname=derived_hostname,
            status=DEPLOYMENT_STATUS_PROVISIONING,
            # Points at a release row that does not exist yet; the FK is
            # DEFERRABLE INITIALLY DEFERRED and is checked at COMMIT, by which
            # time the INSERT below has run. `applied_release_id` is untouched:
            # what is running has not changed just because a rollout was asked
            # for.
            desired_release_id=release_id,
            # SQL expression: generates SET generation = generation + 1
            # evaluated atomically by the database, not from Python state.
            generation=DeploymentORM.generation + 1,
            last_error=None,
        )
    )
    if result.rowcount == 0:
        # The guard rejected the write, so no release is created: a rejected
        # update must leave nothing behind. Nothing has been inserted at this
        # point -- only the UPDATE ran, and it matched no rows.
        raise IntegrityException("Deployment is not in ready state")

    # Only now, and unconditionally distinct from any previous release: two
    # byte-identical updates produce two releases, because identity comes from
    # the row rather than from the content.
    session.add(
        DeploymentReleaseORM(
            id=release_id,
            number=release_number,
            deployment_id=deployment.id,
            template_id=update.desired_template_id,
            build_id=update.build_id,
            values_json=new_user_values,
        )
    )

    # Vars merge; they never replace. An update that says nothing about vars
    # leaves head exactly as it was, and the release below still captures it --
    # which is why the snapshot is taken after this rather than from the
    # request. Nothing here is derived from `user_values_json`: the two halves
    # are routed by the client against the schema's projections, and a runtime
    # property submitted as a chart value is rejected by
    # `_validate_user_values` above rather than quietly re-routed.
    #
    # Attributed to the deployment's owner: this path does not receive the
    # acting user, and an administrator updating someone else's deployment is
    # writing that user's configuration.
    vars_service.write_vars(
        session,
        deployment=deployment,
        actor=session.get(UserORM, deployment.user_id),
        entries=update.vars,
    )
    vars_service.snapshot_release(
        session, release_id=release_id, deployment_id=deployment.id
    )

    # Expire the ORM instance so subsequent reads see the updated row
    session.expire(deployment)

    try:
        _enqueue_reconcile_job(session, deployment_id=update.id, reason=JOB_REASON_UPDATE)
        session.commit()
    except DeploymentInProgressException:
        session.rollback()
        logger.warning("Update deployment blocked by in-progress reconcile job deployment_id=%s", update.id)
        raise
    deployment = _get_deployment_orm(session, deployment_id=update.id)
    logger.info(
        "Updated deployment id=%s user_id=%s desired_template_id=%s",
        deployment.id,
        deployment.user_id,
        deployment.desired_template_id,
    )
    return _read_with_vars(session, deployment)
