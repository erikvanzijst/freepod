"""`freepod init`: name the app, claim its hostname, create its deployment.

Init creates the deployment on the canonical template with no image, so it
serves the product's placeholder, claims its name and hostname, and accepts
vars before the first build. It returns once the platform accepts the
creation; provisioning goes on in the background. The project file then
records only the pointer, plus whatever keys a pre-existing file held.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import click

from . import FreepodError, UsageError
from . import deploy as deploy_module
from . import handle as handle_module
from . import tos
from .api import ApiClient
from .config import CUSTOM_PRODUCT_SLUG
from .fields import claimed_body, first_free_name, list_deployments, named
from .project import DEFAULT_ENV, PROJECT_FILE, Project, load
from . import values as values_module
from .values import (
    HOSTNAME_REASONS,
    ValueCollector,
    describe_reason,
    hostname_label,
    normalize_hostname,
)

#: How many hostname candidates are checked before none is offered.
HOSTNAME_SUGGESTIONS = 5


def _log(message: str) -> None:
    click.echo(message, err=True)


class _Answers:
    """Asks on the terminal, or reads piped answers, naming the option to pass
    when there is neither."""

    def __init__(self, ask: Optional[Callable[..., str]] = None):
        self._ask = ask

    def __call__(self, label: str, option: str, default: Optional[str] = None) -> str:
        ask = self._ask or values_module.prompt
        try:
            answer = ask(f"  {label}", default=default) if default else ask(f"  {label}")
        except click.Abort:
            if not sys.stdin.isatty():
                raise UsageError(f"no {label} given and no terminal to ask on: pass {option}")
            raise
        return (answer or "").strip()


def init(
    api: ApiClient,
    root: Path,
    *,
    force: bool = False,
    name: Optional[str] = None,
    hostname: Optional[str] = None,
    echo: Callable[[str], None] = _log,
) -> Tuple[Project, Dict[str, Any]]:
    """Create this project's deployment and record it. Returns the project and the deployment."""
    existing = load(root) if (root / PROJECT_FILE).exists() else None
    if existing is not None and existing.deployment_id and not force:
        raise UsageError(
            f"{existing.path} already records deployment {existing.deployment_id}.\n"
            f"  Re-run with --force to create a new deployment and point this project at "
            f"it; the current one keeps running.\n"
            f"  To change a setting, edit {PROJECT_FILE} and run `freepod apply`."
        )
    interactive = sys.stdin.isatty()
    ask = _Answers()

    # `/api/me` first: the product reads are answered anonymously however bad
    # the credential is. See design D15.
    user_id = api.me()["id"]
    product, template = _custom_product(api)
    schema = template.get("values_schema_json") or {}

    # The checks a first deploy makes, before anything is asked: no point
    # collecting a name for an account that cannot create anything.
    plan = deploy_module.select_free_plan(api, product)
    suffix = handle_module.require(api)
    tos.require(api, interactive=interactive, echo=echo)

    deployments = list_deployments(api, user_id)
    if existing is not None and existing.deployment_id:
        unlinked = next((d for d in deployments if d.get("id") == existing.deployment_id), None)
        label = f"'{unlinked['name']}'" if unlinked else existing.deployment_id
        echo(
            f"Unlinking deployment {label} from this project. It keeps running and "
            f"stays on your dashboard."
        )

    fields = dict(existing.fields) if existing else {}
    chosen_name = _settle_name(fields.get("name"), name, root, deployments, ask, echo)
    hostname_key = deploy_module._hostname_key(schema)
    given_hostname = fields.get(hostname_key) if hostname_key else None
    given_hostname = given_hostname if isinstance(given_hostname, str) else hostname
    values = _settle_values(
        api,
        schema,
        fields,
        hostname_key,
        given_hostname,
        chosen_name,
        suffix,
        interactive,
        ask,
        echo,
    )

    project = existing or Project(root=root)
    extra: Dict[str, Any] = claimed_body(project) if fields else {}
    while True:
        extra["name"] = fields.get("name", chosen_name)
        try:
            record = deploy_module.create_deployment(
                api, user_id, template["id"], plan["template"]["id"], values, extra
            )
            break
        except deploy_module.CreateConflict as conflict:
            if conflict.code == "name_in_use" and "name" not in fields:
                echo(f"  {chosen_name}: that name is now in use. Try again.")
                chosen_name = _ask_name(None, deployments, ask, echo)
                continue
            if hostname_key and conflict.detail in HOSTNAME_REASONS and hostname_key not in fields:
                echo(f"  {values[hostname_key]}: {describe_reason(conflict.detail)}. Try again.")
                values[hostname_key] = _prompt_hostname(
                    api, schema, hostname_key, None, suffix, ask, echo
                )
                continue
            raise

    project.declared_env = None if api.env.name == DEFAULT_ENV else api.env.name
    try:
        project.record_deployment(record["id"], api.env.api_base)
    except OSError as exc:
        raise FreepodError(
            f"created deployment '{record.get('name')}' but could not write "
            f"{project.path}: {exc}\n"
            f"  Run `freepod link {record.get('name')}` to record it."
        ) from None

    address = record.get("hostname")
    echo(
        f"Created '{record.get('name')}'"
        + (f" at https://{address}" if address else "")
        + ". It is being provisioned in the background; run `freepod deploy` to build "
        "and release, or `freepod var set` to configure it first."
    )
    return project, record


