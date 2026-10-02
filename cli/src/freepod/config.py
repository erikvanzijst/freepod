"""Environments and on-disk locations.

The client targets one of exactly two named environments. There is no
caller-supplied base URL: an access token is bound by its audience to one
environment, so an arbitrary address would need the issuer and client id to
travel with it — which means a discovery endpoint the platform does not
publish. See design D2.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from . import UsageError, __version__
from .project import DEFAULT_ENV, PROJECT_FILE

ISSUER = "https://keycloak.freepod.eu/realms/freepod"

#: Selects the environment when no explicit choice is made.
ENV_VAR = "FREEPOD_ENV"

#: The stable slug of the product that runs tenant-supplied images. Resolved by
#: slug rather than by display name, which is presentation and can change.
CUSTOM_PRODUCT_SLUG = "custom"

SCOPES = "openid email profile offline_access"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

USER_AGENT = f"freepod/{__version__} (+https://freepod.eu)"

#: How long a single HTTP request may take. Long waits (build, rollout) are
#: bounded separately by their own deadlines, not by this.
DEFAULT_HTTP_TIMEOUT = 30

#: Read timeout for a followed log stream.
#:
#: Deliberately not DEFAULT_HTTP_TIMEOUT. That bounds how long a request may
#: take to *answer*, and a followed stream is not trying to finish; httpx
#: applies a read timeout per read, so 30s would disconnect any application
#: that stayed quiet for half a minute -- which is most of them, most of the
#: time, and is not a fault.
#:
#: What this bounds instead is the platform's silence. The endpoint emits a
#: keepalive comment on a fixed interval whether or not the application says
#: anything, so keepalives stopping is the disconnection signal and this must
#: sit comfortably above their interval (15s at the time of writing). Raising
#: the platform's keepalive above this value would make a healthy stream look
#: dead, so the two move together.
LOG_STREAM_READ_TIMEOUT = 120

#: Reconnection attempts for an interrupted followed stream, and the first
#: backoff interval, which doubles. Bounded because a stream that cannot be
#: re-established is an interruption to report, not something to retry forever.
LOG_RECONNECT_ATTEMPTS = 5
LOG_RECONNECT_BACKOFF_SECONDS = 1.0

# Per-operation wait defaults. `--timeout` is a single global override that
# applies to whichever wait is active; unset, each operation uses its own
# default. Only LOGIN_WAIT_SECONDS is consumed so far — the other two belong to
# the build and rollout waits.
LOGIN_WAIT_SECONDS = 300
BUILD_WAIT_SECONDS = 1800
ROLLOUT_WAIT_SECONDS = 600


def wait_seconds(override: Optional[int], default: int) -> int:
    """Resolve a bounded wait: the global `--timeout` if given, else the
    operation's own default."""
    if override is None:
        return default
    if override <= 0:
        raise UsageError("--timeout must be a positive number of seconds")
    return override


class Environment:
    """One named Freepod instance and the OAuth2 client that reaches it.

    Both clients are public: PKCE proves client identity and no secret exists.
    """

    def __init__(self, name: str, client_id: str, api_base: str, issuer: str = ISSUER):
        self.name = name
        self.client_id = client_id
        self.api_base = api_base.rstrip("/")
        self.issuer = issuer

    @property
    def authorization_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/auth"

    @property
    def device_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/auth/device"

    @property
    def token_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/token"

    @property
    def requires_group(self) -> Optional[str]:
        """The Keycloak group this environment gates access on, if any.

        `tf/app/main.tf` sets `allowed_groups` to `["freepod-dev"]` on the dev
        workspace and to `[]` on prod. A non-member holding a perfectly valid
        token gets a bare 401 on every request, so the 401 message has to name
        this to be actionable.
        """
        return "freepod-dev" if self.name == "dev" else None

    def url(self, path: str) -> str:
        return f"{self.api_base}{path}"

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<Environment {self.name} api={self.api_base}>"


ENVIRONMENTS: Dict[str, Environment] = {
    "prod": Environment("prod", "freepod-cli-prod", "https://freepod.eu"),
    "dev": Environment("dev", "freepod-cli-dev", "https://dev.freepod.eu"),
}


def environment_names() -> str:
    """The accepted values, for use in a usage error."""
    return ", ".join(sorted(ENVIRONMENTS))


def env_suffix(name: str, preposition: str = "on") -> str:
    """` on 'dev'` for a non-default environment, nothing for the default one.

    The default environment is the only one end users have, so messages name an
    environment only when another one is in use.
    """
    return "" if name == DEFAULT_ENV else f" {preposition} '{name}'"


def login_command(name: str) -> str:
    """The `freepod login` invocation that authenticates against `name`."""
    return "freepod login" if name == DEFAULT_ENV else f"freepod --env {name} login"


def resolve_environment(
    selected: Optional[str] = None, *, project_env: Optional[str] = None
) -> Environment:
    """Pick the environment: explicit selection, then the project file, then
    `FREEPOD_ENV`, then prod.

    The project file outranks the environment variable because it is the most
    specific signal of where this project lives: a deployment id minted on dev
    is meaningless on prod, so a global default must not pull a command away
    from the environment its project was created on. The default flips relative
    to the demo client, which targeted dev because it was a developer's tool.
    A released client defaults to production.
    """
    name = selected or project_env or os.environ.get(ENV_VAR) or DEFAULT_ENV
    name = name.strip()
    try:
        return ENVIRONMENTS[name]
    except KeyError:
        if selected:
            source = "--env"
        elif project_env:
            source = PROJECT_FILE
        else:
            source = ENV_VAR
        raise UsageError(
            f"unknown environment {name!r} for {source} — "
            f"accepted values are {environment_names()}"
        ) from None


def config_dir() -> Path:
    """Resolve `${XDG_CONFIG_HOME:-~/.config}/freepod` without touching disk."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "freepod"


def ensure_config_dir() -> Path:
    """The config directory, created owner-only.

    The mode is what keeps a cached credential private, so it is asserted on a
    directory that already existed too: `mkdir` applies its mode only when it
    creates the directory, and an earlier loose creation would otherwise be
    inherited forever.
    """
    directory = config_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:  # pragma: no cover - unusual filesystems
        pass
    return directory


def token_cache_path() -> Path:
    """Where the credential cache lives. Reading it must not create anything."""
    return config_dir() / "tokens.json"


def cache_path_hint() -> str:
    """The cache path as a string, for messages. Creates nothing."""
    return str(token_cache_path())
