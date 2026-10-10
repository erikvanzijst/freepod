"""The `freepod` command-line entry point.

Stream discipline: results go to stdout, everything else to stderr, so a piped
stdout carries only the result. `deploy` prints one line — the live address —
while the build log, the progress bar, and every status line go to stderr.

Section 11 completes the flag surface (`--quiet`, `NO_COLOR`) and the exit-code
table; what is here is what the commands wired up so far need.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

import click

from . import EXIT_ERROR, EXIT_OK, FreepodError, UsageError
from . import bucket as bucket_module
from . import copy as copy_module
from . import database as database_module
from . import delete as delete_module
from . import deploy as deploy_module
from . import history
from . import keys as keys_module
from . import logs as logs_module
from . import objects as objects_module
from . import project
from . import releases as releases_module
from . import s3 as s3_module
from . import skill as skill_module
from . import ssh as ssh_module
from . import tos
from . import vars as vars_module
from .api import ApiClient
from .auth import Session, forget_environment, format_claims, log
from .config import (
    BUILD_WAIT_SECONDS,
    CUSTOM_PRODUCT_SLUG,
    DEFAULT_HTTP_TIMEOUT,
    ENVIRONMENTS,
    LOGIN_WAIT_SECONDS,
    ROLLOUT_WAIT_SECONDS,
    cache_path_hint,
    env_suffix,
    environment_names,
    resolve_environment,
    wait_seconds,
)
from .project import DEFAULT_ENV, PROJECT_FILE, find_project_root, load
from . import subdomain
from .values import ValueCollector, hostname_label


def _declared_environment() -> Optional[str]:
    """The environment this directory's project declares, or None.

    Best-effort, because it runs for every command, including ones with no
    business in the project: a missing file yields None, and a broken one does
    too — the command that actually needs the project loads it itself and
    reports the real problem.
    """
    root = find_project_root()
    if root is None:
        return None
    try:
        name = load(root).env
    except FreepodError:
        return None
    # A name this client does not know is not a reason to refuse a command that
    # never touches the project — `init --force`, the one way to repair the
    # file, included. The commands that use the pointer report it themselves.
    return name if name in ENVIRONMENTS else None


class Context:
    """What every command needs: which environment, and how loud to be."""

    def __init__(
        self,
        env_name: Optional[str],
        verbose: bool,
        quiet: bool,
        timeout: Optional[int],
    ):
        # An explicit --env outranks the project file; without one, a project
        # in this directory decides where the command goes, so the environment
        # is something the user never has to think about.
        project_env = None if env_name is not None else _declared_environment()
        self.env = resolve_environment(env_name, project_env=project_env)
        self.verbose = verbose
        self.quiet = quiet
        self.timeout = timeout

    def say(self, message: str) -> None:
        """Diagnostics, unless silenced. Never the result."""
        if not self.quiet:
            log(message)

    def session(self, force_flow: Optional[str] = None) -> Session:
        return Session(
            self.env,
            timeout=wait_seconds(self.timeout, LOGIN_WAIT_SECONDS),
            force_flow=force_flow,
            verbose=self.verbose,
        )

    def client(self, session: Session) -> ApiClient:
        return ApiClient(
            self.env,
            session,
            timeout=DEFAULT_HTTP_TIMEOUT,
            verbose=self.verbose,
        )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--env",
    "env_name",
    metavar="NAME",
    hidden=True,
)
@click.option("--verbose", is_flag=True, help="show extra detail")
@click.option(
    "--quiet",
    is_flag=True,
    help="suppress progress and diagnostics; results and errors still appear",
)
@click.option(
    "--timeout",
    type=int,
    metavar="SECONDS",
    help="how long to wait for the current operation before giving up (defaults: "
    f"login {LOGIN_WAIT_SECONDS}s, build {BUILD_WAIT_SECONDS}s, rollout "
    f"{ROLLOUT_WAIT_SECONDS}s)",
)
@click.version_option(package_name="freepod")
@click.pass_context
def cli(
    ctx: click.Context,
    env_name: Optional[str],
    verbose: bool,
    quiet: bool,
    timeout: Optional[int],
) -> None:
    """Take a local project directory to a running Freepod deployment."""
    if verbose and quiet:
        raise UsageError("--verbose and --quiet contradict each other; pick one")

    # An unset shell variable expands to this. Falling through to the default
    # would deploy to prod on the strength of a variable the script believed it
    # had set, which is the one outcome an explicit --env must never produce.
    if env_name is not None and not env_name.strip():
        raise UsageError(
            f"--env was given an empty value — name one of {environment_names()}, "
            f"or omit it to use the environment recorded in {PROJECT_FILE}"
        )

    # Left as None, click decides per-stream, which would still color a
    # terminal when `NO_COLOR` asks it not to. False forces the escape codes
    # stripped everywhere.
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        ctx.color = False

    ctx.obj = Context(env_name, verbose, quiet, timeout)


@cli.command()
@click.option(
    "--loopback",
    "flow",
    flag_value="loopback",
    help="sign in through a browser on this machine",
)
@click.option(
    "--device",
    "flow",
    flag_value="device",
    help="sign in by opening a URL on any device, for machines without a browser",
)
@click.option("--force", is_flag=True, help="sign in again even if a stored credential is valid")
@click.pass_obj
def login(context: Context, flow: Optional[str], force: bool) -> None:
    """Sign in to Freepod and store the credential on this machine.

    Opens a browser when one is available; otherwise prints a URL to open on
    any device.
    """
    session = context.session(force_flow=flow)
    session.authenticate(force_login=force)

    with context.client(session) as api:
        me = api.me()

        context.say(
            f"Signed in as {me.get('email')} (user id {me.get('id')})"
            f"{env_suffix(context.env.name)}."
        )
        context.say(f"  flow       : {session.flow_used or 'none — reused a cached credential'}")
        context.say(f"  credential : {session.credential_source}")
        if context.verbose and session.access_token:
            context.say(format_claims(session.access_token))

        # Offered, never required. `login` is also how a headless box and a CI
        # job get a credential, and how someone who only wants `whoami` gets
        # one; refusing to finish over an unaccepted agreement would break all
        # three for a fact only `deploy` actually needs. A decline is recorded
        # nowhere and simply leaves `deploy` to ask again.
        status = tos.settle(api, interactive=sys.stdin.isatty())
        if status == tos.VERSION_UNKNOWN:
            context.say(f"  terms      : not accepted — accept them at {context.env.api_base}.")
        elif status != tos.ACCEPTED:
            context.say(
                "  terms      : not accepted — `freepod deploy` will ask before "
                "creating your first deployment."
            )


@cli.command()
@click.pass_obj
def logout(context: Context) -> None:
    """Remove the stored credential from this machine.

    The credential stays valid until it expires or is revoked from your
    account settings.
    """
    name = context.env.name
    scope = env_suffix(name, "for")
    if forget_environment(name):
        context.say(f"Removed the stored credential{scope} from {cache_path_hint()}.")
    else:
        context.say(f"No stored credential{scope} in {cache_path_hint()}.")
    context.say(
        "Note: this only removes the local copy. The credential stays valid until "
        f"you revoke it under Applications at {context.env.issuer}/account"
    )


@cli.command()
@click.pass_obj
def whoami(context: Context) -> None:
    """Show the account you are signed in as."""
    session = context.session()
    # Never start a login from `whoami`: a command that merely reports identity
    # should say "not authenticated" rather than opening a browser.
    session.authenticate(interactive=False)

    with context.client(session) as api:
        me = api.me()

    click.echo(f"{me.get('email')}")
    click.echo(f"user id: {me.get('id')}")
    if me.get("is_admin"):
        click.echo("admin:   yes")
    if context.verbose and session.access_token:
        context.say(format_claims(session.access_token))


@cli.command()
@click.option(
    "--force",
    is_flag=True,
    help=f"overwrite an existing {PROJECT_FILE}; its deployment keeps running "
    "but is no longer linked to this project",
)
@click.pass_obj
def init(context: Context, force: bool) -> None:
    """Set up the current directory as a Freepod project.

    Asks for the project's settings, such as its hostname, and writes them to
    .freepod.json, which is meant to be committed. Nothing is deployed until
    you run `freepod deploy`.
    \f
    Reads only. No deployment is created — that is `freepod deploy`'s job, so
    that a failure writing the project file cannot leave behind a provisioned
    resource the user cannot see.
    """
    root = Path.cwd()
    target = root / PROJECT_FILE

    if target.exists() and not force:
        raise UsageError(
            f"{target} already exists. Re-run with --force to discard it and start "
            f"over. Its deployment would keep running, but this project could no "
            f"longer update or delete it.\n"
            f"  To change a value, edit {PROJECT_FILE} directly; `freepod deploy` "
            f"asks for anything required that is missing."
        )
    if target.exists() and force:
        existing = project.load(root)
        if existing.deployment_name:
            context.say(
                f"Warning: --force unlinks deployment "
                f"'{existing.deployment_name}' from this project. It keeps "
                f"running, and this project can no longer update it."
            )

    session = context.session()
    session.authenticate(interactive=False)

    with context.client(session) as api:
        # `/api/me` first: everything else init reads is public and would be
        # answered anonymously however bad the credential is. See design D15.
        api.me()

        product = api.find_product(CUSTOM_PRODUCT_SLUG)
        if product is None:
            raise FreepodError(
                f"this instance does not offer user-supplied application deployments "
                f"({context.env.api_base} publishes no '{CUSTOM_PRODUCT_SLUG}' product)."
            )

        template = product.get("template") or {}
        schema = template.get("values_schema_json") or {}
        if not schema.get("properties"):
            raise FreepodError(
                f"the '{CUSTOM_PRODUCT_SLUG}' product's template declares no user "
                f"values schema, so there is nothing to configure — this is a "
                f"platform problem, please report it."
            )

        if context.verbose:
            context.say(f"Product '{product.get('name')}' (template {template.get('id')}).")

        collector = ValueCollector(
            schema,
            account_fqdn=subdomain.require(api),
            check_hostname=api.check_hostname,
            suggested_hostname=hostname_label(root.name),
        )
        values = collector.collect()

    # The file names an environment only when it is not the default, so a
    # project initialized against `FREEPOD_ENV=dev` still stays on dev.
    declared = None if context.env.name == DEFAULT_ENV else context.env.name
    new = project.Project(root=root, env=declared, user_values=values)
    new.save()

    # The path is the result; everything else is commentary.
    click.echo(str(target))
    context.say(
        f"Initialized{env_suffix(context.env.name, 'for')}. Run `freepod deploy` "
        f"to build and release."
    )


@cli.command()
@click.option(
    "--recreate",
    is_flag=True,
    help="create a new deployment instead of updating the current one, which "
    "keeps running",
)
# A negated `is_flag`, not `flag_value=False`; see cli/DEVELOPMENT.md.
@click.option(
    "--no-gitignore",
    "no_gitignore",
    is_flag=True,
    help="also upload files that .gitignore excludes",
)
@click.option(
    "--no-build",
    "no_build",
    is_flag=True,
    help="redeploy the current image without building, e.g. to apply staged vars",
)
@click.pass_obj
def deploy(context: Context, recreate: bool, no_gitignore: bool, no_build: bool) -> None:
    """Build the current project and release it to its deployment.

    Uploads the project directory, builds an image from it and releases it.
    The first deploy also creates the deployment, which shows a placeholder
    page until the first build is live. Settings are checked before anything
    is uploaded, so most mistakes are reported in seconds rather than after a
    build.

    The live address is the only output on stdout; build output and progress
    go to stderr, so `URL=$(freepod deploy)` captures the address.
    \f
    Preflight, then — on a first deploy — create the deployment, then pack,
    upload, build and release, in that order: everything a cheap read can refuse
    is refused before anything is created or built, and a build always belongs
    to a deployment that already exists.
    """
    if no_build and recreate:
        raise UsageError("--no-build releases an existing deployment; --recreate makes a new one")

    session = context.session()
    session.authenticate(interactive=False)

    if no_build:
        with context.client(session) as api:
            address = deploy_module.release_current(
                api,
                context.env.name,
                interactive=sys.stdin.isatty(),
                timeout=wait_seconds(context.timeout, ROLLOUT_WAIT_SECONDS),
            )
        click.echo(address)
        context.say(f"Released. Live at {address}")
        return

    with context.client(session) as api:
        address = deploy_module.deploy(
            api,
            context.env.name,
            recreate=recreate,
            honor_gitignore=not no_gitignore,
            verbose=context.verbose,
            quiet=context.quiet,
            interactive=sys.stdin.isatty(),
            build_timeout=wait_seconds(context.timeout, BUILD_WAIT_SECONDS),
            rollout_timeout=wait_seconds(context.timeout, ROLLOUT_WAIT_SECONDS),
        )

    # The address is the result, and the only thing on stdout. The build log,
    # the progress bar and every status line went to stderr, so
    # `URL=$(freepod deploy)` yields exactly the URL.
    click.echo(address)
    context.say(f"Deployed. Live at {address}")


@cli.command()
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="skip the confirmation prompt (required when not run from a terminal)",
)
@click.option(
    "--no-wait",
    "no_wait",
    is_flag=True,
    help="return once the deletion has started instead of waiting for it to finish",
)
@click.pass_obj
def delete(context: Context, assume_yes: bool, no_wait: bool) -> None:
    """Delete this project's deployment and everything it stores.

    Asks for confirmation first, then waits until the deletion has finished;
    the hostname cannot be reused before then.

    .freepod.json keeps its settings, so a later `freepod deploy` creates a
    new deployment under the same hostname.
    """
    session = context.session()
    session.authenticate(interactive=False)

    with context.client(session) as api:
        delete_module.delete(
            api,
            context.env.name,
            assume_yes=assume_yes,
            wait=not no_wait,
            interactive=sys.stdin.isatty(),
            timeout=wait_seconds(context.timeout, ROLLOUT_WAIT_SECONDS),
            # One echo for progress and for the confirmation preamble alike.
            # `--quiet` silences both, which is why the question itself names
            # the deployment rather than relying on the lines above it.
            echo=context.say,
        )


@cli.command()
@click.option(
    "--limit",
    type=int,
    metavar="N",
    default=history.DEFAULT_LIMIT,
    help=f"how many builds to show (default: {history.DEFAULT_LIMIT})",
)
@click.option("--all", "show_all", is_flag=True, help="show every build, ignoring --limit")
@click.pass_obj
def builds(context: Context, limit: int, show_all: bool) -> None:
    """List this project's builds, most recent first.

    The build the deployment is currently running is marked with `*`.
    `--verbose` shows image references in full.
    """
    if limit <= 0 and not show_all:
        raise UsageError("--limit must be a positive number of builds")

    project_file = _project_deployment(context, lacks="builds")
    session = context.session()
    session.authenticate(interactive=False)

    with context.client(session) as api:
        user_id = api.me()["id"]
        records = history.list_builds(api, user_id, project_file.deployment_id)
        live = history.deployed_image(api, user_id, project_file.deployment_id)

    if not records:
        context.say("This project has no builds yet — `freepod deploy` creates one.")
        return

    shown = records if show_all else records[:limit]
    click.echo(
        history.render(
            history.rows(shown, live_image=live, full_image=context.verbose)
        )
    )

    if live and any(record.get("image") == live for record in shown):
        context.say(
            f"{history.LIVE_MARKER} the build this project's deployment is running."
        )
    if len(shown) < len(records):
        context.say(
            f"Showing {len(shown)} of {len(records)} builds; --all shows every one."
        )


@cli.command()
@click.option(
    "--limit",
    type=int,
    metavar="N",
    default=releases_module.DEFAULT_LIMIT,
    help=f"how many releases to show (default: {releases_module.DEFAULT_LIMIT})",
)
@click.option("--all", "show_all", is_flag=True, help="show every release, ignoring --limit")
@click.pass_obj
def releases(context: Context, limit: int, show_all: bool) -> None:
    """List this project's releases, most recent first.

    A release is one rollout of the deployment: a new build, changed vars, or
    changed settings. The release currently running is marked with `*`, and
    its number is what `freepod log -r` takes. `--verbose` shows image
    references in full.
    """
    if limit <= 0 and not show_all:
        raise UsageError("--limit must be a positive number of releases")

    project_file = project.require_project()

    if project_file.env != context.env.name and project_file.deployment_id:
        raise UsageError(
            f"{project_file.path} records deployment "
            f"'{project_file.deployment_name}' on '{project_file.env}', not on "
            f"'{context.env.name}'.\n"
            f"  Re-run without --env (or with --env {project_file.env}) to list it."
        )

    if not project_file.deployment_id:
        raise UsageError(
            f"{project_file.path} records no deployment, so there are no "
            f"releases to list.\n"
            f"  Run `freepod deploy` to create one."
        )

    session = context.session()
    session.authenticate(interactive=False)

    with context.client(session) as api:
        user_id = api.me()["id"]
        deployment = releases_module.read_deployment(
            api, user_id, project_file.deployment_id
        )
        records = releases_module.list_releases(
            api, user_id, project_file.deployment_id
        )

    if not records:
        context.say(
            f"Deployment '{project_file.deployment_name}' has no releases"
            f"{env_suffix(context.env.name)}."
        )
        return

    live = releases_module.applied_number(deployment)
    shown = records if show_all else records[:limit]
    click.echo(
        releases_module.render_table(shown, live_number=live, full_image=context.verbose)
    )

    if live is not None and any(r.get("number") == live for r in shown):
        context.say(
            f"{releases_module.LIVE_MARKER} the release this deployment is running."
        )
    for note in releases_module.failures(shown):
        context.say(note)
    if len(shown) < len(records):
        context.say(
            f"Showing {len(shown)} of {len(records)} releases; --all shows every one."
        )


def _join(labels: list) -> str:
    """`a`, `a and b`, `a, b and c` — a list a person reads rather than parses."""
    if len(labels) == 1:
        return labels[0]
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


def _project_deployment(context: Context, *, lacks: str = "vars") -> project.Project:
    """The project's recorded deployment, refusing the ways it can be wrong.

    `lacks` names what a project without a deployment has none of, for the
    refusal's wording.
    """
    project_file = project.require_project()
    if project_file.env != context.env.name and project_file.deployment_id:
        raise UsageError(
            f"{project_file.path} records deployment "
            f"'{project_file.deployment_name}' on '{project_file.env}', not on "
            f"'{context.env.name}'.\n"
            f"  Re-run without --env (or with --env {project_file.env})."
        )
    if not project_file.deployment_id:
        raise UsageError(
            f"{project_file.path} records no deployment, so it has no {lacks}.\n"
            f"  Run `freepod deploy` to create one."
        )
    return project_file


def _refuse_unreachable(deployment, project_file, env_name) -> dict:
    """The deployment, or a refusal when it has no container to connect to.

    A settled deployment — ready or error — has a stable container, and `error`
    is precisely the state a shell exists for. Every other state is transitional
    or gone, and a connection there would be refused for a reason the platform
    already told us, so it is said rather than discovered the hard way.
    """
    name = project_file.deployment_name
    if deployment is None:
        raise FreepodError(
            f"deployment '{name}' no longer exists{env_suffix(env_name)} — it may "
            f"have been deleted. Run `freepod deploy` to create a new one."
        )
    status = deployment.get("status")
    if status not in deploy_module.SETTLED_STATUSES:
        hint = (
            "wait for the rollout to finish and try again"
            if status in ("pending", "provisioning")
            else "it has no container to connect to"
        )
        raise FreepodError(
            f"deployment '{name}' is {status}, so it has no container to connect "
            f"to right now — {hint}."
        )
    return deployment


def _ssh_username(deployment: dict) -> str:
    return deployment["id"]


def _connection_setup(
    context: Context,
    project_file: project.Project,
    *,
    require_database: bool = False,
) -> tuple[dict, Optional[dict], str, int, Path, Path]:
    """The pieces a connection to the edge needs, resolved and checked.

    Shared by every command that connects: the deployment (refusing the states
    that have no container to connect to), the database when the command needs
    one, the verified edge, and the one key to offer. Returns
    ``(deployment, database, host, port, key_path, known_hosts)``; ``database``
    is None unless ``require_database`` is set, in which case it is the
    deployment's database details or the command is refused.
    """
    # A missing ssh is a prerequisite, not a fault of this client; report it
    # before spending a round trip the connection could not use anyway.
    ssh_module.require_ssh()

    session = context.session()
    session.authenticate(interactive=False)

    with context.client(session) as api:
        user_id = api.me()["id"]
        deployment = _refuse_unreachable(
            releases_module.read_deployment(api, user_id, project_file.deployment_id),
            project_file,
            context.env.name,
        )
        database = None
        if require_database:
            database = database_module.read(api, user_id, project_file.deployment_id)
            if database is None:
                raise FreepodError(
                    f"deployment '{project_file.deployment_name}' has no database, so "
                    f"there is nothing to connect to. Check `freepod db status`."
                )
        edge = api.ssh_edge()
        host, port, known_hosts = ssh_module.pin_edge(edge)
        registered = keys_module.list_keys(api, user_id)
        key_path = keys_module.resolve_local_key(context.env.name, registered)
    return deployment, database, host, port, key_path, known_hosts


def _connection_args(
    context: Context,
    project_file: project.Project,
    *,
    command: Optional[list] = None,
    require_database: bool = False,
    tty: bool = True,
) -> list:
    """The argv for a session over the deployment's SSH edge.

    Shared by `shell` and `db shell`: resolve the deployment, refuse the states
    that have no container to connect to, verify the edge, name the one key to
    offer, and build the arguments. `command` is what the session runs once it
    lands — nothing for a shell, `psql` for a database session, which the
    sidecar routes to its own client rather than the application container.
    """
    deployment, _database, host, port, key_path, known_hosts = _connection_setup(
        context, project_file, require_database=require_database
    )
    return ssh_module.build_args(
        user=_ssh_username(deployment),
        host=host,
        port=port,
        key_path=key_path,
        known_hosts=known_hosts,
        tty=tty,
        command=command,
    )


def _forward(
    context: Context,
    project_file: project.Project,
    local_port: int,
) -> tuple[list, dict]:
    """The argv for a forward to the deployment's database, and its details.

    The destination is the address the platform reports, passed through
    verbatim: the allowlist at the far end matches it as written, so any
    difference in spelling produces a refusal that reads like an authorization
    failure rather than a typo. A forward runs no session, so it needs no tty
    and no command — the `-L` and `-N` are the whole point of the connection.
    """
    deployment, database, host, port, key_path, known_hosts = _connection_setup(
        context, project_file, require_database=True
    )
    local_forward = f"{local_port}:{database['host']}:{database['port']}"
    args = ssh_module.build_args(
        user=_ssh_username(deployment),
        host=host,
        port=port,
        key_path=key_path,
        known_hosts=known_hosts,
        local_forward=local_forward,
    )
    return args, database


#: The conventional PostgreSQL port, tried first when no local port is given.
CONVENTIONAL_DB_PORT = 5432


def _port_available(port: int) -> bool:
    """Whether a local TCP port can be bound right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _free_local_port() -> int:
    """A local TCP port the kernel will hand out on demand."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def choose_local_port(requested: Optional[int]) -> int:
    """The local port a forward binds, or a specific refusal.

    A port the user named that is unavailable is reported as such — choosing a
    different one silently would bind a port they did not ask for. With no port
    given, the conventional one is tried first and a free one is chosen when it
    is occupied, so an occupied default never fails the command.
    """
    if requested is not None:
        if not _port_available(requested):
            raise FreepodError(
                f"port {requested} is not available on this machine — it is in use "
                f"or reserved. Choose another with --port."
            )
        return requested
    if _port_available(CONVENTIONAL_DB_PORT):
        return CONVENTIONAL_DB_PORT
    return _free_local_port()


def _connection_url(database: dict, host: str, port: int) -> str:
    """A connection URL addressing the given end, carrying the database's credential.

    The credential is percent-encoded rather than concatenated: a password with
    characters that have meaning in a URL would otherwise yield a URL that
    parses to a different password. Today's generated passwords are hexadecimal
    so concatenation happens to work, which is precisely why this is written
    against correctness instead of the generator's current output.
    """
    role = quote(str(database.get("role", "")), safe="")
    password = quote(str(database.get("password", "")), safe="")
    name = quote(str(database.get("database", "")), safe="")
    return f"postgresql://{role}:{password}@{host}:{port}/{name}"


@cli.group()
def var() -> None:
    """Manage your app's environment variables.

    Setting or removing a var redeploys the app so the change takes effect;
    `--stage` saves the change for the next deploy instead.

    A var set with `--secret` is write-only: it is listed with its value
    hidden, and no command can print it back.
    """


@var.command("list")
@click.option("--json", "as_json", is_flag=True, help="print the vars as JSON")
@click.pass_obj
def var_list(context: Context, as_json: bool) -> None:
    """List this deployment's vars.

    The `--json` output can be piped back into `freepod var set -f -`. Secrets
    appear without a value, and an entry without a value leaves that var
    unchanged.
    """
    project_file = _project_deployment(context)
    session = context.session()
    session.authenticate(interactive=False)
    with context.client(session) as api:
        user_id = api.me()["id"]
        payload = vars_module.read(api, user_id, project_file.deployment_id)

    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return
    table = vars_module.render_table(payload)
    if table:
        click.echo(table)
    else:
        context.say("No vars are set.")
    if payload.get("pending"):
        context.say("Some vars are not applied yet. Apply them with `freepod deploy --no-build`.")


@var.command("get")
@click.argument("key")
@click.pass_obj
def var_get(context: Context, key: str) -> None:
    """Print one var's value.

    Fails for a secret var, whose value cannot be read back.
    """
    project_file = _project_deployment(context)
    session = context.session()
    session.authenticate(interactive=False)
    with context.client(session) as api:
        user_id = api.me()["id"]
        payload = vars_module.read(api, user_id, project_file.deployment_id)

    entry = (payload.get("vars") or {}).get(key)
    if entry is None:
        raise UsageError(f"{key} is not set on this deployment")
    if "value" not in entry:
        raise UsageError(f"{key} is secret, so its value cannot be read back")
    click.echo(entry["value"])


@var.command("set")
@click.argument("assignments", nargs=-1)
@click.option("--secret", is_flag=True, help="store these vars write-only")
@click.option(
    "-f",
    "--file",
    "source",
    metavar="FILE",
    help="read vars from FILE: KEY=VALUE lines, or JSON as printed by "
    "`var list --json`; '-' reads stdin",
)
@click.option("--stage", is_flag=True, help="save the vars without redeploying")
@click.pass_obj
def var_set(
    context: Context,
    assignments: tuple,
    secret: bool,
    source: Optional[str],
    stage: bool,
) -> None:
    """Set vars and redeploy so they take effect.

    Accepts `KEY=VALUE` pairs, a bare `KEY` to be prompted for without echo,
    or `-f FILE`. Several vars in one command are applied in one redeploy.

    `--stage` saves them without redeploying, which also works while a deploy
    is in progress. `freepod deploy --no-build` applies staged vars.
    """
    if not assignments and not source:
        raise UsageError("give KEY=VALUE pairs, a bare KEY to be prompted for, or -f FILE")

    entries: Dict[str, Any] = {}
    if source:
        entries.update(vars_module.load_entries(source))
    if assignments:
        entries.update(
            {
                key: {"value": value}
                for key, value in vars_module.parse_assignments(
                    list(assignments), interactive=sys.stdin.isatty()
                ).items()
            }
        )

    session = context.session()
    session.authenticate(interactive=False)
    project_file = _project_deployment(context)

    with context.client(session) as api:
        user_id = api.me()["id"]
        deployment = deploy_module.read_deployment(api, user_id, project_file.deployment_id)
        if secret:
            entries, declared = vars_module.mark_sensitive(entries, deployment)
            if declared:
                context.say(
                    f"--secret ignored for {', '.join(sorted(declared))}: this "
                    f"product's schema decides which of its vars are secret."
                )
        payload = vars_module.write(api, user_id, project_file.deployment_id, entries)
        _finish_var_write(context, api, len(entries), payload, deployment, stage=stage)


@var.command("rm")
@click.argument("keys", nargs=-1, required=True)
@click.option("--stage", is_flag=True, help="save the removal without redeploying")
@click.pass_obj
def var_rm(context: Context, keys: tuple, stage: bool) -> None:
    """Remove vars and redeploy.

    Removing a var that is not set succeeds and changes nothing.
    """
    project_file = _project_deployment(context)
    session = context.session()
    session.authenticate(interactive=False)

    with context.client(session) as api:
        user_id = api.me()["id"]
        deployment = deploy_module.read_deployment(api, user_id, project_file.deployment_id)
        vars_module.remove(api, user_id, project_file.deployment_id, list(keys))
        payload = vars_module.read(api, user_id, project_file.deployment_id)
        _finish_var_write(context, api, len(keys), payload, deployment, stage=stage)


def _finish_var_write(
    context: Context,
    api,
    count: int,
    payload: Dict[str, Any],
    deployment: Dict[str, Any],
    *,
    stage: bool,
) -> None:
    """Report the write, then roll unless the caller asked to stage it.

    A deployment mid-rollout is refused rather than waited on: the vars are
    already recorded, so waiting would hold the terminal for a rollout the
    caller did not ask for.
    """
    subject = "var" if count == 1 else "vars"
    if stage:
        context.say(f"Saved {count} {subject}, not applied yet.")
        context.say("Apply them with `freepod deploy --no-build`.")
        return
    if not payload.get("pending"):
        context.say(f"Saved {count} {subject}; nothing changed, so nothing to redeploy.")
        return

    if deployment.get("status") not in deploy_module.SETTLED_STATUSES:
        raise FreepodError(
            f"deployment '{deployment.get('name')}' is {deployment.get('status')}, "
            f"so it cannot be redeployed right now.\n"
            f"  The {subject} {'is' if count == 1 else 'are'} saved. Apply "
            f"{'it' if count == 1 else 'them'} with `freepod deploy --no-build` "
            f"once the current rollout finishes, or pass --stage to skip this step."
        )

    context.say(f"Saved {count} {subject}. Redeploying...")
    try:
        address = deploy_module.release_current(
            api,
            context.env.name,
            interactive=sys.stdin.isatty(),
            timeout=wait_seconds(context.timeout, ROLLOUT_WAIT_SECONDS),
        )
    except FreepodError as error:
        # Same class, so a failed rollout still exits 5 rather than being
        # flattened into the generic failure code by this re-raise.
        raise type(error)(
            f"{error}\n"
            f"  The vars are saved. Re-run with --stage to skip the redeploy, "
            f"or apply them later with `freepod deploy --no-build`."
        ) from error
    click.echo(address)


@cli.group()
def db() -> None:
    """Your app's PostgreSQL database.

    `db status` shows the database and role name, the password, and storage
    usage. `db shell` opens an interactive psql session. `db proxy` forwards a
    local port to the database and prints a connection URL for it.

    Your running app already has the connection details in its environment
    (`DATABASE_URL`, `PG*`). The database is not reachable from this machine
    directly; `db shell` and `db proxy` connect over SSH.
    """


@db.command("status")
@click.option("--show-password", is_flag=True, help="print the password instead of masking it")
@click.pass_obj
def db_status(context: Context, show_password: bool) -> None:
    """Show this deployment's database, role, password and storage usage.

    The password is masked unless `--show-password` is given.
    """
    project_file = _project_deployment(context)
    session = context.session()
    session.authenticate(interactive=False)
    with context.client(session) as api:
        user_id = api.me()["id"]
        details = database_module.read(api, user_id, project_file.deployment_id)

    if details is None:
        context.say("This deployment has no database.")
        return

    click.echo(database_module.render_status(details, show_password=show_password))
    context.say(
        "\nThis database is reachable from your running app, not from this machine."
    )


@db.command("shell")
@click.pass_obj
def db_shell(context: Context) -> None:
    """Open an interactive psql session in this deployment's database.

    psql runs on the platform, so no PostgreSQL client is needed on this
    machine, and the session works even when your app is down. Exits with
    psql's exit code.
    """
    project_file = _project_deployment(context)
    args = _connection_args(context, project_file, command=["psql"], require_database=True)
    raise SystemExit(ssh_module.run_interactive(args))


@db.command("proxy")
@click.option(
    "--port",
    type=int,
    metavar="PORT",
    help=f"the local port to listen on (default: {CONVENTIONAL_DB_PORT}, or a free "
    "port if that one is in use)",
)
@click.pass_obj
def db_proxy(context: Context, port: Optional[int]) -> None:
    """Forward a local port to the database and print a connection URL.

    The tunnel runs in the foreground until you press Ctrl+C. The URL points at
    the local end of the tunnel, so any client on this machine can use it. It
    is the only output on stdout.
    """
    project_file = _project_deployment(context)
    local_port = choose_local_port(port)
    args, database = _forward(context, project_file, local_port)
    url = _connection_url(database, "localhost", local_port)

    if port is None and local_port != CONVENTIONAL_DB_PORT:
        context.say(
            f"Port {CONVENTIONAL_DB_PORT} is in use; forwarding on "
            f"localhost:{local_port} instead."
        )
    else:
        context.say(f"Forwarding localhost:{local_port} to the database.")
    context.say("Press Ctrl+C to close the tunnel.")

    # The URL is the result and the only thing on stdout.
    click.echo(url)

    # Captured, not streamed: a forward prints little, and the one failure worth
    # naming — a refused destination — is only visible in ssh's stderr.
    try:
        proc = ssh_module.run(args, capture_output=True)
    except KeyboardInterrupt:
        # Interrupting the tunnel is how it ends; the port is released with it.
        context.say("")
        raise SystemExit(EXIT_OK)
    if proc.returncode != 0:
        if ssh_module.is_forward_refused(proc.stderr):
            # The key was accepted and the channel opened; the destination was
            # not permitted. That is not an authentication failure, and saying
            # so is the difference between a user debugging their key and one
            # reporting a platform mismatch.
            raise FreepodError(
                "the SSH server accepted your key but refused to forward to the "
                "database. This is not an authentication problem but a platform "
                "fault; please report it."
            )
        if proc.stderr:
            sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
    raise SystemExit(proc.returncode)


@cli.group()
def bucket() -> None:
    """Your app's object storage bucket.

    `bucket status` shows the bucket, its S3 endpoint and credentials, and how
    much of its limits it uses. The other commands work with its objects
    directly, from this machine. Mark the bucket's side of a path with a
    leading colon; `:` alone is the bucket's root:

    \b
      freepod bucket ls -l :uploads
      freepod bucket cp ./assets :public          upload a directory
      freepod bucket cp :exports/report.csv .     download one object
      freepod bucket link :exports/report.csv     a URL to share

    Your running app already has the same credentials in its environment
    (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT_URL`, and the
    bucket name).
    """


def _bucket_details(context: Context, *, usage: bool) -> Optional[dict]:
    project_file = _project_deployment(context, lacks="bucket")
    session = context.session()
    session.authenticate(interactive=False)
    with context.client(session) as api:
        user_id = api.me()["id"]
        return bucket_module.read(api, user_id, project_file.deployment_id, usage=usage)


def _open_bucket(context: Context) -> s3_module.Bucket:
    """The project deployment's bucket, with credentials fetched for this run only."""
    creds = bucket_module.credentials(_bucket_details(context, usage=False))
    return s3_module.Bucket(creds, verbose=context.verbose)


def _reporter(context: Context) -> objects_module.Reporter:
    return objects_module.Reporter(quiet=context.quiet)


@bucket.command("status")
@click.option("--show-secret", is_flag=True, help="print the secret key instead of masking it")
@click.pass_obj
def bucket_status(context: Context, show_secret: bool) -> None:
    """Show this deployment's bucket, endpoint, credentials and usage.

    The secret key is masked unless `--show-secret` is given.
    """
    details = _bucket_details(context, usage=True)
    if details is None:
        context.say("This deployment has no bucket.")
        return
    click.echo(bucket_module.render_status(details, show_secret=show_secret))


@bucket.command("ls")
@click.option("-l", "long_format", is_flag=True, help="show each object's size and last-modified time")
@click.option("-r", "recursive", is_flag=True, help="list every object under the prefix, recursively")
@click.argument("path", required=False, default=":")
@click.pass_obj
def bucket_ls(context: Context, long_format: bool, recursive: bool, path: str) -> None:
    """List a prefix of the bucket, or the root when no path is given.

    Sub-prefixes are shown with a trailing `/`. The leading colon is optional:
    the path is always the bucket's.
    """
    remote = objects_module.remote_path(path, marker_required=False)
    with _open_bucket(context) as store:
        for name, info in objects_module.list_entries(store, remote, path, recursive=recursive):
            click.echo(objects_module.format_entry(name, info, long=long_format))


def _transfer(context: Context, source: str, destination: str, *, move: bool) -> None:
    reporter = _reporter(context)
    with _open_bucket(context) as store:
        objects_module.transfer(store, source, destination, move=move, reporter=reporter)
    verb = "Moved" if move else "Copied"
    context.say(
        f"{verb} {reporter.files} file{'s' if reporter.files != 1 else ''} "
        f"({database_module.format_bytes(reporter.bytes)})."
    )


@bucket.command("cp")
@click.argument("source")
@click.argument("destination")
@click.pass_obj
def bucket_cp(context: Context, source: str, destination: str) -> None:
    """Copy files or objects between here and the bucket, or within it.

    Mark the bucket's side with a leading colon; the marked side decides the
    direction. A directory or prefix is copied recursively, with no flag:

    \b
      freepod bucket cp photo.jpg :images/       to images/photo.jpg
      freepod bucket cp photo.jpg :cover.jpg     to exactly cover.jpg
      freepod bucket cp ./site :public           a whole tree
      freepod bucket cp :public ./backup         and back
      freepod bucket cp :public :public-old      within the bucket

    Existing files and objects are overwritten. Keys that would land outside
    the destination are skipped and reported.
    """
    _transfer(context, source, destination, move=False)


@bucket.command("mv")
@click.argument("source")
@click.argument("destination")
@click.pass_obj
def bucket_mv(context: Context, source: str, destination: str) -> None:
    """Move files or objects: copy them, then delete each source.

    Takes the same paths as `cp`. A source is deleted only after its copy has
    completed; one that could not be copied is kept and reported. Within the
    bucket, nothing is downloaded.
    """
    _transfer(context, source, destination, move=True)


@bucket.command("rm")
@click.option("-r", "recursive", is_flag=True, help="delete everything under a prefix")
@click.argument("paths", nargs=-1, required=True)
@click.pass_obj
def bucket_rm(context: Context, recursive: bool, paths: tuple) -> None:
    """Delete objects, or with -r everything under a prefix.

    There is no undo: the bucket keeps no previous versions. The leading colon
    is optional; local files are never touched.
    """
    reporter = _reporter(context)
    targets = [(objects_module.remote_path(p, marker_required=False), p) for p in paths]
    with _open_bucket(context) as store:
        deleted = objects_module.remove(store, targets, recursive=recursive, reporter=reporter)
    context.say(f"Deleted {deleted} object{'s' if deleted != 1 else ''}.")


@bucket.command("cat")
@click.argument("paths", nargs=-1, required=True)
@click.pass_obj
def bucket_cat(context: Context, paths: tuple) -> None:
    """Write objects to stdout, exactly as stored.

    Several objects are written one after another, in the order given.
    """
    targets = [(objects_module.remote_path(p, marker_required=False), p) for p in paths]
    out = click.get_binary_stream("stdout")
    with _open_bucket(context) as store:
        try:
            objects_module.cat(store, targets, out)
        except BrokenPipeError:
            # The reader went away (`| head`); that is its choice, not a failure.
            sys.stdout = open(os.devnull, "w")


@bucket.command("link")
@click.option("--put", is_flag=True, help="a URL that uploads to the key, instead of downloading it")
@click.option(
    "--expires",
    default="1h",
    show_default=True,
    metavar="DURATION",
    help="how long the URL works: a number with s, m, h or d; at most 7d",
)
@click.argument("path")
@click.pass_obj
def bucket_link(context: Context, put: bool, expires: str, path: str) -> None:
    """Print a presigned URL for one object.

    Anyone holding the URL can download the object (or, with --put, upload to
    the key, as in `curl -T file URL`) until it expires, with no other
    credentials. The URL is the only output.
    """
    seconds = objects_module.parse_expiry(expires)
    remote = objects_module.remote_path(path, marker_required=False)
    with _open_bucket(context) as store:
        url = objects_module.link(store, remote, path, put=put, expires=seconds)
    click.echo(url)


@cli.group()
def key() -> None:
    """Register the SSH public keys that identify you to the platform.

    `shell`, `cp`, `db shell` and `db proxy` connect over SSH and need a
    registered key. A key belongs to your account and works for every
    deployment you own. Removing a key revokes its access.

    Registering a key also makes it the one this machine uses, so connections
    offer exactly that key.
    """


@key.command("list")
@click.pass_obj
def key_list(context: Context) -> None:
    """List the keys registered on your account.

    The key this machine uses is marked with `*`.
    """
    session = context.session()
    session.authenticate(interactive=False)
    with context.client(session) as api:
        user_id = api.me()["id"]
        registered = keys_module.list_keys(api, user_id)

    if not registered:
        context.say("No SSH keys are registered on this account.")
        context.say("Add one with `freepod key add`.")
        return

    held = keys_module.select_local_key(context.env.name, registered)
    here = keys_module.fingerprint_for_file(held) if held is not None else None
    click.echo(keys_module.render_table(registered, here))


@key.command("add")
@click.argument("path", required=False, type=click.Path(path_type=Path))
@click.option("--label", help="the name `key list` shows (default: the key's comment)")
@click.pass_obj
def key_add(context: Context, path: Optional[Path], label: Optional[str]) -> None:
    """Register a public key, generating one if no PATH is given.

    With no PATH, generates an Ed25519 key in freepod's configuration directory
    (not `~/.ssh`) and registers it. With a PATH, registers that public key
    file. Either way, the key becomes the one this machine uses.

    Naming a key that is already registered makes it this machine's key
    without registering it again.
    """
    env_name = context.env.name
    session = context.session()
    session.authenticate(interactive=False)

    with context.client(session) as api:
        user_id = api.me()["id"]
        registered = keys_module.list_keys(api, user_id)

        if path is None:
            generated = keys_module.generated_key_path()
            public_path = Path(str(generated) + ".pub")
            existing = keys_module.fingerprint_for_file(public_path)
            if existing and any(k.get("fingerprint") == existing for k in registered):
                context.say("This machine already holds a registered key.")
                click.echo(existing)
                keys_module.remember(env_name, existing, public_path)
                return
            if public_path.exists():
                material = keys_module.read_public_key(public_path)
            else:
                material = keys_module.generate_keypair(generated)
                context.say(f"Generated a new key at {generated}")
            source = public_path
        else:
            material = keys_module.read_public_key(path)
            source = path

        try:
            stored = keys_module.add_key(api, user_id, material, label)
        except keys_module.DuplicateKey as duplicate:
            fingerprint = keys_module.fingerprint_for_line(material)
            keys_module.remember(env_name, fingerprint, source)
            context.say(str(duplicate))
            click.echo(fingerprint)
            context.say(
                f"This machine now uses it{env_suffix(env_name)} for shell, cp, "
                "db shell, and db proxy."
            )
            return

    keys_module.remember(env_name, stored["fingerprint"], source)
    context.say(f"Registered {stored['label']!r}{env_suffix(env_name)}.")
    click.echo(stored["fingerprint"])
    context.say("This machine now uses it for shell, cp, db shell, and db proxy.")


@key.command("rm")
@click.argument("fingerprint")
@click.pass_obj
def key_rm(context: Context, fingerprint: str) -> None:
    """Revoke a key by the fingerprint `freepod key list` shows.

    Works for keys this machine does not hold, such as one on a lost laptop.
    """
    session = context.session()
    session.authenticate(interactive=False)
    with context.client(session) as api:
        user_id = api.me()["id"]
        keys_module.remove_key(api, user_id, fingerprint)

    recorded = keys_module.local_key(context.env.name)
    if recorded and recorded["fingerprint"] == fingerprint:
        keys_module.forget(context.env.name)
        context.say("This machine no longer holds a registered key.")
    context.say(f"Removed {fingerprint}.")


@cli.group()
def skill() -> None:
    """Install the deployment instructions for your coding agents.

    The skill is a SKILL.md file that tells a coding agent what an app needs to
    run on Freepod and how to deploy it with this CLI. It ships with the CLI,
    so it always matches the installed version.
    """


@skill.command("install")
@click.option(
    "--agent",
    "names",
    metavar="NAME",
    multiple=True,
    help="install for this agent whether or not it is detected; repeatable",
)
@click.option("--all", "everything", is_flag=True, help="install for every supported agent")
@click.option(
    "--project",
    is_flag=True,
    help="install into this directory's per-agent skill folders rather than the home directory",
)
@click.option(
    "--dest",
    type=click.Path(path_type=Path),
    help=f"write {skill_module.SKILL_FILE} to this exact path instead, for an agent not listed",
)
@click.pass_obj
def skill_install(
    context: Context,
    names: tuple,
    everything: bool,
    project: bool,
    dest: Optional[Path],
) -> None:
    """Install the skill where your coding agents will find it.

    With no options, installs for every supported agent whose configuration
    directory exists on this machine. `--agent` and `--all` choose agents
    explicitly; `--dest` writes the file to an exact path.

    Existing copies are replaced, so upgrading freepod and re-running this
    updates the skill. The installed paths are printed to stdout, one per line.
    \f
    Replaced without asking because the file is generated and the path belongs
    to this client: a newer client's skill has to supersede an older one for
    `pip install --upgrade` to mean anything.
    """
    if dest is not None:
        if names or everything or project:
            raise UsageError("--dest names the exact path, so it takes no other selector.")
        outcome = skill_module.write(dest)
        context.say(
            f"{'Already current' if outcome == 'current' else 'Installed'}: "
            f"{skill_module.SKILL_NAME}"
        )
        click.echo(str(dest))
        return

    if names and everything:
        raise UsageError("--agent selects specific agents and --all selects every one.")

    chosen = skill_module.select(names, everything)
    if not chosen:
        raise UsageError(
            "no supported coding agent found on this machine — none of "
            f"{', '.join(skill_module.agent_keys())} has a configuration directory.\n"
            "  Install for one anyway with `--agent NAME`, for all of them with "
            "`--all`, or write the file wherever you need it with `--dest PATH`."
        )

    results = skill_module.install(chosen, project=project)

    # The whole report to stderr first, then the paths to stdout, rather than
    # alternating between the two. Both streams reach a terminal by default,
    # and interleaved they read as every line printed twice.
    width = max(len(agent.label) for agent, _, _ in results)
    for agent, target, outcome in results:
        note = " (already current)" if outcome == "current" else ""
        context.say(f"  {agent.label.ljust(width)}  {target}{note}")

    installed = [agent.label for agent, _, outcome in results if outcome != "current"]
    scope = "this project" if project else "this machine"
    if installed:
        context.say(f"Installed '{skill_module.SKILL_NAME}' for {_join(installed)} on {scope}.")
    else:
        context.say(f"'{skill_module.SKILL_NAME}' was already current for every agent.")

    if not names and not everything:
        missing = [
            agent.label for agent in skill_module.agents() if agent not in set(chosen)
        ]
        if missing:
            context.say(
                f"Not detected: {_join(missing)}. Use --agent or --all to install anyway."
            )

    context.say("Agents pick the skill up on their next session.")

    for _agent, target, _outcome in results:
        click.echo(str(target))


@skill.command("show")
def skill_show() -> None:
    """Print the packaged skill to stdout.

    Use it for an agent `install` does not support, or to read the skill
    before installing it.
    """
    click.echo(skill_module.read_skill(), nl=False)


def main(argv: Optional[list] = None) -> int:
    """Run the CLI and map every failure onto its exit code.

    Section 11 completes the exit-code table; the rows reachable from the
    commands wired up so far are handled here.
    """
    try:
        cli.main(args=argv, standalone_mode=False)
        return EXIT_OK
    except click.exceptions.Exit as exc:
        return int(exc.exit_code)
    except click.ClickException as exc:
        exc.show()
        return int(exc.exit_code)
    except click.Abort:
        log("\nInterrupted.")
        return 130
    except UsageError as exc:
        log(f"error: {exc}")
        return exc.exit_code
    except FreepodError as exc:
        log(f"\nerror: {exc}")
        return exc.exit_code
    except KeyboardInterrupt:
        log("\nInterrupted.")
        return 130
    except Exception as exc:  # noqa: BLE001 - the "unexpected error" row
        log(f"\nunexpected error: {exc.__class__.__name__}: {exc}")
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


@cli.command(name="log")
@click.option("-f", "--follow", is_flag=True, help="keep the stream open and print lines as they arrive")
@click.option(
    "-n", "--tail", type=int, metavar="LINES",
    help="how many recent lines to show first (default: set by the platform)",
)
@click.option(
    "-r", "--release", type=int, metavar="NUMBER",
    help="pin to one release by its number, including one that failed and was rolled back",
)
@click.option(
    "-t", "--timestamps", is_flag=True,
    help="prefix each line with the time the platform recorded for it",
)
@click.pass_obj
def log_command(
    context: Context,
    follow: bool,
    tail: Optional[int],
    release: Optional[int],
    timestamps: bool,
) -> None:
    """Print this project's application output.

    Application output goes to stdout and freepod's own messages to stderr, so
    `freepod log > app.log` captures only your app's output.

    With `-f` the stream stays open, including across redeploys.
    """
    session = context.session()
    session.authenticate(interactive=False)
    with context.client(session) as api:
        try:
            code = logs_module.run(
                api,
                context.env.name,
                root=Path.cwd(),
                follow=follow,
                tail=tail,
                release=release,
                timestamps=timestamps,
                say=context.say,
            )
        except KeyboardInterrupt:
            # Interrupting a follow is how a follow ends. Nothing happened to
            # the deployment and nothing should suggest otherwise.
            context.say("")
            raise SystemExit(EXIT_OK)
    raise SystemExit(code)


@cli.command()
@click.argument("source")
@click.argument("destination")
@click.pass_obj
def cp(context: Context, source: str, destination: str) -> None:
    """Copy a file or directory between here and this deployment.

    Mark the deployment's side with a leading colon; the other side is local,
    and which one is marked decides the direction:

    \b
      freepod cp report.csv :/app/report.csv     copy in
      freepod cp :/app/out.log ./out.log         copy out
      freepod cp ./assets :/app/assets           a whole tree, no flag needed

    A relative remote path means what it means in `freepod shell`. Directories
    carry their structure and their files' modes; owners and timestamps are
    not preserved. Directories are always copied recursively.
    Nothing has to be installed in your image for this to work.
    """
    project_file = _project_deployment(context)
    deployment_name = project_file.deployment_name

    # Every refusal that does not need a connection happens before we spend one.
    local, remote, upload = copy_module.direction(source, destination, deployment_name)
    copy_module.check_local(local, upload=upload)
    ssh_module.require_sftp()

    deployment, _database, host, port, key_path, known_hosts = _connection_setup(
        context, project_file
    )
    args = ssh_module.build_sftp_args(
        user=_ssh_username(deployment),
        host=host,
        port=port,
        key_path=key_path,
        known_hosts=known_hosts,
    )
    code = copy_module.run(args, copy_module.batch(local, remote, upload=upload))
    if code == EXIT_OK:
        context.say(f"Copied {source} to {destination}.")
    # Otherwise sftp has already said which path it could not read, on the
    # user's own stderr, and nothing here claims the copy finished.
    raise SystemExit(code)


@cli.command(
    # The first word of COMMAND ends this client's own options, so everything
    # after it -- `-la`, `-t`, `--help` -- belongs to the remote command and is
    # passed through untouched. It is where `ssh` draws the same line, and
    # without it a command's flags would be read as this client's.
    context_settings={"allow_interspersed_args": False}
)
@click.option(
    "--tty",
    "-t",
    "force_tty",
    is_flag=True,
    help="allocate a terminal for COMMAND — for a full-screen program such as "
    "top or an editor, which needs one to draw",
)
@click.argument("command", nargs=-1, type=click.UNPROCESSED)
@click.pass_obj
def shell(context: Context, force_tty: bool, command: tuple) -> None:
    """Open a shell in the app's container, or run COMMAND in it.

    With no COMMAND the session runs on your own terminal and stays until you
    leave it. This is the command for a deployment that is up but misbehaving —
    the container is reachable even when the app inside it is not.

    With a COMMAND it runs there and exits, the way `ssh host COMMAND` does:
    the words are joined and interpreted by the container's own shell, so
    quote a pipeline as one argument to keep it whole. Its input and output are
    this terminal's, so `freepod shell cat app.log > local.log` works.

    Either way the exit code is the remote side's, with one ambiguity `ssh`
    itself has: 255 is also what `ssh` reports for its own failures.
    """
    project_file = _project_deployment(context)
    args = _connection_args(
        context,
        project_file,
        command=list(command) or None,
        # A remote command gets no terminal unless it is asked for: a pty
        # rewrites its output — line endings translated, stderr folded into
        # stdout, input echoed — which is corruption for anything redirected
        # to a file or a pipe. An interactive session is the case that needs
        # one, and it is the case with no command.
        tty=force_tty or not command,
    )
    raise SystemExit(ssh_module.run_interactive(args))
