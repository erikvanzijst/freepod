"""The deploy pipeline: preflight, pack, upload, build, release.

The build comes before the deployment is touched, which collapses a first
deploy to a single rollout and never shows a placeholder page. The deployment
is created on first run and updated thereafter, always targeting the product's
canonical template and always submitting user values as a complete document.
See design D6, D7, and D8.

Preflight is the whole point of the ordering. Packing and building cost
minutes; every question that can be answered from a cheap read is answered
first, in this order:

1. the project file, and that its recorded deployment applies to this
   environment — a cross-environment deploy needs `--recreate`,
2. `GET /api/me` — the first request that actually exercises the credential,
3. `GET /api/products` — the product and its canonical template,
4. the recorded deployment, so one deleted out of band is reported here rather
   than after a four-minute build,
5. any newly required value, by asking,
6. the hostname, but only when it is new or changed (design D14).

What preflight cannot catch is a template that narrowed rather than grew: a
tightened `pattern` or a property removed under `additionalProperties: false`
passes every check above and is refused at release, after the build is spent.
That refusal arrives as a 409 indistinguishable by status from "retry in a
moment", which is why `describe_conflict` reads the `detail` and not the code.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import IO, Any, Callable, Dict, List, Optional, Tuple

import httpx

from . import FreepodError, RolloutFailed, UsageError
from . import subdomain as subdomain_module
from . import tos
from .api import ApiClient, _json_code, _json_detail
from .archive import packed_archive, report
from .build import build_image
from . import vars as vars_module
from .config import BUILD_WAIT_SECONDS, CUSTOM_PRODUCT_SLUG, ROLLOUT_WAIT_SECONDS
from .project import PROJECT_FILE, Project, require_project
from .values import (
    HOSTNAME_REASONS,
    ValueCollector,
    describe_reason,
    is_hostname_property,
    missing_required,
    normalize_hostname,
)

#: Statuses a rollout ends in. `pending` is not among them — it means a paid
#: plan is awaiting payment, which this client never selects.
TERMINAL_STATUSES = frozenset({"ready", "error"})

#: Statuses the platform accepts an update from. The guard is atomic and
#: server-side (`WHERE status IN ('ready','error')`), so this set is a mirror
#: of it rather than the authority.
SETTLED_STATUSES = frozenset({"ready", "error"})

#: A deployment that reaches either of these while we watch it is gone, and no
#: amount of further polling will bring it back.
GONE_STATUSES = frozenset({"deleting", "deleted"})

STATUS_ERROR = "error"

#: The schema property the built image is delivered through.
IMAGE_KEY = "image"

#: How often to re-read a deployment while waiting. The reconciler's own work
#: is measured in tens of seconds, so a faster poll only adds requests.
POLL_SECONDS = 3.0

# The `detail` strings the platform's release conflicts carry. Prefix matching
# on a human-readable message is fragile — these are the platform's exception
# arguments, not a documented vocabulary — so each mapping is pinned by a test
# and anything unrecognized is quoted verbatim rather than guessed at.
DETAIL_SCHEMA_INVALID = "product template has an invalid values_schema_json:"
DETAIL_VALUES_INVALID = "user_values_json is invalid:"
DETAIL_NOT_READY = "Deployment is not in ready state"
DETAIL_IN_PROGRESS = "A deployment job is already queued or running"
DETAIL_DOWNGRADE = "Can only upgrade to newer versions, not downgrade"
DETAIL_CROSS_PRODUCT = "Upgrade template must belong to the same product"
DETAIL_NOT_CANONICAL = "Template is not the current canonical for this product"
DETAIL_DUPLICATE = "Deployment already exists"


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _silence(_message: str) -> None:
    """The `--quiet` echo."""


class _Discard:
    """A write sink for a build log nobody asked to see.

    Not an `io.BytesIO`: a quiet deploy of a large project would otherwise
    accumulate the entire buildkit log in memory purely to throw it away.
    """

    def write(self, data: bytes) -> int:
        return len(data)

    def flush(self) -> None:
        pass


# --------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------


class Preflight:
    """Everything established before a byte is packed."""

    def __init__(
        self,
        project: Project,
        user_id: int,
        product: Dict[str, Any],
        template: Dict[str, Any],
        values: Dict[str, Any],
        deployment: Optional[Dict[str, Any]],
        plan: Optional[Dict[str, Any]] = None,
    ):
        self.project = project
        self.user_id = user_id
        self.product = product
        self.template = template
        self.values = values
        self.deployment = deployment
        self.plan = plan

    @property
    def schema(self) -> Dict[str, Any]:
        return self.template.get("values_schema_json") or {}

    @property
    def template_id(self) -> int:
        return self.template["id"]

    @property
    def deployment_template_id(self) -> Optional[int]:
        if not self.deployment:
            return None
        value = self.deployment.get("desired_template_id")
        return value if isinstance(value, int) else None


def preflight(
    api: ApiClient,
    env_name: str,
    *,
    root: Optional[Path] = None,
    recreate: bool = False,
    interactive: bool = True,
    echo: Callable[[str], None] = _log,
) -> Preflight:
    """Read everything a deploy depends on, cheapest and most fatal first."""
    project = require_project(root)

    if project.env != env_name and project.deployment and not recreate:
        # The recorded deployment is minted on another environment, and no
        # request to this one can reach it. Deploying here would start fresh
        # and leave it running but unaddressable from this project — a
        # consequence that needs the same confirmation as --recreate.
        raise UsageError(
            f"{project.path} records deployment "
            f"'{project.deployment_name}' on '{project.env}', but this command "
            f"targets '{env_name}'.\n"
            f"  The deployment would keep running, but this project could no "
            f"longer address it. Re-run with --recreate to point the project "
            f"at a new deployment on '{env_name}'."
        )

    if recreate and project.deployment:
        echo(
            f"--recreate: discarding the pointer to deployment "
            f"'{project.deployment_name}' ({project.deployment_id}). It is not "
            f"deleted — if it still exists, it keeps running unattended."
        )
        # The pointer stays on the project until the replacement exists.
        # Clearing it here would be persisted by any save between now and the
        # create — `_settle_values` writes one whenever the template requires a
        # value this file lacks — and a deploy that then failed would leave a
        # deployment nothing can address. A pointer to something that may
        # already be gone is strictly the better wreckage.

    # `/api/me` first: the reads below are on the edge's skip-auth list and are
    # answered anonymously however bad the credential is. See design D15.
    user_id = api.me()["id"]

    product = api.find_product(CUSTOM_PRODUCT_SLUG)
    if product is None:
        raise FreepodError(
            f"this instance does not offer user-supplied application deployments "
            f"({api.env.api_base} publishes no '{CUSTOM_PRODUCT_SLUG}' product)."
        )

    template = product.get("template") or {}
    if not template.get("id"):
        raise FreepodError(
            f"the '{CUSTOM_PRODUCT_SLUG}' product publishes no current template, so "
            f"there is nothing to deploy against — this is a platform problem, "
            f"please report it."
        )

    schema = template.get("values_schema_json") or {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    if IMAGE_KEY not in properties:
        # Without it there is nowhere to put the build's output, and the schema
        # is `additionalProperties: false`, so inventing a key would be refused
        # at release — after the build had already been spent.
        raise FreepodError(
            f"the '{CUSTOM_PRODUCT_SLUG}' product's template {template['id']} declares "
            f"no '{IMAGE_KEY}' value, so a locally built image cannot be delivered to "
            f"it — this is a platform problem, please report it."
        )

    # `--recreate` is a decision to abandon the recorded deployment, so its
    # state is not worth a request: whatever it says, this deploy creates.
    deployment = None if recreate else _read_deployment(api, user_id, project)

    # Everything above is a read. Everything below may ask a question, so the
    # cheap fatal checks are exhausted first: there is no point collecting a
    # hostname, or asking anyone to accept terms, for a deploy that a plain
    # `GET` already knows cannot succeed.
    #
    # Both of these are create-only preconditions. Plans are read here rather
    # than at release, which D6 does not list among the preflight reads but the
    # principle it states does: an instance with no free plan refuses every
    # time, and one cheap read turns that from a refusal after a four-minute
    # build into an instant one. Observed, not hypothetical — the `custom`
    # product on dev published no plans at all.
    plan = None
    if deployment is None:
        plan = select_free_plan(api, product)
        subdomain_module.require(api)
        # Only a create is gated on the terms; an update is not. Asking on
        # every deploy would be nagging for a fact the platform records once.
        tos.require(api, interactive=interactive, echo=echo)

    values = _settle_values(
        api,
        project,
        schema,
        deployment,
        interactive=interactive,
        echo=echo,
    )

    return Preflight(project, user_id, product, template, values, deployment, plan)


def _read_deployment(
    api: ApiClient, user_id: int, project: Project
) -> Optional[Dict[str, Any]]:
    """The recorded deployment, or a refusal naming `--recreate`.

    A deployment deleted on the platform still leaves its pointer in a file
    that is committed, so this is the common way a project goes stale. Catching
    it here is the difference between one cheap read and a spent build.
    """
    deployment_id = project.deployment_id
    if not deployment_id:
        return None

    response = api.get(f"/api/users/{user_id}/deployments/{deployment_id}")
    if response.status_code == 404:
        raise FreepodError(
            f"{project.path} points at deployment {deployment_id}"
            f"{f' (' + project.deployment_name + ')' if project.deployment_name else ''}, "
            f"which no longer exists on '{project.env}'.\n"
            f"  It was deleted outside this project. Run `freepod deploy --recreate` "
            f"to create a new deployment and re-point {PROJECT_FILE} at it."
        )
    if not response.is_success:
        raise FreepodError(
            f"could not read deployment {deployment_id}: HTTP {response.status_code} "
            f"{response.text.strip()[:300]}"
        )
    return response.json()


def _settle_values(
    api: ApiClient,
    project: Project,
    schema: Dict[str, Any],
    deployment: Optional[Dict[str, Any]],
    *,
    interactive: bool,
    echo: Callable[[str], None],
) -> Dict[str, Any]:
    """Fill in whatever the template requires and the file does not carry.

    Asking is deliberate: sending the user back to `init` would discard the
    deployment pointer, which is the one thing in the file that cannot be
    reconstructed.
    """
    values = dict(project.user_values)
    missing = missing_required(schema, values)
    hostname_key = _hostname_key(schema)

    if missing:
        echo(
            f"The product template requires "
            f"{'a value' if len(missing) == 1 else 'values'} this project does not "
            f"carry yet: {', '.join(missing)}."
        )
        collector = ValueCollector(
            schema,
            account_fqdn=_account_fqdn(api),
            check_hostname=api.check_hostname,
            interactive=interactive,
        )
        values = collector.collect(values, only_missing=True)
        project.user_values = dict(values)
        project.save()

    if hostname_key:
        values[hostname_key] = _settle_hostname(
            api,
            values[hostname_key],
            deployment,
            # A value just prompted for was already checked inside the prompt
            # loop, where a refusal could be answered with another try.
            already_checked=hostname_key in missing,
            echo=echo,
        )

    return values


def _settle_hostname(
    api: ApiClient,
    value: str,
    deployment: Optional[Dict[str, Any]],
    *,
    already_checked: bool,
    echo: Callable[[str], None],
) -> str:
    """Normalize the hostname, and check it only when it is new or changed.

    `GET /api/hostnames/{fqdn}` runs without `exclude_deployment_id`, so
    re-checking a name we already hold reports `in_use` against ourselves — and
    for a custom domain it performs a live DNS lookup that is slow and
    transiently failure-prone. See design D14.
    """
    fqdn = normalize_hostname(value, _account_fqdn(api) if "." not in value else None)
    current = (deployment or {}).get("hostname") or ""

    if already_checked:
        return fqdn
    if fqdn.lower() == current.lower():
        return fqdn

    verdict = api.check_hostname(fqdn)
    if not verdict.get("usable", False):
        raise FreepodError(
            f"{fqdn}: {describe_reason(verdict.get('reason'))}.\n"
            f"  Edit 'hostname' in {PROJECT_FILE} and re-run — nothing has been "
            f"built or deployed."
        )
    if current:
        echo(f"Hostname {current} → {fqdn}.")
    return fqdn


def _hostname_key(schema: Dict[str, Any]) -> Optional[str]:
    """The required property the platform will treat as the hostname, if any."""
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None
    required = schema.get("required")
    names = required if isinstance(required, list) else []
    for name in names:
        spec = properties.get(name)
        if isinstance(spec, dict) and is_hostname_property(spec):
            return name
    return None


def _account_fqdn(api: ApiClient) -> Optional[str]:
    """The account's domain name, tolerating its absence.

    Only needed to complete a bare label into an FQDN; a deploy whose hostname
    is already qualified should not fail because this read did. A create with no
    domain name at all was already refused in preflight.
    """
    try:
        return subdomain_module.held(subdomain_module.read(api))
    except FreepodError:
        return None


# --------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------


def select_free_plan(api: ApiClient, product: Dict[str, Any]) -> Dict[str, Any]:
    """The first plan whose current template costs nothing.

    Plans arrive ordered by `sort_order`, each embedding its current template
    with the price, so this is one read and no second lookup. Anything priced
    would put the deployment in `pending` behind a checkout page the client
    cannot drive.
    """
    plans = api.get_json(f"/api/products/{product['id']}/plans")
    if not isinstance(plans, list) or not plans:
        raise FreepodError(
            f"the '{product.get('slug')}' product publishes no plans, so no "
            f"deployment can be created against it — this is a platform "
            f"configuration problem, please report it."
        )

    for plan in plans:
        template = plan.get("template") or {}
        if template.get("price_cents") == 0 and template.get("id"):
            return plan

    offered = ", ".join(str(plan.get("name")) for plan in plans)
    raise FreepodError(
        f"the '{product.get('slug')}' product offers no free plan ({offered}), and "
        f"this client only supports free plans — a paid plan is created behind a "
        f"checkout page, which needs the web UI. Nothing has been created."
    )


# --------------------------------------------------------------------------
# Release
# --------------------------------------------------------------------------


def describe_conflict(detail: Optional[str], *, move: Optional[str] = None) -> Tuple[str, bool]:
    """Read a release 409's `detail`. Returns `(message, worth_retrying)`.

    The status cannot carry the distinction: `ERROR_STATUS` maps
    `HostnameException`, `IntegrityException`, and `DeploymentInProgressException`
    all to 409, so "conflict" spans a transient rollout collision and a schema
    failure no retry can ever resolve. Telling the user to try again in the
    second case is worse than saying nothing.
    """
    text = (detail or "").strip()

    if text.startswith(DETAIL_SCHEMA_INVALID):
        return (
            "the product template's own values schema is invalid, so nothing can be "
            "deployed against it. This is a platform defect — your configuration and "
            "your values are not at fault, and changing them will not help.\n"
            f"  The platform said: {text}\n"
            "  Please report it. The built image is unaffected.",
            False,
        )

    if text.startswith(DETAIL_VALUES_INVALID):
        moved = f" being moved to ({move})" if move else ""
        return (
            f"the values in {PROJECT_FILE} no longer satisfy the product template"
            f"{moved}.\n"
            f"  The platform said: {text}\n"
            f"  Retrying cannot help: the template narrowed what it accepts, so the "
            f"values have to change. The build succeeded and is not lost.",
            False,
        )

    if text in HOSTNAME_REASONS:
        return (
            f"the hostname was refused: {describe_reason(text)}.\n"
            f"  Edit 'hostname' in {PROJECT_FILE} and re-run.",
            False,
        )

    if text == DETAIL_NOT_READY:
        return (
            "the deployment is not in a state that accepts an update — it went back "
            "to provisioning between the wait and the release.\n"
            "  This is worth retrying in a moment.",
            True,
        )

    if text == DETAIL_IN_PROGRESS:
        return (
            "another operation on this deployment is already queued or running.\n"
            "  This is worth retrying once it finishes.",
            True,
        )

    if text == DETAIL_DOWNGRADE:
        return (
            "the deployment already runs a newer product template than the one the "
            "platform now publishes as current, and templates only move forward.\n"
            "  Nothing you can change locally affects this; please report it.",
            False,
        )

    if text == DETAIL_CROSS_PRODUCT:
        return (
            "the template being moved to belongs to a different product than the "
            "deployment does.\n"
            "  Nothing you can change locally affects this; please report it.",
            False,
        )

    if text == DETAIL_NOT_CANONICAL:
        return (
            "the product's current template moved while this deploy was running, so "
            "the one it was built against is no longer canonical.\n"
            "  Re-running picks up the new template.",
            True,
        )

    if text == DETAIL_DUPLICATE:
        return (
            "a deployment for this account already holds that hostname on that "
            "template.\n"
            f"  Either point {PROJECT_FILE} at it, or choose a different hostname.",
            False,
        )

    # Deliberately not guessed at. A message invented for an unrecognized
    # detail would be wrong exactly when it mattered most.
    return (
        f"the platform refused the release: {text}" if text
        else "the platform refused the release with a conflict and no explanation.",
        False,
    )


def _conflict(response: httpx.Response, *, move: Optional[str] = None) -> FreepodError:
    message, retryable = describe_conflict(_json_detail(response), move=move)
    if retryable:
        message = f"{message}\n  The image is already built; a re-run reuses it."
    return FreepodError(message)


def describe_move(from_id: Optional[int], to_template: Dict[str, Any]) -> Optional[str]:
    """`4 → 5 (chart custom 0.1.0 → 0.2.0)`, or None when nothing moved."""
    to_id = to_template.get("id")
    if from_id is None or from_id == to_id:
        return None
    return f"{from_id} → {to_id}"


def _announce_move(
    preflight_result: Preflight, echo: Callable[[str], None]
) -> Optional[str]:
    """Say that the canonical template moved, rather than moving silently."""
    move = describe_move(preflight_result.deployment_template_id, preflight_result.template)
    if move is None:
        return None

    was = (preflight_result.deployment or {}).get("desired_template") or {}
    now = preflight_result.template
    detail = ""
    if was.get("chart_version") and was.get("chart_version") != now.get("chart_version"):
        chart = str(now.get("chart_ref", "")).rsplit("/", 1)[-1]
        detail = f" (chart {chart} {was['chart_version']} → {now['chart_version']})"
    echo(f"Product template {move}{detail}.")
    return move


def create_deployment(
    api: ApiClient,
    user_id: int,
    template_id: int,
    plan_template_id: int,
    values: Dict[str, Any],
    *,
    build_id: Optional[str] = None,
) -> Dict[str, Any]:
    """`POST /api/users/{user_id}/deployments` — one rollout, image included."""
    body = {
        "desired_template_id": template_id,
        "plan_template_id": plan_template_id,
        "user_values_json": values,
    }
    if build_id is not None:
        body["build_id"] = build_id
    response = api.post(f"/api/users/{user_id}/deployments", json=body)
    if response.status_code == 409:
        raise _conflict(response)
    if response.status_code == 400 and _json_code(response) == subdomain_module.DEPLOY_REFUSAL_CODE:
        raise FreepodError(
            f"the platform refused the deployment because this account does not "
            f"have a domain name.\n"
            f"  Choose one at {api.env.api_base}, then re-run.\n"
            f"  The build succeeded and is not lost."
        )
    if response.status_code == 400 and _json_detail(response) == tos.DEPLOY_REFUSAL:
        # Preflight settles this, so reaching it means the acceptance was
        # withdrawn in between, or the client skipped the check. Either way it
        # is not the generic "your values are wrong" that a 400 usually means,
        # and reporting it as one would send the user to edit a correct file.
        raise FreepodError(
            f"the platform refused the deployment because this account has not "
            f"accepted its terms.\n"
            f"  Run `freepod login --env {api.env.name}` to accept them, or accept "
            f"them at {api.env.api_base}, then re-run.\n"
            f"  The build succeeded and is not lost."
        )
    if response.status_code != 201:
        raise FreepodError(
            f"could not create the deployment: HTTP {response.status_code} "
            f"{response.text.strip()[:300]}"
        )

    envelope = response.json()
    if envelope.get("checkout_url"):
        raise FreepodError(
            "the platform returned a checkout page for this deployment, which means "
            "the selected plan is not free. This client only supports free plans; "
            "finish or cancel the deployment in the web UI."
        )
    return envelope["deployment"]


def update_deployment(
    api: ApiClient,
    user_id: int,
    deployment_id: str,
    template_id: int,
    values: Dict[str, Any],
    *,
    move: Optional[str] = None,
    build_id: Optional[str] = None,
) -> Dict[str, Any]:
    """`PUT` the same route, with the complete user-values document.

    Complete because the platform replaces stored values wholesale: omitting
    the key reuses what is stored, but a partial object does not merge, so
    sending `{"image": …}` alone fails on the missing required hostname. See
    design D8.
    """
    body: Dict[str, Any] = {
        "desired_template_id": template_id,
        "user_values_json": values,
    }
    if build_id is not None:
        body["build_id"] = build_id
    response = api.put(f"/api/users/{user_id}/deployments/{deployment_id}", json=body)
    if response.status_code == 409:
        raise _conflict(response, move=move)
    if not response.is_success:
        raise FreepodError(
            f"could not update the deployment: HTTP {response.status_code} "
            f"{response.text.strip()[:300]}"
        )
    return response.json()


# --------------------------------------------------------------------------
# Waiting
# --------------------------------------------------------------------------


def read_deployment(api: ApiClient, user_id: int, deployment_id: str) -> Dict[str, Any]:
    response = api.get(f"/api/users/{user_id}/deployments/{deployment_id}")
    if response.status_code == 404:
        raise FreepodError(
            f"deployment {deployment_id} disappeared while this deploy was running — "
            f"it was deleted from elsewhere."
        )
    if not response.is_success:
        raise FreepodError(
            f"could not read deployment {deployment_id}: HTTP {response.status_code} "
            f"{response.text.strip()[:300]}"
        )
    return response.json()


def wait_until_settled(
    api: ApiClient,
    user_id: int,
    deployment: Dict[str, Any],
    *,
    timeout: int = ROLLOUT_WAIT_SECONDS,
    poll: float = POLL_SECONDS,
    echo: Callable[[str], None] = _log,
) -> Dict[str, Any]:
    """Wait until the deployment is in a state the platform accepts an update from.

    The update is guarded by an atomic `WHERE status IN ('ready','error')`, so
    releasing into a rollout already in flight is refused rather than queued.
    """
    if deployment.get("status") in SETTLED_STATUSES:
        return deployment

    deployment_id = deployment["id"]
    reported: Optional[str] = None
    deadline = time.monotonic() + timeout

    while True:
        status = deployment.get("status")
        if status in SETTLED_STATUSES:
            return deployment
        if status in GONE_STATUSES:
            raise FreepodError(
                f"the deployment is {status} and cannot be updated. Run "
                f"`freepod deploy --recreate` to create a new one."
            )
        if status != reported:
            echo(f"  Waiting for the deployment to settle (currently {status})...")
            reported = status
        if time.monotonic() >= deadline:
            raise FreepodError(
                f"stopped waiting after {timeout}s for deployment {deployment_id} to "
                f"leave '{status}'. It is still rolling out on the platform; nothing "
                f"was canceled. The built image is not lost — re-run to release it."
            )
        time.sleep(poll)
        deployment = read_deployment(api, user_id, deployment_id)


def follow_rollout(
    api: ApiClient,
    user_id: int,
    deployment_id: str,
    generation: int,
    *,
    timeout: int = ROLLOUT_WAIT_SECONDS,
    poll: float = POLL_SECONDS,
    echo: Callable[[str], None] = _log,
) -> Dict[str, Any]:
    """Poll until *our* rollout is terminal, not merely until one is.

    `generation` is incremented atomically by the update and returned with it.
    A `ready` carrying an older generation is the previous rollout's, and
    reporting it as success would announce an address serving the old image.
    """
    reported: Optional[str] = None
    deadline = time.monotonic() + timeout

    while True:
        record = read_deployment(api, user_id, deployment_id)
        status = record.get("status")
        current = record.get("generation", 0)

        if current >= generation and status in TERMINAL_STATUSES:
            return record
        if status in GONE_STATUSES:
            raise FreepodError(
                f"deployment {deployment_id} became '{status}' during the rollout — "
                f"it was deleted from elsewhere."
            )

        if status != reported:
            echo(f"  {status}...")
            reported = status

        if time.monotonic() >= deadline:
            raise FreepodError(
                f"stopped waiting after {timeout}s. Deployment {deployment_id} is "
                f"still rolling out on the platform — it was not canceled. Check it "
                f"with `freepod deploy` again, or in the web UI."
            )
        time.sleep(poll)


def address(deployment: Dict[str, Any]) -> Optional[str]:
    hostname = deployment.get("hostname")
    return f"https://{hostname}" if hostname else None


# --------------------------------------------------------------------------
# The pipeline
# --------------------------------------------------------------------------


def release(
    api: ApiClient,
    state: Preflight,
    image: str,
    *,
    build_id: Optional[str] = None,
    timeout: int = ROLLOUT_WAIT_SECONDS,
    poll: float = POLL_SECONDS,
    echo: Callable[[str], None] = _log,
) -> str:
    """Create or update the deployment, then follow the rollout. Returns the address.

    `build_id` names the build that produced `image`, and is recorded on the
    platform's release rather than on the deployment. Optional so that a caller
    releasing an image it did not just build still works.
    """
    values = dict(state.values)
    values[IMAGE_KEY] = image

    if state.deployment is None:
        plan = state.plan or select_free_plan(api, state.product)
        echo(f"Creating a deployment on the '{plan.get('name')}' plan...")
        record = create_deployment(
            api,
            state.user_id,
            state.template_id,
            plan["template"]["id"],
            values,
            build_id=build_id,
        )
        # Written before the rollout is awaited: a deployment that exists but
        # is not recorded is one this project can never address again. The
        # environment travels with the pointer, in the same write: a file that
        # recorded a deployment while still declaring another environment
        # would point at an id the declared environment cannot answer.
        if state.project.env != api.env.name:
            state.project.env = api.env.name
        state.project.record_deployment(record["id"], record["name"])
        echo(f"Created deployment '{record['name']}' ({record['id']}).")
    else:
        settled = wait_until_settled(
            api, state.user_id, state.deployment, timeout=timeout, poll=poll, echo=echo
        )
        move = _announce_move(state, echo)
        echo(f"Releasing to deployment '{settled.get('name')}'...")
        record = update_deployment(
            api,
            state.user_id,
            settled["id"],
            state.template_id,
            values,
            move=move,
            build_id=build_id,
        )

    final = follow_rollout(
        api,
        state.user_id,
        record["id"],
        record.get("generation", 0),
        timeout=timeout,
        poll=poll,
        echo=echo,
    )

    if final.get("status") == STATUS_ERROR:
        raise RolloutFailed(
            f"the rollout failed for deployment {final.get('name')} ({final['id']}).\n"
            f"  The platform recorded: {final.get('last_error') or 'no error message'}"
        )

    live = address(final)
    if live is None:
        raise FreepodError(
            f"deployment {final['id']} is ready but carries no hostname — this is an "
            f"unexpected platform condition, please report it."
        )
    return live


def announce_pending_vars(
    api: ApiClient, state: "Preflight", *, echo: Callable[[str], None] = _log
) -> None:
    """Report configuration this rollout will apply along with the code."""
    deployment = state.deployment
    if not deployment or not deployment.get("pending"):
        return
    count = vars_module.pending_count(api, state.user_id, deployment)
    if count == 0:
        return
    subject = "var" if count == 1 else "vars"
    measured = "some" if count is None else str(count)
    echo(f"This rollout will also apply {measured} pending {subject}.")


def applied_image(deployment: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """The image the deployment is running, and the build that produced it."""
    applied = deployment.get("applied_release") or {}
    values = applied.get("values_json") or {}
    image = values.get(IMAGE_KEY)
    return (image if isinstance(image, str) and image else None), applied.get("build_id")


def release_current(
    api: ApiClient,
    env_name: str,
    *,
    root: Optional[Path] = None,
    interactive: bool = True,
    timeout: int = ROLLOUT_WAIT_SECONDS,
    poll: float = POLL_SECONDS,
    echo: Callable[[str], None] = _log,
) -> str:
    """Roll the deployment again on the image it already runs. Returns the address.

    The build reference is carried forward explicitly: an update omitting it
    writes a release with no link to the build that produced the image. See
    design D11.
    """
    state = preflight(api, env_name, root=root, interactive=interactive, echo=echo)
    if state.deployment is None:
        raise FreepodError(
            "this project has no deployment yet, so there is nothing to roll.\n"
            "  Run `freepod deploy` to create one."
        )
    image, build_id = applied_image(state.deployment)
    if image is None:
        raise FreepodError(
            f"deployment '{state.deployment.get('name')}' has never completed a "
            f"rollout, so there is no image to release.\n"
            f"  Run `freepod deploy` to build and release one."
        )
    announce_pending_vars(api, state, echo=echo)
    echo(f"Releasing {image} again.")
    return release(
        api, state, image, build_id=build_id, timeout=timeout, poll=poll, echo=echo
    )


def deploy(
    api: ApiClient,
    env_name: str,
    *,
    root: Optional[Path] = None,
    recreate: bool = False,
    honor_gitignore: bool = True,
    interactive: bool = True,
    verbose: bool = False,
    quiet: bool = False,
    build_timeout: int = BUILD_WAIT_SECONDS,
    rollout_timeout: int = ROLLOUT_WAIT_SECONDS,
    poll: float = POLL_SECONDS,
    out: Optional[IO[bytes]] = None,
    store: Optional[httpx.Client] = None,
    echo: Callable[[str], None] = _log,
) -> str:
    """Preflight, pack, upload, build, release. Returns the live address.

    `store` reaches the object store, which is a different host with a
    different credential model; left unset the upload opens its own client.

    Nothing here writes to stdout. The address is returned, and the caller
    decides where a result belongs.
    """
    if quiet:
        # `--quiet` is "only the result and real errors". Everything a deploy
        # narrates — the packing report, the progress bar, the status lines,
        # and the platform's own build log — is diagnostics, so all of it goes.
        echo = _silence
        out = out if out is not None else _Discard()

    state = preflight(
        api,
        env_name,
        root=root,
        recreate=recreate,
        interactive=interactive,
        echo=echo,
    )
    announce_pending_vars(api, state, echo=echo)

    with packed_archive(
        state.project.root,
        honor_gitignore=honor_gitignore,
        on_skip=None if quiet else (lambda name, reason: echo(f"  skipped {name}: {reason}")),
    ) as (handle, size, members):
        if not quiet:
            report(size, members, verbose=verbose, echo=echo)
        built = build_image(
            api,
            state.user_id,
            handle,
            size,
            client=store,
            out=out,
            timeout=build_timeout,
            quiet=quiet,
            echo=echo,
        )

    echo(f"Built {built.image}.")
    return release(
        api,
        state,
        built.image,
        build_id=built.build_id,
        timeout=rollout_timeout,
        poll=poll,
        echo=echo,
    )
