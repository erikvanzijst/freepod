"""Schema-driven prompting, and hostname normalization.

Walks the product template's `values_schema_json`, prompts for each `required`
property, and validates answers locally before they reach the API. Shared by
`init` and `deploy`, because `init --force` discards the whole project file and
so a missing value at deploy time must be answered by asking rather than by
sending the user back to `init`. See design D5.

The loop is driven by the schema rather than by a hardcoded field list, so a
newly required property appears without a client release. Today `required` is
exactly `["hostname"]`.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

import click

from . import FreepodError

#: The schema title that marks the hostname property, matched
#: case-insensitively — the same rule the platform uses to derive and claim a
#: deployment's hostname.
HOSTNAME_TITLE = "hostname"

#: `GET /api/hostnames/{fqdn}` answers 200 with `{fqdn, usable, reason}`. The
#: reasons are machine codes; these are their user-facing readings.
HOSTNAME_REASONS = {
    "invalid": "that is not a valid hostname",
    "reserved": "that name is reserved by the platform",
    "claimed": "that name is beneath a domain name another account holds",
    "in_use": "that name is already taken by another deployment",
    "not_resolving": (
        "that name does not have a CNAME pointing at the platform yet — "
        "custom domains need the DNS record in place first"
    ),
}


class ValueError_(FreepodError):
    """A required value is missing or unusable and cannot be resolved."""


def describe_reason(reason: Optional[str]) -> str:
    if not reason:
        return "the platform reported it as unusable"
    return HOSTNAME_REASONS.get(reason, f"the platform reported '{reason}'")


# --------------------------------------------------------------------------
# Local constraint checking
# --------------------------------------------------------------------------


def check_constraints(name: str, value: str, spec: Dict[str, Any]) -> Optional[str]:
    """Return a human explanation of the first violated constraint, or None.

    Only the constraints that can be evaluated without the platform are
    checked. Everything else is left to the API, which is the authority.
    """
    enum = spec.get("enum")
    if isinstance(enum, list) and enum:
        if value not in enum:
            allowed = ", ".join(str(option) for option in enum)
            return f"{name} must be one of: {allowed}"
        return None

    minimum = spec.get("minLength")
    if isinstance(minimum, int) and len(value) < minimum:
        return f"{name} must be at least {minimum} character{'' if minimum == 1 else 's'}"

    maximum = spec.get("maxLength")
    if isinstance(maximum, int) and len(value) > maximum:
        return f"{name} must be at most {maximum} characters (that was {len(value)})"

    pattern = spec.get("pattern")
    if isinstance(pattern, str) and pattern:
        try:
            matches = re.search(pattern, value) is not None
        except re.error:
            # An un-compilable pattern is the platform's problem, not the
            # user's; let the API judge rather than blocking on it here.
            return None
        if not matches:
            return f"{name} must match the pattern {pattern}"

    return None


# --------------------------------------------------------------------------
# Hostname handling
# --------------------------------------------------------------------------


def is_hostname_property(spec: Dict[str, Any]) -> bool:
    title = spec.get("title")
    return isinstance(title, str) and title.strip().lower() == HOSTNAME_TITLE


def normalize_hostname(value: str, account_fqdn: Optional[str]) -> str:
    """Lowercase, and complete a bare label beneath the account's domain name.

    An application is addressed at `<app>.<subdomain>.<domain>`, so a bare label
    is completed with the account's own name rather than with a platform domain
    chosen from a list -- there is no list, and no other name the account may
    deploy beneath.

    A value containing a dot is taken as already fully qualified: it may be a
    custom domain, which the platform supports via CNAME.
    """
    candidate = value.strip().lower().rstrip(".")
    if not candidate:
        return candidate
    if "." not in candidate and account_fqdn:
        return f"{candidate}.{account_fqdn}"
    return candidate


# --------------------------------------------------------------------------
# The prompting loop
# --------------------------------------------------------------------------


class ValueCollector:
    """Collects the values a template's schema requires.

    `check_hostname` is injected rather than reached for directly, so the
    routine stays testable without a network and so `deploy` can skip the
    check when the hostname has not changed (design D14).
    """

    def __init__(
        self,
        schema: Dict[str, Any],
        *,
        account_fqdn: Optional[str] = None,
        check_hostname: Optional[Callable[[str], Dict[str, Any]]] = None,
        interactive: bool = True,
        echo: Callable[[str], None] = lambda message: click.echo(message, err=True),
        ask: Optional[Callable[..., str]] = None,
    ):
        self.schema = schema or {}
        self.account_fqdn = account_fqdn
        self.check_hostname = check_hostname
        self.interactive = interactive
        self.echo = echo
        self._ask = ask or (
            lambda text, default=None: click.prompt(text, default=default, err=True)
        )

    # -- schema access ----------------------------------------------------

    @property
    def properties(self) -> Dict[str, Any]:
        properties = self.schema.get("properties")
        return properties if isinstance(properties, dict) else {}

    @property
    def required(self) -> List[str]:
        required = self.schema.get("required")
        if not isinstance(required, list):
            return []
        return [name for name in required if isinstance(name, str)]

    def spec_for(self, name: str) -> Dict[str, Any]:
        spec = self.properties.get(name)
        return spec if isinstance(spec, dict) else {}

    # -- collection -------------------------------------------------------

    def collect(
        self,
        existing: Optional[Dict[str, Any]] = None,
        *,
        only_missing: bool = False,
    ) -> Dict[str, Any]:
        """Return the required values, prompting for whatever is not settled.

        With `only_missing`, values already present are accepted untouched —
        the mode `deploy` uses, where re-asking a settled question would be
        noise. Properties that are not required are never prompted for and
        never written, so the file does not accumulate defaults the user did
        not choose.
        """
        collected: Dict[str, Any] = dict(existing or {})
        result: Dict[str, Any] = {}

        for name in self.required:
            spec = self.spec_for(name)
            present = collected.get(name)
            has_value = isinstance(present, str) and present != ""

            if has_value and only_missing:
                result[name] = present
                continue

            result[name] = self._resolve(name, spec, present if has_value else None)

        # Carry through any non-required value the user already had, so a
        # hand-edited optional setting is not silently dropped on rewrite.
        for name, value in collected.items():
            result.setdefault(name, value)

        return result

    def _resolve(self, name: str, spec: Dict[str, Any], current: Optional[str]) -> str:
        hostname = is_hostname_property(spec)

        if current is not None and not self.interactive:
            return self._validate_noninteractive(name, spec, current, hostname)

        if not self.interactive:
            raise ValueError_(
                f"'{name}' is required by the product template and is not set, and "
                f"there is no terminal to ask on. Set it in .freepod.json and re-run."
            )

        self._introduce(name, spec)
        return self._prompt_loop(name, spec, current, hostname)

    def _introduce(self, name: str, spec: Dict[str, Any]) -> None:
        description = spec.get("description")
        if isinstance(description, str) and description.strip():
            self.echo(f"{name}: {description.strip()}")

    def _prompt_loop(
        self, name: str, spec: Dict[str, Any], current: Optional[str], hostname: bool
    ) -> str:
        while True:
            answer = self._ask(f"  {name}", default=current) if current else self._ask(f"  {name}")
            answer = (answer or "").strip()

            if hostname:
                answer = normalize_hostname(answer, self.account_fqdn)
                if answer and answer != (current or "") and "." in answer:
                    self.echo(f"  → {answer}")

            problem = check_constraints(name, answer, spec)
            if problem:
                self.echo(f"  {problem}. Try again.")
                current = None
                continue

            if hostname and self.check_hostname is not None:
                verdict = self.check_hostname(answer)
                if not verdict.get("usable", False):
                    self.echo(f"  {answer}: {describe_reason(verdict.get('reason'))}. Try again.")
                    current = None
                    continue

            return answer

    def _validate_noninteractive(
        self, name: str, spec: Dict[str, Any], value: str, hostname: bool
    ) -> str:
        if hostname:
            value = normalize_hostname(value, self.account_fqdn)
        problem = check_constraints(name, value, spec)
        if problem:
            raise ValueError_(f"{problem} (currently {value!r})")
        return value


def missing_required(schema: Dict[str, Any], values: Dict[str, Any]) -> List[str]:
    """Required property names absent or empty in `values`."""
    required = schema.get("required")
    if not isinstance(required, list):
        return []
    missing = []
    for name in required:
        if not isinstance(name, str):
            continue
        value = values.get(name)
        if not isinstance(value, str) or value == "":
            missing.append(name)
    return missing
