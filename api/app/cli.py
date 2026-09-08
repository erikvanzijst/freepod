from __future__ import annotations

import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from uuid import UUID

import typer
import yaml
from fastapi.encoders import jsonable_encoder

from app.config import CaelusSettings, get_settings
from app.db import session_scope
from app.logging_config import configure_logging
from app.models import (
    TosAcceptanceCreate,
    UserCreate,
    DeploymentCreate,
    ProductTemplateVersionCreate,
    ProductCreate,
    ProductUpdate,
    ProductVisibility,
    DeploymentUpdate,
    PlanCreate,
    PlanUpdate,
    PlanTemplateVersionCreate,
    BillingInterval,
)
from app.services import (
    templates as template_service,
    deployments as deployment_service,
    products as product_service,
    users as user_service,
    reconcile as reconcile_service,
    jobs as jobs_service,
    plans as plan_service,
    subscriptions as subscription_service,
    var_crypto,
)
from app.services.errors import CaelusException, DeploymentInProgressException
from app.services.reconcile_constants import (
    JOB_REASON_UPDATE,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
)

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import UserORM

# Honor CAELUS_LOG_LEVEL (INFO by default) rather than forcing DEBUG: the CLI is
# an operator surface, and its command output should not be buried in library
# tracing. Export CAELUS_LOG_LEVEL=DEBUG for a verbose run.
configure_logging()
logger = logging.getLogger(__name__)
app = typer.Typer(help="Caelus CLI", pretty_exceptions_show_locals=False)

# Mirrors the REST `?force=` query parameter, so the two surfaces stay in
# lockstep on the break-glass path as well as on the guard itself.
FORCE_HELP = (
    "Break-glass override allowing this modification on a catalog-managed "
    "(curated) product. The catalog is unchanged, so the next reconciliation "
    "re-asserts it and the drift self-heals."
)
FORCE_DELETE_HELP = (
    "Accepted for symmetry, but deletion of a curated product or its templates "
    "is never overridable: the next reconciliation would recreate it. Remove "
    "the product's catalog file instead."
)

# ── CLI authentication ────────────────────────────────────────────────

_cli_user_email: str | None = None


@app.callback()
def _main(
    as_user: str | None = typer.Option(
        None,
        "--as-user",
        envvar="CAELUS_USER_EMAIL",
        help="Email of the acting user (overrides CAELUS_USER_EMAIL).",
    ),
) -> None:
    global _cli_user_email
    _cli_user_email = as_user


def _require_cli_user(session: Session) -> UserORM:
    """Resolve the CLI user email to a UserORM, auto-creating if needed.

    Exits with code 1 when no email is configured.
    """
    if not _cli_user_email:
        typer.echo(
            "Error: No user email configured. "
            "Set CAELUS_USER_EMAIL or pass --as-user.",
            err=True,
        )
        raise typer.Exit(code=1)

    email = _cli_user_email.strip().lower()

    user = session.exec(
        select(UserORM).where(
            func.lower(UserORM.email) == email,
            UserORM.deleted_at.is_(None),  # type: ignore[union-attr]
        )
    ).one_or_none()

    if user is None:
        user = UserORM(email=email)
        session.add(user)
        session.commit()
        session.refresh(user)

    return user


def _parse_json_object_input(
    *,
    json_text: str | None,
    json_file: Path | None,
    json_option_name: str,
    file_option_name: str,
) -> dict:
    if json_text is not None and json_file is not None:
        raise ValueError(f"Provide only one of {json_option_name} or {file_option_name}")

    if json_text is not None:
        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON for {json_option_name}: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{json_option_name} must decode to a JSON object")
        return parsed

    if json_file is not None:
        try:
            content = json_file.read_text()
        except OSError as exc:
            raise ValueError(f"Unable to read {file_option_name}: {exc}") from exc
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {file_option_name}: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{file_option_name} must contain a JSON object")
        return parsed

    return {}


def _exit_for_domain_error(exc: CaelusException) -> None:
    logger.warning("CLI command failed with domain error: %s", exc)
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(code=1)


def _echo_yaml_entity(entity: object) -> None:
    encoded = jsonable_encoder(entity)
    typer.echo(yaml.safe_dump(encoded, sort_keys=False), nl=False)


def _echo_yaml_stream_item(entity: object) -> None:
    encoded = jsonable_encoder(entity)
    typer.echo(yaml.safe_dump(encoded, sort_keys=False).rstrip())


def _echo_bytes(data: bytes) -> None:
    """Write build output to stdout verbatim.

    Bytes rather than text on purpose: a build log is whatever the tenant's
    tooling emitted, which is only conventionally UTF-8. Writing through the
    binary buffer passes it through unchanged, exactly as the REST log endpoint
    does, instead of forcing a decode that could fail or mangle it.
    """
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:  # a captured/text-only stdout, e.g. under CliRunner
        sys.stdout.write(data.decode("utf-8", errors="replace"))
        sys.stdout.flush()
        return
    stream.write(data)
    stream.flush()


@app.command("create-user")
def create_user(email: str) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        try:
            user = user_service.create_user(session, UserCreate(email=email))
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(user)


@app.command("delete-user")
def delete_user(user_id: int) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        try:
            user = user_service.delete_user(session, user_id=user_id)
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(user)


@app.command("list-users")
def list_users() -> None:
    with session_scope() as session:
        _require_cli_user(session)
        _echo_yaml_entity(user_service.list_users(session))