def _custom_product(api: ApiClient) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    product = api.find_product(CUSTOM_PRODUCT_SLUG)
    if product is None:
        raise FreepodError(
            f"this instance does not offer user-supplied application deployments "
            f"({api.env.api_base} publishes no '{CUSTOM_PRODUCT_SLUG}' product)."
        )
    template = product.get("template") or {}
    schema = template.get("values_schema_json") or {}
    if not template.get("id") or not schema.get("properties"):
        raise FreepodError(
            f"the '{CUSTOM_PRODUCT_SLUG}' product's template declares no user values "
            f"schema, so there is nothing to configure — this is a platform problem, "
            f"please report it."
        )
    return product, template


# --------------------------------------------------------------------------
# The name
# --------------------------------------------------------------------------


def _settle_name(
    in_file: Any,
    option: Optional[str],
    root: Path,
    deployments: List[Dict[str, Any]],
    ask: _Answers,
    echo: Callable[[str], None],
) -> str:
    if isinstance(in_file, str) and in_file.strip():
        holder = named(deployments, in_file)
        if holder is not None:
            raise FreepodError(
                f"{PROJECT_FILE} names this app '{in_file}', which your deployment "
                f"{_describe(holder)} already uses.\n"
                f"  Change 'name' in {PROJECT_FILE}, or link the project to that "
                f"deployment with `freepod link`."
            )
        return in_file.strip()
    if option is not None and option.strip():
        holder = named(deployments, option)
        if holder is None:
            return option.strip()
        if not sys.stdin.isatty():
            raise UsageError(
                f"--name '{option}': your deployment {_describe(holder)} already uses it"
            )
        echo(f"  {option}: your deployment {_describe(holder)} already uses that name.")
        return _ask_name(None, deployments, ask, echo)
    return _ask_name(first_free_name(deployments, root.name), deployments, ask, echo)


def _ask_name(
    default: Optional[str],
    deployments: List[Dict[str, Any]],
    ask: _Answers,
    echo: Callable[[str], None],
) -> str:
    while True:
        answer = ask("name", "--name", default)
        if not answer:
            default = None
            continue
        holder = named(deployments, answer)
        if holder is None:
            return answer
        echo(f"  {answer}: your deployment {_describe(holder)} already uses that name. Try again.")
        default = None


def _describe(record: Dict[str, Any]) -> str:
    host = record.get("hostname")
    return f"at {host}" if host else str(record.get("id"))


# --------------------------------------------------------------------------
# The hostname and the other required values
# --------------------------------------------------------------------------


def _settle_values(
    api: ApiClient,
    schema: Dict[str, Any],
    fields: Dict[str, Any],
    hostname_key: Optional[str],
    given_hostname: Optional[str],
    name: str,
    suffix: Optional[str],
    interactive: bool,
    ask: _Answers,
    echo: Callable[[str], None],
) -> Dict[str, Any]:
    values = {k: v for k, v in fields.items() if k not in ("name", "description", "icon")}
    if hostname_key:
        values[hostname_key] = _prompt_hostname(
            api,
            schema,
            hostname_key,
            given_hostname,
            suffix,
            ask,
            echo,
            name=name,
            from_file=hostname_key in fields,
        )
    collector = ValueCollector(
        schema, suffix=suffix, check_hostname=api.check_hostname, interactive=interactive
    )
    try:
        return collector.collect(values, only_missing=True)
    except click.Abort:
        if not sys.stdin.isatty():
            raise UsageError(
                f"the product template requires values that were not given, and there "
                f"is no terminal to ask on. Set them in {PROJECT_FILE} and re-run."
            )
        raise


def _prompt_hostname(
    api: ApiClient,
    schema: Dict[str, Any],
    key: str,
    given: Optional[str],
    suffix: Optional[str],
    ask: _Answers,
    echo: Callable[[str], None],
    *,
    name: Optional[str] = None,
    from_file: bool = False,
) -> str:
    """A hostname the platform reports usable: the one given, or one asked for."""
    if given:
        value = normalize_hostname(given)
        verdict = api.check_hostname(value)
        if verdict.get("usable", False):
            return value
        reason = describe_reason(verdict.get("reason"))
        where = f"'{key}' in {PROJECT_FILE}" if from_file else "--hostname"
        if from_file or not sys.stdin.isatty():
            raise FreepodError(f"{where} {value}: {reason}.")
        echo(f"  {value}: {reason}. Try again.")
    default = _suggest_hostname(api, name) if name and not given else None
    spec = (schema.get("properties") or {}).get(key) or {}
    description = spec.get("description")
    if isinstance(description, str) and description.strip():
        echo(f"{key}: {description.strip()}")
    while True:
        answer = normalize_hostname(ask(key, "--hostname", default))
        default = None
        if not answer:
            continue
        shown = answer if "." in answer or not suffix else f"{answer}{suffix}"
        if shown != answer:
            echo(f"  → {shown}")
        verdict = api.check_hostname(answer)
        if verdict.get("usable", False):
            return answer
        echo(f"  {answer}: {describe_reason(verdict.get('reason'))}. Try again.")


def _suggest_hostname(api: ApiClient, name: str) -> Optional[str]:
    """The name as a label, or the first usable `-2`, `-3`… of it, checking at most five."""
    label = hostname_label(name)
    if label is None:
        return None
    candidates = [label] + [f"{label}-{n}" for n in range(2, HOSTNAME_SUGGESTIONS + 1)]
    for candidate in candidates:
        if api.check_hostname(candidate).get("usable", False):
            return candidate
    return None
