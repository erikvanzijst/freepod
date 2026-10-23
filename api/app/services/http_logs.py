"""Reading a deployment's HTTP access log from the log store.

Traefik writes one JSON line per request (tf/deps/system/helm/traefik), and the
collector labels each with the `router` that matched it (tf/deps/loki). A line
carries no deployment, so a deployment's requests are selected by the names of
the routers it owns.

**How a router name maps to a deployment.** Traefik's Kubernetes Ingress
provider names a router `Normalize(namespace-ingress-host+path)@kubernetes`,
where `Normalize` turns each run of non-alphanumerics into one `-`; a rule that
would collide with another in the same Ingress gets a hash appended. Catalog
charts name every Ingress `<release>-...`, and the release is
`deployment.name`. So every router a deployment owns -- across Ingresses, hosts
and paths -- starts with `<namespace>-<name>-`, and nothing else's does:

* both values are platform-generated `[a-z0-9-]`; the host and path, the only
  parts a tenant influences, come after them and cannot forge the prefix;
* namespaces and names end in random suffixes, so another deployment's prefix
  is out of reach, and the `-` after the name keeps `...-ab12cd` from matching
  `...-ab12cd9` in a namespace two deployments share.

If Traefik ever changed its naming, this selects nothing rather than someone
else's requests. The Traefik chart version carries a note to check.

The selector is built here from an authorized row, as in ``deployment_logs.py``,
and for the same reason: Loki has no tenancy of its own.
"""

from __future__ import annotations

import json
import re

from sqlmodel import Session

from app.services import deployment_logs
from app.services.deployment_logs import LogTarget
from app.services.log_stream import LogSource
from app.services.loki import LogEntry

TRAEFIK_NAMESPACE = "kube-system"
TRAEFIK_CONTAINER = "traefik"
ROUTER_LABEL = "router"

EVENT_REQUEST = "request"


def resolve_target(session: Session, *, deployment_id, user_id: int | None) -> LogTarget:
    """Authorize exactly as the pod log does. Requests have no release to pin."""
    return deployment_logs.resolve_target(session, deployment_id=deployment_id, user_id=user_id)


def router_pattern(target: LogTarget) -> str:
    """The deployment's routers, as an RE2 pattern Loki anchors at both ends.

    `@kubernetescrd` admits a chart that renders an IngressRoute, which Traefik
    names `<namespace>-<name>-<hash>`.
    """
    prefix = re.escape(f"{target.namespace}-{target.name}-")
    return f"{prefix}.+@kubernetes(crd)?"


def build_selector(target: LogTarget) -> str:
    return (
        f"{{namespace={json.dumps(TRAEFIK_NAMESPACE)}, "
        f"container={json.dumps(TRAEFIK_CONTAINER)}, "
        f"{ROUTER_LABEL}=~{json.dumps(router_pattern(target))}}}"
    )


def render(entry: LogEntry) -> dict | None:
    """One request record, or None for a line that is not one.

    Built field by field from named keys, so a field Traefik starts writing is
    not passed on to tenants until it is added here. Skips lines from before
    the access log was JSON, and anything else that does not parse.
    """
    try:
        line = json.loads(entry.line)
    except ValueError:
        return None
    if not isinstance(line, dict):
        return None
    status = line.get("DownstreamStatus")
    size = line.get("DownstreamContentSize")
    duration_ns = line.get("Duration")
    if not (
        isinstance(line.get("RequestMethod"), str)
        and isinstance(line.get("StartUTC"), str)
        and _is_int(status)
        and _is_int(size)
        and _is_int(duration_ns)
    ):
        return None
    return {
        # A string, like the pod log's: see `deployment_logs.render`.
        "ts": entry.timestamp_ns,
        "time": line["StartUTC"],
        "host": line.get("RequestHost"),
        "remote_addr": line.get("ClientHost"),
        "method": line["RequestMethod"],
        "path": line.get("RequestPath"),
        "protocol": line.get("RequestProtocol"),
        "status": status,
        "bytes": size,
        "duration_ms": round(duration_ns / 1_000_000, 3),
        # Traefik omits a header the request did not carry.
        "referer": line.get("request_Referer"),
        "user_agent": line.get("request_User-Agent"),
    }


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def log_source(target: LogTarget) -> LogSource:
    return LogSource(
        selector=build_selector(target),
        event=EVENT_REQUEST,
        render=render,
        description=f"http log of deployment_id={target.deployment_id}",
    )
