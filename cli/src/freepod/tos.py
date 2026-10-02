"""Terms of Service acceptance.

The platform refuses to create a deployment for an account that has never
accepted the terms: `POST /api/users/{id}/deployments` answers **400** with the
detail `Terms of Service must be accepted before deploying`. That refusal
arrives at the very end of a deploy — after the archive has been packed,
uploaded, and built — so the client settles it in preflight instead, where the
answer costs one question rather than a spent build.

Two things here are deliberately separate, because they need different
knowledge:

- **The gate** is `tos_accepted_version is not None`. The platform requires
  *some* acceptance, not the current one, so checking it needs no idea which
  version is current.
- **Recording** an acceptance requires submitting the exact current version, or
  the platform answers 409. The client learns that version from
  `current_version` on the same document and never carries its own copy: it is a
  release constant of the API image, the client ships on its own cadence, and a
  stale copy would 409 every user of that client until they upgraded — locking
  them out of deploying entirely. Same reasoning as design D12.

Only a *create* is gated; an update of an existing deployment is not. The client
therefore asks only when it is about to create one, rather than nagging on every
deploy.
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

import click

from . import FreepodError
from .api import ApiClient
from .config import Environment, login_command

ACCEPTANCE_PATH = "/api/me/tos-acceptance"

#: The detail the platform's create refuses with when the terms are unaccepted.
#: Matched as a backstop for the race where acceptance is withdrawn between
#: preflight and the create request.
DEPLOY_REFUSAL = "Terms of Service must be accepted before deploying"

#: The documents, in the order the web UI names them. Slugs resolve under the
#: platform's own origin (`/legal/{slug}`), which is where the UI links too.
DOCUMENTS: Tuple[Tuple[str, str], ...] = (
    ("Terms of Service", "terms"),
    ("Acceptable Use Policy", "aup"),
    ("Privacy Policy", "privacy"),
)

#: Verbatim from the web UI's deploy dialog (`ui/src/components/TosAgreement.tsx`).
#: The wording is the consent record, so it is copied rather than paraphrased:
#: two documents are actively agreed to and the third is acknowledged, and that
#: distinction is not the client's to restate.
AGREEMENT = (
    "I agree to the Freepod Terms of Service and Acceptable Use Policy, and "
    "acknowledge the Privacy Policy."
)


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _ask(question: str) -> bool:
    return click.confirm(question, default=False, err=True)


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def read(api: ApiClient) -> Dict[str, Any]:
    """`GET /api/me/tos-acceptance` — always 200, even when nothing is accepted.

    The platform models "not accepted" as a document with null fields rather
    than a 404, so an unaccepted account is a normal state to read, not an
    error to handle.
    """
    body = api.get_json(ACCEPTANCE_PATH)
    if not isinstance(body, dict):
        raise FreepodError(f"unexpected {ACCEPTANCE_PATH} response: {body!r}")
    return body


def accepted(record: Dict[str, Any]) -> bool:
    """Whether this account has accepted any version of the terms."""
    return bool(record.get("version"))


def current_version(record: Dict[str, Any]) -> Optional[str]:
    """The version the platform currently requires, if it says.

    `None` means the API predates exposing it. The client cannot then record an
    acceptance — submitting a guessed version is exactly the 409 this field
    exists to prevent — so it points at the web UI instead.
    """
    version = record.get("current_version")
    return version if isinstance(version, str) and version else None


def document_urls(env: Environment) -> List[Tuple[str, str]]:
    return [(title, f"{env.api_base}/legal/{slug}") for title, slug in DOCUMENTS]


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


def record_acceptance(api: ApiClient, version: str) -> Dict[str, Any]:
    """`POST /api/me/tos-acceptance`. Idempotent for the current version."""
    response = api.post(ACCEPTANCE_PATH, json={"version": version})
    if response.status_code == 409:
        raise FreepodError(
            f"the platform refused version {version!r}: the terms changed between "
            f"reading them and accepting them. Re-run and review the current terms."
        )
    if not response.is_success:
        raise FreepodError(
            f"could not record the acceptance: HTTP {response.status_code} "
            f"{response.text.strip()[:300]}"
        )
    return response.json()


def present(env: Environment, echo: Callable[[str], None]) -> None:
    """Show what is being agreed to, with somewhere to read it.

    Links rather than the text itself: a terminal is a poor reader for a legal
    document, and the web UI links rather than inlining for the same reason.
    """
    echo("")
    echo("Before your first deployment, Freepod needs you to accept its terms.")
    width = max(len(title) for title, _ in DOCUMENTS)
    for title, url in document_urls(env):
        echo(f"  {title.ljust(width)}  {url}")
    echo("")


# --------------------------------------------------------------------------
# The two entry points
# --------------------------------------------------------------------------


#: Why settling ended the way it did. These are kept distinct because they are
#: different facts with different remedies, and collapsing them to a bool
#: reports "you declined" to someone who agreed — blaming the user for a gap in
#: the platform they are talking to.
ACCEPTED = "accepted"
DECLINED = "declined"
NO_TERMINAL = "no-terminal"
VERSION_UNKNOWN = "version-unknown"


def settle(
    api: ApiClient,
    *,
    record: Optional[Dict[str, Any]] = None,
    interactive: bool = True,
    echo: Callable[[str], None] = _log,
    ask: Callable[[str], bool] = _ask,
) -> str:
    """Offer the terms and record acceptance. Returns one of the outcomes above.

    Never raises for a decline — refusing is a legitimate answer, and it is the
    caller that knows whether the answer is fatal.
    """
    record = read(api) if record is None else record
    if accepted(record):
        return ACCEPTED
    if not interactive:
        return NO_TERMINAL

    version = current_version(record)
    if version is None:
        # Offering an agreement whose version we would then have to guess is
        # precisely the 409 this indirection exists to prevent, so nothing is
        # shown and nothing is asked.
        return VERSION_UNKNOWN

    present(api.env, echo)
    if not ask(AGREEMENT):
        return DECLINED

    record_acceptance(api, version)
    echo(f"Accepted version {version}. This is recorded once, not per deployment.")
    return ACCEPTED


def explain(status: str, env: Environment) -> str:
    """Why the deploy cannot proceed, and what would fix it."""
    if status == VERSION_UNKNOWN:
        return (
            f"this platform does not report which version of its terms is current, "
            f"so they cannot be accepted from the command line.\n"
            f"  Accept them at {env.api_base} and re-run. Nothing has been built "
            f"or deployed."
        )
    if status == NO_TERMINAL:
        return (
            f"this account has not accepted the Freepod terms, and there is no "
            f"terminal to ask on.\n"
            f"  Run `{login_command(env.name)}` from a terminal, or accept "
            f"them at {env.api_base}, then re-run."
        )
    return (
        "the terms were not accepted, so no deployment can be created. Nothing "
        "has been built or deployed."
    )


def require(
    api: ApiClient,
    *,
    interactive: bool = True,
    echo: Callable[[str], None] = _log,
    ask: Callable[[str], bool] = _ask,
) -> None:
    """Settle the terms, or refuse the deploy before anything is spent."""
    status = settle(api, interactive=interactive, echo=echo, ask=ask)
    if status == ACCEPTED:
        return
    raise FreepodError(explain(status, api.env))
