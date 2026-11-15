"""The deploy pipeline: preflight, pack, upload, build, release.

A build belongs to a deployment, which `freepod init` creates. Every deploy
builds against it and releases the build together with the project file in
one update, built as `freepod apply` builds it, always targeting the
product's canonical template. See the `builds-belong-to-deployments` design
D6 and the deployment-identity design D3.

Preflight is the whole point of the ordering. Packing and building cost
minutes; every question that can be answered from a cheap read is answered
first, in this order:

1. the project file: that it records a deployment, on this environment, and
   that its icon can be read,
2. `GET /api/me` — the first request that actually exercises the credential,
3. `GET /api/products` — the product and its canonical template,
4. the recorded deployment, so one deleted out of band is reported here rather
   than after a four-minute build,
5. any newly required value, by asking.

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
from typing import IO, Any, Callable, Dict, Optional, Tuple

import httpx

from . import FreepodError, RolloutFailed
from . import handle as handle_module
from . import tos
from .api import ApiClient, _json_code, _json_detail
from .archive import packed_archive, report
from .build import build_image
from .fields import claimed_body
from . import vars as vars_module
from .config import (
    BUILD_WAIT_SECONDS,
    CUSTOM_PRODUCT_SLUG,
    ROLLOUT_WAIT_SECONDS,
    env_suffix,
    login_command,
)
from .project import PROJECT_FILE, Project, require_project, settle_migration
from .values import (
    HOSTNAME_REASONS,
    ValueCollector,
    check_public_patterns,
    describe_reason,
    is_hostname_property,
    missing_required,
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

CODE_UNDER_MAINTENANCE = "under_maintenance"


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
        deployment: Dict[str, Any],
    ):
        self.project = project
        self.user_id = user_id
        self.product = product
        self.template = template
        self.values = values
        self.deployment = deployment

    @property
    def schema(self) -> Dict[str, Any]:
        return self.template.get("values_schema_json") or {}

    @property
    def template_id(self) -> int:
        return self.template["id"]

    @property
    def deployment_template_id(self) -> Optional[int]:
        value = self.deployment.get("desired_template_id")
        return value if isinstance(value, int) else None


def preflight(
    api: ApiClient,
    env_name: str,
    *,
    root: Optional[Path] = None,
    interactive: bool = True,
    echo: Callable[[str], None] = _log,
) -> Preflight:
    """Read everything a deploy depends on, cheapest and most fatal first."""
    from .apply import linked_project  # apply imports this module

    project = linked_project(root, env_name, "deploy")
    claimed_body(project)  # an unreadable icon fails here, before a build

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

    deployment = read_linked(api, user_id, project)
    settle_migration(project, deployment)
    values = _settle_values(api, project, schema, deployment, interactive=interactive, echo=echo)
    return Preflight(project, user_id, product, template, values, deployment)


def read_linked(api: ApiClient, user_id: int, project: Project) -> Dict[str, Any]:
    """The recorded deployment, or a refusal naming how to re-point the project.

    A deployment deleted on the platform still leaves its pointer in a file
    that is committed, so this is the common way a project goes stale.
    """
    record = _read_deployment(api, user_id, project)
    if record is None:
        raise FreepodError(f"{project.path} records no deployment — this is a client bug")
    return record


def _read_deployment(
    api: ApiClient, user_id: int, project: Project
) -> Optional[Dict[str, Any]]:
    """The recorded deployment, or a refusal naming how to re-point the project.

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
            f"{project.path} points at deployment {deployment_id}, "
            f"which no longer exists{env_suffix(project.env)}.\n"
            f"  It was deleted outside this project. Run `freepod init --force` to "
            f"create a new one, or `freepod link` to point {PROJECT_FILE} at another."
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
    deployment: Dict[str, Any],
    *,
    interactive: bool,
    echo: Callable[[str], None],
) -> Dict[str, Any]:
    """The deployment's stored chart values with the file's keys over them, and
    whatever the template now requires that neither holds, asked for.

    An answer goes with this release only, not into the file: the deployment
    keeps it, and the file holds what the developer chose to manage.
    """
    stored = dict(deployment.get("user_values_json") or {})
    stored.pop(IMAGE_KEY, None)
    values = {**stored, **project.chart_values}
    check_public_patterns(values)
    missing = missing_required(schema, values)
    if not missing:
        return values

    echo(
        f"The product template requires "
        f"{'a value' if len(missing) == 1 else 'values'} this deployment does not "
        f"have yet: {', '.join(missing)}."
    )
    collector = ValueCollector(
        schema,
        suffix=handle_module.held_suffix(api),
        check_hostname=api.check_hostname,
        interactive=interactive,
    )
    return collector.collect(values, only_missing=True)


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