@app.command("get-user")
def get_user(user_id: int) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        try:
            user = user_service.get_user(session, user_id=user_id)
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(user)


@app.command("create-product")
def create_product(
    name: str,
    description: str,
    template_id: int | None = None,
    category: str | None = typer.Option(None, "--category"),
    replaces: str | None = typer.Option(None, "--replaces"),
    visibility: ProductVisibility = typer.Option(
        ProductVisibility.ADMIN.value,
        "--visibility",
        help="Whether the product is offered to end users. New products stay hidden by default.",
    ),
    icon: Path | None = typer.Option(None, "--icon", help="Path to product icon image"),
) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        try:
            icon_data = None
            if icon is not None:
                icon_data = icon.read_bytes()
            product = product_service.create_product(
                session,
                payload=ProductCreate(
                    name=name,
                    description=description,
                    template_id=template_id,
                    category=category,
                    replaces=replaces,
                    visibility=visibility,
                ),
                icon_data=icon_data,
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(product)


@app.command("update-product")
def update_product(
    product_id: int,
    *,
    template_id: int | None = typer.Option(None, "--template-id"),
    description: str | None = typer.Option(None, "--description"),
    category: str | None = typer.Option(None, "--category"),
    replaces: str | None = typer.Option(None, "--replaces"),
    visibility: ProductVisibility | None = typer.Option(
        None,
        "--visibility",
        help="Publish the product to end users ('public') or withdraw it ('admin').",
    ),
    icon: Path | None = typer.Option(
        None, "--icon", help="Path to a product icon image. Replaces any existing icon."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=FORCE_HELP,
    ),
) -> None:
    with session_scope() as session:
        actor = _require_cli_user(session)
        try:
            icon_data = icon.read_bytes() if icon is not None else None
            product = product_service.update_product(
                session,
                product=ProductUpdate(
                    id=product_id,
                    template_id=template_id,
                    description=description,
                    category=category,
                    replaces=replaces,
                    visibility=visibility,
                ),
                icon_data=icon_data,
                actor=actor,
                force=force,
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(product)


@app.command("delete-product")
def delete_product(
    product_id: int,
    force: bool = typer.Option(False, "--force", help=FORCE_DELETE_HELP),
) -> None:
    with session_scope() as session:
        actor = _require_cli_user(session)
        try:
            product = product_service.delete_product(
                session, product_id=product_id, force=force, actor=actor
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(product)


@app.command("list-products")
def list_products() -> None:
    with session_scope() as session:
        # Mirrors GET /api/products: admins additionally see the products
        # hidden from end users.
        user = _require_cli_user(session)
        _echo_yaml_entity(product_service.list_products(session, include_hidden=user.is_admin))


@app.command("get-product")
def get_product(product_id: int) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        try:
            product = product_service.get_product(session, product_id=product_id)
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(product)


@app.command("create-template")
def create_template(
    product_id: int = typer.Option(
        ..., "--product-id", help="Product ID to associate with the template."
    ),
    chart_ref: str = typer.Option(
        ..., "--chart-ref", help="Chart reference (e.g. 'oci://example/chart')."
    ),
    chart_version: str = typer.Option(..., "--chart-version", help="Chart version (e.g. '1.2.3')."),
    chart_digest: str | None = typer.Option(
        None, "--chart-digest", help="Optional immutable digest for the chart artifact."
    ),
    system_values_json: str | None = typer.Option(
        None,
        "--system-values-json",
        help="JSON object string for template system values.",
    ),
    system_values_file: Path | None = typer.Option(
        None,
        "--system-values-file",
        help="Path to JSON file containing template system values object.",
    ),
    values_schema_json: str | None = typer.Option(
        None,
        "--values-schema-json",
        help="JSON object string for template values schema.",
    ),
    values_schema_file: Path | None = typer.Option(
        None,
        "--values-schema-file",
        help="Path to JSON file containing template values schema object.",
    ),
    force: bool = typer.Option(False, "--force", help=FORCE_HELP),
) -> None:
    try:
        parsed_system_values = _parse_json_object_input(
            json_text=system_values_json,
            json_file=system_values_file,
            json_option_name="--system-values-json",
            file_option_name="--system-values-file",
        )
        parsed_values_schema = _parse_json_object_input(
            json_text=values_schema_json,
            json_file=values_schema_file,
            json_option_name="--values-schema-json",
            file_option_name="--values-schema-file",
        )
    except ValueError as e:
        logger.warning("Invalid template JSON input: %s", e)
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    with session_scope() as session:
        actor = _require_cli_user(session)
        try:
            template = template_service.create_template(
                session,
                ProductTemplateVersionCreate(
                    product_id=product_id,
                    chart_ref=chart_ref,
                    chart_version=chart_version,
                    chart_digest=chart_digest,
                    system_values_json=parsed_system_values,
                    values_schema_json=parsed_values_schema,
                ),
                force=force,
                actor=actor,
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(template)


@app.command("list-templates")
def list_templates(product_id: int) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        _echo_yaml_entity(template_service.list_templates(session, product_id=product_id))


@app.command("get-template")
def get_template(product_id: int, template_id: int) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        try:
            template = template_service.get_template(
                session,
                product_id=product_id,
                template_id=template_id,
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(template)


@app.command("delete-template")
def delete_template(
    product_id: int,
    template_id: int,
    force: bool = typer.Option(False, "--force", help=FORCE_DELETE_HELP),
) -> None:
    with session_scope() as session:
        actor = _require_cli_user(session)
        try:
            template = template_service.delete_template(
                session,
                product_id=product_id,
                template_id=template_id,
                force=force,
                actor=actor,
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(template)


@app.command("create-deployment")
def create_deployment(
    *,
    user_id: int = typer.Option(..., "--user-id"),
    desired_template_id: int = typer.Option(..., "--desired-template-id"),
    plan_template_id: int = typer.Option(..., "--plan-template-id"),
    user_values_json: str | None = typer.Option(
        None,
        "--user-values-json",
        help='JSON object string for deployment user values, e.g. \'{"key":"value"}\'.',
    ),
    user_values_file: Path | None = typer.Option(
        None,
        "--user-values-file",
        help="Path to a JSON file containing a JSON object for deployment user values.",
    ),
) -> None:
    try:
        parsed_user_values = _parse_json_object_input(
            json_text=user_values_json,
            json_file=user_values_file,
            json_option_name="--user-values-json",
            file_option_name="--user-values-file",
        )
    except ValueError as e:
        logger.warning("Invalid deployment user values JSON input: %s", e)
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    with session_scope() as session:
        _require_cli_user(session)

        # Refuse paid plans via CLI — checkout requires a browser redirect.
        settings = get_settings()
        if settings.mollie_api_key:
            from app.models import PlanTemplateVersionORM
            ptv = session.get(PlanTemplateVersionORM, plan_template_id)
            if ptv and ptv.price_cents > 0:
                typer.echo(
                    "Error: Paid plans require payment via the web dashboard. "
                    "The CLI cannot redirect to the Mollie checkout page.",
                    err=True,
                )
                raise typer.Exit(code=1)

        try:
            result = deployment_service.create_deployment(
                session,
                payload=DeploymentCreate(
                    user_id=user_id,
                    desired_template_id=desired_template_id,
                    plan_template_id=plan_template_id,
                    user_values_json=parsed_user_values,
                ),
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(result.deployment)


@app.command("accept-tos")
def accept_tos(
    *,
    user_id: int = typer.Option(..., "--user-id"),
    version: str = typer.Option(
        ...,
        "--version",
        help="ISO-8601 effective date (YYYY-MM-DD) of the Terms of Service being "
        "accepted. Must equal the current Terms version.",
    ),
) -> None:
    """Record a user's acceptance of the current Terms of Service.

    Mirrors POST /api/me/tos-acceptance. Deploying requires that the owning user
    has accepted first; run this before create-deployment for a new user.
    """
    with session_scope() as session:
        _require_cli_user(session)
        user = session.get(UserORM, user_id)
        if not user or user.deleted_at:
            typer.echo(f"Error: User {user_id} not found.", err=True)
            raise typer.Exit(code=1)
        try:
            # Construct the request model to get the same ISO shape validation the
            # API applies before the service's equal-to-current check.
            payload = TosAcceptanceCreate(version=version)
            acceptance = user_service.record_tos_acceptance(
                session, user=user, version=payload.version
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(acceptance)


@app.command("list-deployments")
def list_deployments(
    user_id: int | None = typer.Argument(None, help="Filter deployments by user ID"),
    all_users: bool = typer.Option(False, "--all", help="List deployments for all users (admin only)"),
) -> None:
    with session_scope() as session:
        user = _require_cli_user(session)
        if all_users:
            if not user.is_admin:
                typer.echo("Error: --all requires admin privileges", err=True)
                raise typer.Exit(code=1)
            _echo_yaml_entity(deployment_service.list_deployments(session))
        else:
            _echo_yaml_entity(deployment_service.list_deployments(session, user_id=user_id))


@app.command("get-deployment")
def get_deployment(user_id: int, deployment_id: UUID) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        try:
            deployment = deployment_service.get_deployment(
                session,
                user_id=user_id,
                deployment_id=deployment_id,
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(deployment)


def _release_scope(user: UserORM, user_id: int) -> int | None:
    """The scope to read releases under, or exit for a refused cross-user read.

    There is no `require_self` here as there is on the REST side, so the check
    is explicit -- passing the argument through unguarded would let anyone read
    any account's releases.
    """
    if user.is_admin:
        return None
    if user_id != user.id:
        typer.echo("Error: reading another user's releases requires admin privileges", err=True)
        raise typer.Exit(code=1)
    return user_id


@app.command("list-releases")
def list_releases(user_id: int, deployment_id: UUID) -> None:
    """List a deployment's releases, most recent first."""
    with session_scope() as session:
        user = _require_cli_user(session)
        scope = _release_scope(user, user_id)
        try:
            releases = deployment_service.list_releases(
                session, deployment_id=deployment_id, user_id=scope
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(releases)


@app.command("get-release")
def get_release(user_id: int, deployment_id: UUID, number: int) -> None:
    """Show one release by its per-deployment number, with its build inlined."""
    with session_scope() as session:
        user = _require_cli_user(session)
        scope = _release_scope(user, user_id)
        try:
            release = deployment_service.get_release(
                session, deployment_id=deployment_id, number=number, user_id=scope
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(release)


@app.command("get-deployment-sftp")
def get_deployment_sftp(user_id: int, deployment_id: UUID) -> None:
    """A deployment's SFTP connection details.

    No credential is reported, to anyone: access is authenticated by a public
    key registered on the owning account, so there is none to report.
    `account_has_ssh_key` says whether that account has one yet -- when it does
    not, these details cannot be used until the owner registers a key.
    """
    with session_scope() as session:
        _require_cli_user(session)
        try:
            creds = deployment_service.get_sftp_credentials(
                session,
                user_id=user_id,
                deployment_id=deployment_id,
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(creds)


@app.command("get-deployment-database")
def get_deployment_database(user_id: int, deployment_id: UUID) -> None:
    """A deployment's database connection details, quota state and usage.

    The password is reported to the deployment's owner alone. An operator
    acting as anyone else gets every other field with the password withheld --
    the same rule the API applies, inherited from the same service rather than
    re-implemented here.
    """
    with session_scope() as session:
        operator = _require_cli_user(session)
        try:
            details = deployment_service.get_database_details(
                session,
                user_id=user_id,
                deployment_id=deployment_id,
                viewer_id=operator.id,
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(details)


@app.command("delete-deployment")
def delete_deployment(user_id: int, deployment_id: UUID) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        try:
            deployment = deployment_service.delete_deployment(
                session, user_id=user_id, deployment_id=deployment_id
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(deployment)


@app.command("update-deployment")
def update_deployment(
    *,
    user_id: int = typer.Option(..., "--user-id"),
    deployment_id: UUID = typer.Option(..., "--deployment-id"),
    desired_template_id: int = typer.Option(..., "--desired-template-id"),
    user_values_json: str | None = typer.Option(
        None,
        "--user-values-json",
        help='JSON object string for new deployment user values, e.g. \'{"key":"value"}\'. '
        "Omit to reuse the deployment's existing stored values.",
    ),
    user_values_file: Path | None = typer.Option(
        None,
        "--user-values-file",
        help="Path to a JSON file containing a JSON object for new deployment user values.",
    ),
) -> None:
    # Only override user values when a flag is given; otherwise pass None so the
    # service reuses the deployment's existing stored values (unchanged behavior).
    parsed_user_values: dict | None = None
    if user_values_json is not None or user_values_file is not None:
        try:
            parsed_user_values = _parse_json_object_input(
                json_text=user_values_json,
                json_file=user_values_file,
                json_option_name="--user-values-json",
                file_option_name="--user-values-file",
            )
        except ValueError as e:
            logger.warning("Invalid deployment user values JSON input: %s", e)
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(code=1)

    with session_scope() as session:
        _require_cli_user(session)
        try:
            deployment = deployment_service.update_deployment(
                session,
                update=DeploymentUpdate(
                    user_id=user_id,
                    id=deployment_id,
                    desired_template_id=desired_template_id,
                    user_values_json=parsed_user_values,
                ),
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(deployment)


@app.command("reconcile")
def reconcile(
    deployment_id: UUID,
) -> None:
    with session_scope() as session:
        try:
            result = reconcile_service.DeploymentReconciler(session=session).reconcile(
                deployment_id
            )
        except CaelusException as e:
            _exit_for_domain_error(e)

        if result.status == "error":
            typer.echo(
                f"Error: Reconcile failed for deployment {deployment_id}: {result.last_error}",
                err=True,
            )
            raise typer.Exit(code=1)

        if result.deferred:
            # This path holds no job to defer, and the deferred result has just
            # put the deployment into `provisioning` -- which only a completed
            # reconcile moves it out of. Without a job to finish the work that
            # is a deployment stranded by an operator command, so one is queued
            # here rather than promising a retry that does not exist.
            try:
                jobs_service.JobService(session).enqueue_job(
                    deployment_id=deployment_id, reason=JOB_REASON_UPDATE
                )
                session.commit()
            except DeploymentInProgressException:
                pass
            typer.echo(
                f"Deployment {deployment_id} is waiting for its account's TLS "
                "certificate; it remains provisioning and a queued job will "
                "retry.",
                err=True,
            )

        _echo_yaml_entity(result)


@app.command("worker")
def worker(
    concurrency: int = typer.Option(1, "--concurrency", "-c", help="Number of parallel job workers"),
    poll_seconds: float = typer.Option(1.0, "--poll-seconds", help="Sleep interval when no jobs are available"),
) -> None:
    if concurrency < 1:
        typer.echo("Error: --concurrency must be >= 1", err=True)
        raise typer.Exit(code=1)

    from app.worker import run_worker

    # The worker decrypts a release's vars to build the tenant's Secret, so a
    # keyring that cannot cover storage has to stop it here rather than inside
    # somebody's rollout, after the release row already exists.
    with session_scope() as session:
        try:
            var_crypto.verify_keyring(session)
        except CaelusException as e:
            _exit_for_domain_error(e)

    base_worker_id = os.environ.get("CAELUS_WORKER_ID") or f"worker-{int(time.time())}"
    run_worker(
        base_worker_id=base_worker_id,
        concurrency=concurrency,
        poll_seconds=poll_seconds,
        emit=_echo_yaml_stream_item,
    )


@app.command("db-worker")
def db_worker(
    interval_seconds: float | None = typer.Option(
        None, "--interval-seconds", help="Seconds between quota sweeps"
    ),
) -> None:
    """Run the database housekeeping worker: measure and apply quota state.

    Deliberately does not verify the var keyring, unlike `worker`: every tick
    connects as the platform's database admin and none of them decrypts a
    tenant password, so a keyring problem must not stop quota enforcement.
    """
    from app.db_worker import run_db_worker

    settings = get_settings()
    if interval_seconds is not None:
        if interval_seconds <= 0:
            typer.echo("Error: --interval-seconds must be > 0", err=True)
            raise typer.Exit(code=1)
        settings = CaelusSettings(
            **{**settings.model_dump(), "db_worker_quota_interval_seconds": interval_seconds}
        )

    run_db_worker(settings=settings, emit=_echo_yaml_stream_item)


@app.command("build-worker")
def build_worker(
    interval_seconds: float | None = typer.Option(
        None, "--interval-seconds", help="Seconds between passes (default: CAELUS_BUILD_WORKER_INTERVAL_SECONDS)"
    ),
    max_in_flight: int | None = typer.Option(
        None, "--max-in-flight", help="Builds allowed to run at once (default: CAELUS_BUILD_MAX_IN_FLIGHT)"
    ),
) -> None:
    """Run the build worker: claim queued builds, advance running ones.

    Unlike `worker`, this takes no `--concurrency`: one process runs one
    non-blocking pass that advances every running build, so how many builds run
    at once is `--max-in-flight`, not a process count.
    """
    # Deferred like `worker` above, and for a measured reason: importing
    # app.build_worker costs ~350ms because it pulls in boto3 via the artifacts
    # service. At module level that would land on every `caelus` invocation,
    # including `catalog lint` in CI and the catalog init container on rollout.
    from app.build_worker import run_build_worker

    settings = get_settings()
    overrides: dict[str, object] = {}
    if interval_seconds is not None:
        if interval_seconds <= 0:
            typer.echo("Error: --interval-seconds must be > 0", err=True)
            raise typer.Exit(code=1)
        overrides["build_worker_interval_seconds"] = interval_seconds
    if max_in_flight is not None:
        if max_in_flight < 1:
            typer.echo("Error: --max-in-flight must be >= 1", err=True)
            raise typer.Exit(code=1)
        overrides["build_max_in_flight"] = max_in_flight
    if overrides:
        settings = CaelusSettings(**{**settings.model_dump(), **overrides})

    run_build_worker(settings=settings, emit=_echo_yaml_stream_item)


@app.command("keyring-rotate")
def keyring_rotate(
    batch_size: int = typer.Option(
        200, "--batch-size", help="Rows re-encrypted per committed batch"
    ),
) -> None:
    """Re-encrypt every value the keyring covers under the current key.

    Run after promoting a new key to the front of CAELUS_VAR_ENCRYPTION_KEYS.
    Every batch commits on its own, so the sweep can be interrupted and
    re-run: a row names the key that encrypted it, and a half-swept store
    stays fully readable throughout.

    Retiring the old key takes more than this reporting zero. That count is a
    snapshot: a process still running with the old key at the front keeps
    writing rows under it. Roll every process onto the new key list first,
    re-run this until it reports zero, and let the startup check be the gate --
    it refuses to serve while any stored value names a key that is gone.
    """
    with session_scope() as session:
        try:
            rotated = var_crypto.rotate_encrypted_values(
                session,
                batch_size=batch_size,
                on_batch=lambda n: logger.info("Re-encrypted %d rows so far", n),
            )
            key_id = var_crypto.current_key_id()
        except CaelusException as e:
            _exit_for_domain_error(e)
    _echo_yaml_entity({"rotated": rotated, "current_key_id": key_id})


@app.command("sync-network-policies")
def sync_network_policies(
    concurrency: int = typer.Option(16, "--concurrency", "-c", help="Parallel kubectl applies"),
    namespaces: str | None = typer.Option(
        None, "--namespaces", help="Comma-separated namespaces to limit the sync to"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print rendered policies instead of applying them"
    ),
) -> None:
    """Re-apply the baseline NetworkPolicy + tenant labels across running deployments.

    Use this to roll out a change to the baseline policy after editing the
    template/settings. NetworkPolicy updates reprogram the CNI dataplane without
    restarting pods, so a fleet-wide sync is non-disruptive; individual failures
    are reported and do not abort the rest. Canary a few namespaces with
    ``--namespaces`` before fanning out.
    """
    from app.provisioner import provisioner as prov

    only = {n.strip() for n in namespaces.split(",") if n.strip()} if namespaces else None
    with session_scope() as session:
        deployments = deployment_service.list_deployments(session)

    target_ns = sorted(
            deployment.namespace
            for deployment in deployments
            if deployment.namespace and (only is None or deployment.namespace in only)
    )
    if not target_ns:
        typer.echo("No matching deployment namespaces to sync.")
        return

    if dry_run:
        for ns in target_ns:
            _echo_yaml_stream_item(prov.build_tenant_policy(namespace=ns))
        return

    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(prov.ensure_tenant_isolation, namespace=ns): ns for ns in target_ns}
        for future in as_completed(futures):
            ns = futures[future]
            try:
                future.result()
                typer.echo(f"synced {ns}")
            except Exception as exc:  # noqa: BLE001 - report per-namespace, keep going
                failures.append(ns)
                typer.echo(f"FAILED {ns}: {exc}", err=True)

    typer.echo(f"Synced {len(target_ns) - len(failures)}/{len(target_ns)} namespaces.")
    if failures:
        raise typer.Exit(code=1)


@app.command("jobs")
def jobs(
    failed: bool = typer.Option(False, "--failed", help="Show only failed jobs"),
    done: bool = typer.Option(False, "--done", help="Show only done jobs"),
    reverse: bool = typer.Option(False, "--reverse", "-r", help="Reverse run_after sort order"),
    deployment_id: UUID | None = typer.Option(
        None, "--deployment-id", "-d", help="Filter by deployment id"
    ),
) -> None:
    if failed and done:
        statuses = [JOB_STATUS_FAILED, JOB_STATUS_DONE]
    elif failed:
        statuses = [JOB_STATUS_FAILED]
    elif done:
        statuses = [JOB_STATUS_DONE]
    else:
        statuses = [JOB_STATUS_QUEUED, JOB_STATUS_RUNNING]

    with session_scope() as session:
        jobs_service_obj = jobs_service.JobService(session)
        jobs_list = jobs_service_obj.list_jobs(
            statuses=statuses, deployment_id=deployment_id, limit=1000
        )
        if reverse:
            jobs_list = list(reversed(jobs_list))
        _echo_yaml_entity(jobs_list)


# ── Plan commands ─────────────────────────────────────────────────────


@app.command("list-plans")
def list_plans(product_id: int) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        try:
            plans = plan_service.list_plans_for_product(session, product_id)
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(plans)


@app.command("get-plan")
def get_plan(plan_id: int) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        try:
            plan = plan_service.get_plan(session, plan_id)
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(plan)


@app.command("create-plan")
def create_plan(
    product_id: int = typer.Option(..., "--product-id"),
    name: str = typer.Option(..., "--name"),
    sort_order: int | None = typer.Option(None, "--sort-order"),
) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        try:
            plan = plan_service.create_plan(
                session,
                product_id=product_id,
                payload=PlanCreate(name=name, sort_order=sort_order),
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(plan)


@app.command("update-plan")
def update_plan(
    plan_id: int,
    name: str | None = typer.Option(None, "--name"),
    template_id: int | None = typer.Option(None, "--template-id"),
    sort_order: int | None = typer.Option(None, "--sort-order"),
) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        try:
            plan = plan_service.update_plan(
                session,
                plan_id=plan_id,
                payload=PlanUpdate(
                    name=name,
                    template_id=template_id, sort_order=sort_order,
                ),
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(plan)


@app.command("delete-plan")
def delete_plan(plan_id: int) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        try:
            plan_service.delete_plan(session, plan_id=plan_id)
        except CaelusException as e:
            _exit_for_domain_error(e)
        typer.echo("Deleted")


@app.command("create-plan-template")
def create_plan_template(
    plan_id: int = typer.Option(..., "--plan-id"),
    price_cents: int = typer.Option(..., "--price-cents"),
    billing_interval: BillingInterval = typer.Option(..., "--billing-interval"),
    storage_bytes: int | None = typer.Option(None, "--storage-bytes"),
    database_bytes: int | None = typer.Option(None, "--database-bytes"),
    description: str | None = typer.Option(None, "--description"),
) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        try:
            tmpl = plan_service.create_plan_template_version(
                session,
                plan_id=plan_id,
                payload=PlanTemplateVersionCreate(
                    price_cents=price_cents,
                    billing_interval=billing_interval,
                    storage_bytes=storage_bytes,
                    database_bytes=database_bytes,
                    description=description,
                ),
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(tmpl)


# ── Catalog commands ──────────────────────────────────────────────────
#
# Operator and build tooling rather than tenant-facing surface — `apply` is run
# by an init container — so this group is intentionally CLI-only and exempt from
# the REST parity convention. No parity gap is introduced: the protections these
# commands rely on live in the service layer.

build_app = typer.Typer(
    help="Build project archives into container images.",
    no_args_is_help=True,
)
app.add_typer(build_app, name="build")

# Directories that are never source: reproducing them wastes the upload budget
# and, for a Railpack build, is actively counterproductive — dependencies are
# installed inside the build from the manifest, so a vendored tree would only
# be overwritten.
_ARCHIVE_EXCLUDES = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache"}
)


def _build_or_exit(session: Session, build_id: UUID, user: UserORM):
    from app.services import builds as build_service

    try:
        return build_service.get_build(
            session, build_id=build_id, user_id=None if user.is_admin else user.id
        )
    except CaelusException as e:
        _exit_for_domain_error(e)


def _archive_directory(source: Path, *, max_bytes: int) -> bytes:
    """Tar+gzip `source` into memory, skipping what is never source.

    Checked against the cap here as well as at the object store: the store's
    rejection is authoritative, but finding out locally beats spending the
    upload to be told.
    """
    import io
    import tarfile

    if not source.is_dir():
        typer.echo(f"Error: {source} is not a directory", err=True)
        raise typer.Exit(code=1)

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in sorted(source.rglob("*")):
            if any(part in _ARCHIVE_EXCLUDES for part in path.relative_to(source).parts):
                continue
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                continue
            tar.add(path, arcname=str(path.relative_to(source)), recursive=False)

    archive = buffer.getvalue()
    if len(archive) > max_bytes:
        typer.echo(
            f"Error: project archive is {len(archive)} bytes, over the "
            f"{max_bytes} byte limit. Remove large files or add them to .gitignore.",
            err=True,
        )
        raise typer.Exit(code=1)
    return archive


@build_app.command("list")
def build_list(
    user_id: int | None = typer.Argument(None, help="Whose builds to list (admin only)"),
) -> None:
    """List builds, most recent first."""
    from app.services import builds as build_service

    with session_scope() as session:
        user = _require_cli_user(session)
        if user_id is not None and user_id != user.id and not user.is_admin:
            typer.echo("Error: listing another user's builds requires admin privileges", err=True)
            raise typer.Exit(code=1)
        _echo_yaml_entity(build_service.list_builds(session, user_id=user_id or user.id))


@build_app.command("show")
def build_show(build_id: UUID) -> None:
    """Show one build's status, timestamps, and resulting image."""
    with session_scope() as session:
        user = _require_cli_user(session)
        _echo_yaml_entity(_build_or_exit(session, build_id, user))


@build_app.command("log")
def build_log(
    build_id: UUID,
    follow: bool = typer.Option(False, "--follow", "-f", help="Poll until the build finishes"),
) -> None:
    """Print a build's output.

    With `--follow`, polls from the offset already printed — the same
    incremental read the REST log endpoint serves over HTTP Range.
    """
    from app.services import builds as build_service
    from app.services.build_constants import is_terminal

    with session_scope() as session:
        user = _require_cli_user(session)
        scope = None if user.is_admin else user.id
        _build_or_exit(session, build_id, user)  # 404s before printing anything

        offset = 0
        while True:
            slice_ = build_service.get_build_log(
                session, build_id=build_id, user_id=scope, start=offset
            )
            if slice_.data:
                _echo_bytes(slice_.data)
                offset += len(slice_.data)
            if not follow or is_terminal(slice_.status):
                break
            session.commit()  # release the snapshot so the next read sees new rows
            time.sleep(get_settings().build_worker_interval_seconds)


@build_app.command("submit")
def build_submit(
    directory: Path = typer.Argument(Path("."), help="Project directory to build"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for the build to finish"),
    timeout_seconds: float = typer.Option(
        3900.0, "--timeout", help="How long to wait before giving up on a build"
    ),
) -> None:
    """Build a project directory into an image: upload, then build.

    Performs all three phases the REST API exposes — mint an upload slot,
    upload the archive straight to object storage, create the build — so the
    whole flow is exercisable without a separate client.

    On success the resulting `image` is printed. That value is what you submit
    as a deployment's `image` user value; nothing here deploys it for you, by
    design: a deployment may consume several images and most consume none.
    """
    import httpx

    from app.models import BuildCreate
    from app.services import artifacts as artifact_service
    from app.services import builds as build_service
    from app.services.build_constants import BUILD_STATUS_SUCCEEDED, is_terminal

    settings = get_settings()
    archive = _archive_directory(directory, max_bytes=settings.artifact_max_bytes)

    with session_scope() as session:
        user = _require_cli_user(session)
        scope = None if user.is_admin else user.id

        try:
            slot = artifact_service.mint_upload_slot(user.id)
        except CaelusException as e:
            _exit_for_domain_error(e)
        typer.echo(f"Uploading {len(archive)} bytes as artifact {slot.artifact_id}...", err=True)

        response = httpx.post(
            slot.url,
            data=dict(slot.fields),
            files={"file": ("project.tgz", archive, "application/gzip")},
            timeout=300,
        )
        if response.status_code >= 400:
            typer.echo(f"Error: upload rejected ({response.status_code}): {response.text[:300]}", err=True)
            raise typer.Exit(code=1)

        try:
            result = build_service.create_build(
                session, user_id=user.id, payload=BuildCreate(artifact_id=slot.artifact_id)
            )
        except CaelusException as e:
            _exit_for_domain_error(e)

        build = result.build
        typer.echo(f"Build {build.id} queued.", err=True)
        if not wait:
            _echo_yaml_entity(build)
            return

        offset = 0
        deadline = time.monotonic() + timeout_seconds
        while True:
            slice_ = build_service.get_build_log(
                session, build_id=build.id, user_id=scope, start=offset
            )
            if slice_.data:
                _echo_bytes(slice_.data)
                offset += len(slice_.data)
            if is_terminal(slice_.status):
                break
            if time.monotonic() > deadline:
                typer.echo(f"Error: gave up waiting for build {build.id}", err=True)
                raise typer.Exit(code=1)
            session.commit()
            time.sleep(settings.build_worker_interval_seconds)

        final = build_service.get_build(session, build_id=build.id, user_id=scope)
        if final.status != BUILD_STATUS_SUCCEEDED:
            typer.echo(f"Error: build {final.id} {final.status}", err=True)
            raise typer.Exit(code=1)
        typer.echo(final.image)


catalog_app = typer.Typer(
    help="Manage the git-authored product catalog (products/catalog/).",
    no_args_is_help=True,
)
app.add_typer(catalog_app, name="catalog")


def _catalog_dir(dir_option: Path | None) -> Path:
    return dir_option if dir_option is not None else get_settings().catalog_dir


@catalog_app.command("apply")
def catalog_apply(
    dir: Path | None = typer.Option(
        None, "--dir", help="Catalog directory to apply (defaults to CAELUS_CATALOG_DIR)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report the actions that would be taken and write nothing."
    ),
) -> None:
    """Reconcile a catalog directory into the database.

    Run by the `catalog` init container after `migrate`. A validation or
    reconciliation failure exits non-zero with the database unchanged, which
    fails the init container and leaves the previous pods serving.
    """
    from app.services.catalog import CatalogReconciler

    catalog_dir = _catalog_dir(dir)
    with session_scope() as session:
        try:
            report = CatalogReconciler(
                session=session,
                catalog_dir=catalog_dir,
                commit_sha=os.environ.get("GIT_COMMIT"),
            ).apply(dry_run=dry_run)
        except CaelusException as e:
            _exit_for_domain_error(e)

    for action in report.actions:
        typer.echo(action)
    verb = "planned" if dry_run else "applied"
    typer.echo(f"Catalog {verb} from {catalog_dir}: {len(report.actions)} action(s).")


@catalog_app.command("curate")
def catalog_curate(
    slug: str = typer.Argument(
        ..., help="Slug or name of the product to write into the catalog."
    ),
    dir: Path | None = typer.Option(
        None, "--dir", help="Catalog directory to write into (defaults to CAELUS_CATALOG_DIR)."
    ),
) -> None:
    """Write a product's catalog document and icon from current database state.

    This is the graduation path for a hand-tuned product. It does **not** curate
    the product: curation takes effect only when the reconciler applies the
    committed catalog during a rollout, so `curated` and `slug` are left
    untouched here.
    """
    from app.services import catalog as catalog_service

    catalog_dir = _catalog_dir(dir)
    with session_scope() as session:
        _require_cli_user(session)
        try:
            written = catalog_service.curate_product(
                session, identifier=slug, catalog_dir=catalog_dir
            )
        except CaelusException as e:
            _exit_for_domain_error(e)

    for path in written:
        typer.echo(f"wrote {path}")
    typer.echo(
        "The product is not curated yet: complete the 'upstream' block, then commit "
        "and merge these files. Curation takes effect when the reconciler applies "
        "the catalog during the next rollout."
    )


@catalog_app.command("lint")
def catalog_lint(
    dir: Path | None = typer.Option(
        None, "--dir", help="Catalog directory to validate (defaults to CAELUS_CATALOG_DIR)."
    ),
    write_schema: bool = typer.Option(
        False,
        "--write-schema",
        help="Regenerate catalog.schema.json from the document models instead of "
        "checking it. Run this after changing the models.",
    ),
) -> None:
    """Validate a catalog directory using only the files themselves.

    Deliberately touches no database, so it can gate a pull request in CI where
    neither a database nor the cluster is reachable. Also verifies that the
    generated `catalog.schema.json` still matches the document models, so the
    editor contract cannot drift from the enforced one.
    """
    from app.services.catalog import check_json_schema, load_catalog, write_json_schema

    catalog_dir = _catalog_dir(dir)

    if write_schema:
        typer.echo(f"wrote {write_json_schema(catalog_dir)}")
        return

    try:
        entries = load_catalog(catalog_dir)
        check_json_schema(catalog_dir)
    except CaelusException as e:
        _exit_for_domain_error(e)

    for entry in entries:
        typer.echo(f"ok {entry.path}")
    typer.echo(f"Validated {len(entries)} catalog document(s) in {catalog_dir}.")


# ── Subscription commands ─────────────────────────────────────────────


@app.command("list-subscriptions")
def list_subscriptions(user_id: int) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        subs = subscription_service.list_subscriptions_for_user(session, user_id)
        _echo_yaml_entity(subs)


@app.command("cancel-subscription")
def cancel_subscription(subscription_id: int) -> None:
    with session_scope() as session:
        _require_cli_user(session)
        try:
            sub = subscription_service.cancel_subscription(
                session, subscription_id=subscription_id
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(sub)


# ── SSH keys ──────────────────────────────────────────────────────────

ssh_key_app = typer.Typer(
    help="Manage an account's SSH public keys.",
    no_args_is_help=True,
)
app.add_typer(ssh_key_app, name="ssh-key")


def _ssh_key_target(session: Session, user_id: int | None) -> int:
    """The account to act on, honoring the admin-only cross-account form."""
    user = _require_cli_user(session)
    if user_id is None or user_id == user.id:
        return user.id
    if not user.is_admin:
        typer.echo("Error: Forbidden", err=True)
        raise typer.Exit(code=1)
    return user_id


@ssh_key_app.command("list")
def ssh_key_list(
    user_id: int | None = typer.Argument(None, help="Whose keys to list (admin only)"),
) -> None:
    """List an account's registered SSH public keys."""
    from app.services import ssh_keys as ssh_key_service

    with session_scope() as session:
        target = _ssh_key_target(session, user_id)
        _echo_yaml_entity(ssh_key_service.list_keys(session, user_id=target))


@ssh_key_app.command("add")
def ssh_key_add(
    public_key: str = typer.Argument(..., help="Path to a .pub file, or the key line itself"),
    label: str | None = typer.Option(None, "--label", help="Defaults to the key's comment"),
) -> None:
    """Register an SSH public key on the acting account.

    Only ever on your own account, exactly as the API restricts it: adding a
    key to someone else's account installs a credential that authenticates as
    them.
    """
    from app.services import ssh_keys as ssh_key_service

    candidate = Path(public_key)
    material = candidate.read_text() if candidate.is_file() else public_key

    with session_scope() as session:
        user = _require_cli_user(session)
        try:
            key = ssh_key_service.add_key(
                session, user_id=user.id, public_key=material, label=label
            )
        except CaelusException as e:
            _exit_for_domain_error(e)
        _echo_yaml_entity(key)


@ssh_key_app.command("rm")
def ssh_key_rm(
    fingerprint: str = typer.Argument(..., help="The key's SHA256: fingerprint"),
    user_id: int | None = typer.Option(None, "--user-id", help="Whose key to revoke (admin only)"),
) -> None:
    """Revoke a registered SSH public key."""
    from app.services import ssh_keys as ssh_key_service

    with session_scope() as session:
        target = _ssh_key_target(session, user_id)
        try:
            ssh_key_service.delete_key(session, user_id=target, fingerprint=fingerprint)
        except CaelusException as e:
            _exit_for_domain_error(e)
        typer.echo(f"Removed {fingerprint}")


if __name__ == "__main__":
    app()