def describe_conflict(
    detail: Optional[str], *, move: Optional[str] = None, built: bool = True
) -> Tuple[str, bool]:
    """Read a release 409's `detail`. Returns `(message, worth_retrying)`.

    `built` says whether an image was built before the refusal. A first deploy
    creates its deployment before building anything, so a refused creation
    must not reassure the user about a build that never ran.

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
            "  Please report it." + (" The built image is unaffected." if built else ""),
            False,
        )

    if text.startswith(DETAIL_VALUES_INVALID):
        moved = f" being moved to ({move})" if move else ""
        return (
            f"the values in {PROJECT_FILE} no longer satisfy the product template"
            f"{moved}.\n"
            f"  The platform said: {text}\n"
            f"  Retrying cannot help: the template narrowed what it accepts, so the "
            f"values have to change."
            + (" The build succeeded and is not lost." if built else ""),
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


def _conflict(
    response: httpx.Response, *, move: Optional[str] = None, built: bool = True
) -> FreepodError:
    if _json_code(response) == CODE_UNDER_MAINTENANCE:
        message, retryable = (
            "the deployment is held for platform maintenance and accepts no release "
            "until it ends.\n  This is worth retrying later.",
            True,
        )
    else:
        message, retryable = describe_conflict(_json_detail(response), move=move, built=built)
    if retryable and built:
        message = f"{message}\n  The image is already built; a re-run reuses it."
    return FreepodError(message)


def describe_move(from_id: Optional[int], to_template: Dict[str, Any]) -> Optional[str]:
    """`4 → 5`, or None when nothing moved."""
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
        detail = f" (version {was['chart_version']} → {now['chart_version']})"
    echo(f"Product template {move}{detail}.")
    return move


class CreateConflict(FreepodError):
    """A refused creation, with the platform's code and detail to act on."""

    def __init__(self, message: str, code: Optional[str], detail: Optional[str]):
        super().__init__(message)
        self.code = code
        self.detail = detail


def create_deployment(
    api: ApiClient,
    user_id: int,
    template_id: int,
    plan_template_id: int,
    values: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """`POST /api/users/{user_id}/deployments`, with no image and no build.

    Nothing has been built yet: a build belongs to a deployment, so the
    deployment comes first and serves the product's placeholder meanwhile.
    `extra` carries the identity and `managed_fields`.
    """
    body = {
        "desired_template_id": template_id,
        "plan_template_id": plan_template_id,
        "user_values_json": values,
        **(extra or {}),
    }
    response = api.post(f"/api/users/{user_id}/deployments", json=body)
    if response.status_code == 409:
        raise CreateConflict(
            str(_conflict(response, built=False)), _json_code(response), _json_detail(response)
        )
    if response.status_code == 400 and _json_code(response) == handle_module.DEPLOY_REFUSAL_CODE:
        raise FreepodError(
            f"the platform refused the deployment because this account does not "
            f"have a handle.\n"
            f"  Choose one at {api.env.api_base}, then re-run."
        )
    if response.status_code == 400 and _json_detail(response) == tos.DEPLOY_REFUSAL:
        # Preflight settles this, so reaching it means the acceptance was
        # withdrawn in between, or the client skipped the check. Either way it
        # is not the generic "your values are wrong" that a 400 usually means,
        # and reporting it as one would send the user to edit a correct file.
        raise FreepodError(
            f"the platform refused the deployment because this account has not "
            f"accepted its terms.\n"
            f"  Run `{login_command(api.env.name)}` to accept them, or accept "
            f"them at {api.env.api_base}, then re-run."
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


def put_update(
    api: ApiClient,
    user_id: int,
    deployment_id: str,
    body: Dict[str, Any],
    *,
    move: Optional[str] = None,
    built: bool = False,
) -> Dict[str, Any]:
    """`PUT` an update body as given: the deployment as the platform returns it."""
    response = api.put(f"/api/users/{user_id}/deployments/{deployment_id}", json=body)
    if response.status_code == 409:
        raise _conflict(response, move=move, built=built)
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
                f"`freepod init --force` to create a new one."
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
    """Release `image` with the file's keys in one update, then follow it. Returns the address.

    The update is built as apply builds it, plus the current template, the
    build and its image. `image` is never claimed as managed: it is a build
    output.
    """
    values = dict(state.values)
    values[IMAGE_KEY] = image
    body: Dict[str, Any] = {
        "desired_template_id": state.template_id,
        "user_values_json": values,
        **claimed_body(state.project),
    }
    if build_id is not None:
        body["build_id"] = build_id

    # A deployment init created moments ago may still be provisioning.
    settled = wait_until_settled(
        api, state.user_id, state.deployment, timeout=timeout, poll=poll, echo=echo
    )
    move = _announce_move(state, echo)
    echo(f"Releasing to deployment '{settled.get('name')}'...")
    record = put_update(api, state.user_id, settled["id"], body, move=move, built=True)

    return finish_rollout(api, state.user_id, record, timeout=timeout, poll=poll, echo=echo)


def finish_rollout(
    api: ApiClient,
    user_id: int,
    record: Dict[str, Any],
    *,
    timeout: int = ROLLOUT_WAIT_SECONDS,
    poll: float = POLL_SECONDS,
    echo: Callable[[str], None] = _log,
) -> str:
    """Follow the rollout the update in `record` started. Returns the address."""
    final = follow_rollout(
        api,
        user_id,
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

    from .power import stopped_notice  # power imports delete, which imports this module

    notice = stopped_notice(final)
    if notice:
        echo(notice)

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


def applied_image(deployment: Dict[str, Any]) -> Optional[str]:
    """The image the deployment is running."""
    applied = deployment.get("applied_release") or {}
    values = applied.get("values_json") or {}
    image = values.get(IMAGE_KEY)
    return image if isinstance(image, str) and image else None


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
    """Roll the build the deployment runs again, so staged vars take effect.

    Naming the running build is what makes the platform release; the project
    file is not sent. Returns the address.
    """
    project = require_project(root)
    if not project.deployment_id:
        raise FreepodError(
            f"{project.path} records no deployment, so there is nothing to roll.\n"
            f"  Run `freepod init` to create one."
        )
    user_id = api.me()["id"]
    record = read_linked(api, user_id, project)
    build = (record.get("applied_release") or {}).get("build_id")
    if not build:
        raise FreepodError(
            f"deployment '{record.get('name')}' runs no build yet, so there is nothing "
            f"to roll again.\n"
            f"  Pending vars take effect with the next `freepod deploy`."
        )
    record = wait_until_settled(api, user_id, record, timeout=timeout, poll=poll, echo=echo)
    echo(f"Releasing '{record.get('name')}' again on its current build.")
    updated = put_update(
        api,
        user_id,
        record["id"],
        {"user_values_json": record.get("user_values_json") or {}, "build_id": str(build)},
    )
    return finish_rollout(api, user_id, updated, timeout=timeout, poll=poll, echo=echo)


def deploy(
    api: ApiClient,
    env_name: str,
    *,
    root: Optional[Path] = None,
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

    state = preflight(api, env_name, root=root, interactive=interactive, echo=echo)
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
            state.deployment["id"],
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
