"""The HTTP access log's selector and request record.

Router names are as Traefik v3.7's Kubernetes Ingress provider writes them:
`Normalize(namespace-ingress-host+path)@kubernetes`. Loki anchors label regexes
at both ends, so `re.fullmatch` is the matching rule.
"""

from __future__ import annotations

import json
import re

import pytest

from app.services import http_logs
from app.services.deployment_logs import LogTarget
from app.services.loki import LogEntry


NS = "app-studio-erik-van-z-h715fg8ng"
TARGET = LogTarget(deployment_id="d", namespace=NS, name="app-studio-ic8szp")
TS = "1787066060123456789"

OWN = [
    # The default host, at `/`.
    f"{NS}-app-studio-ic8szp-ingress-studio-prutser-freepod-app@kubernetes",
    # A path the chart routes through its own rule.
    f"{NS}-app-studio-ic8szp-ingress-studio-prutser-freepod-app-appstudio@kubernetes",
    # A second hostname on a second Ingress.
    f"{NS}-app-studio-ic8szp-preview-preview-studio-prutser-freepod-app@kubernetes",
    # Two rules in one Ingress that normalized to the same key.
    f"{NS}-app-studio-ic8szp-ingress-studio-prutser-freepod-app-1a2b3c4d5e@kubernetes",
    # An IngressRoute.
    f"{NS}-app-studio-ic8szp-route-abcdef0123456789@kubernetescrd",
]

OTHERS = [
    # A deployment whose name extends this one's.
    f"{NS}-app-studio-ic8szp9-ingress-x-freepod-app@kubernetes",
    # A sibling deployment in a namespace two deployments share.
    f"{NS}-app-studio-zzzzzz-ingress-x-freepod-app@kubernetes",
    # A deployment in another namespace.
    "custom-user-app-zantvoort-7eor1gs7b-custom-user-app-ma0c4b-ingress-a-test@kubernetes",
    # Platform routers.
    "kube-system-http-to-https-a431b128267aabc954fd@kubernetescrd",
    "caelus-tenant-apex-f70cb80bed80619d03d2@kubernetescrd",
    "caelus-caelus-ui-ingress-freepod-eu@kubernetes",
    # Something other than the Ingress providers.
    f"{NS}-app-studio-ic8szp-x@file",
]


@pytest.mark.parametrize("router", OWN)
def test_every_router_the_deployment_owns_is_selected(router):
    assert re.fullmatch(http_logs.router_pattern(TARGET), router)


@pytest.mark.parametrize("router", OTHERS)
def test_no_other_router_is_selected(router):
    assert not re.fullmatch(http_logs.router_pattern(TARGET), router)


def test_the_selector_reads_traefiks_stream_by_router_label():
    selector = http_logs.build_selector(TARGET)
    assert selector == (
        '{namespace="kube-system", container="traefik", router=~'
        + json.dumps(http_logs.router_pattern(TARGET))
        + "}"
    )


def test_label_values_are_escaped_so_a_stray_quote_cannot_escape_the_selector():
    """Nothing reaching here is client-supplied; escaping anyway means the next
    caller does not have to know that."""
    target = LogTarget(deployment_id="d", namespace='ns"} | {x="', name="app")
    selector = http_logs.build_selector(target)
    prefix = '{namespace="kube-system", container="traefik", router=~'
    assert selector.startswith(prefix) and selector.endswith("}")
    # The value is one JSON string literal, so the injected quote and brace
    # stay inside it, and as a regex they match only themselves.
    pattern = json.loads(selector[len(prefix):-1])
    assert re.fullmatch(pattern, 'ns"} | {x="-app-ingress-h@kubernetes')
    assert not re.fullmatch(pattern, "ns-app-ingress-h@kubernetes")


# ---------------------------------------------------------------------------
# The request record
# ---------------------------------------------------------------------------

LINE = {
    "ClientHost": "203.0.113.7",
    "DownstreamContentSize": 512,
    "DownstreamStatus": 200,
    "Duration": 32412345,
    "RequestHost": "studio-prutser.freepod.app",
    "RequestMethod": "GET",
    "RequestPath": "/index.html?q=1",
    "RequestProtocol": "HTTP/2.0",
    "RouterName": OWN[0],
    "StartUTC": "2026-10-23T12:50:48.123456789Z",
    "level": "info",
    "msg": "",
    "request_Referer": "https://example.org/",
    "request_User-Agent": "Mozilla/5.0",
    "time": "2026-10-23T12:50:48Z",
}


def _render(line):
    text = line if isinstance(line, str) else json.dumps(line)
    return http_logs.render(LogEntry(timestamp_ns=TS, line=text, labels={}))


def test_a_request_becomes_exactly_the_twelve_record_fields():
    assert _render(LINE) == {
        "ts": TS,
        "time": "2026-10-23T12:50:48.123456789Z",
        "host": "studio-prutser.freepod.app",
        "remote_addr": "203.0.113.7",
        "method": "GET",
        "path": "/index.html?q=1",
        "protocol": "HTTP/2.0",
        "status": 200,
        "bytes": 512,
        "duration_ms": 32.412,
        "referer": "https://example.org/",
        "user_agent": "Mozilla/5.0",
    }


def test_the_timestamp_stays_a_string():
    assert isinstance(_render(LINE)["ts"], str)


def test_absent_headers_are_null():
    line = {k: v for k, v in LINE.items() if not k.startswith("request_")}
    record = _render(line)
    assert record["referer"] is None
    assert record["user_agent"] is None


def test_a_field_traefik_adds_is_not_passed_on():
    record = _render({**LINE, "ServiceURL": "http://10.42.1.152:8080", "ClientPort": "51234"})
    assert set(record) == {
        "ts", "time", "host", "remote_addr", "method", "path", "protocol",
        "status", "bytes", "duration_ms", "referer", "user_agent",
    }
    assert "10.42.1.152" not in json.dumps(record)


def test_a_sub_millisecond_request_keeps_its_duration():
    assert _render({**LINE, "Duration": 91611})["duration_ms"] == 0.092


@pytest.mark.parametrize(
    "line",
    [
        # The access log's format before it was JSON.
        '216.73.216.206 - - [23/Oct/2026:12:52:20 +0000] "GET /a HTTP/2.0" 404 0 "-" "-" '
        '88103 "ns-name-ingress-host@kubernetes" "http://10.42.1.152:8080" 374ms',
        "not json at all",
        "[1, 2, 3]",
        '"a string"',
        # Traefik's own log line, were one ever to carry the router label.
        json.dumps({"level": "error", "msg": "something", "time": "2026-10-23T12:50:48Z"}),
        json.dumps({**LINE, "DownstreamStatus": "200"}),
        json.dumps({**LINE, "Duration": True}),
    ],
)
def test_a_line_that_is_not_a_request_record_is_skipped(line):
    assert _render(line) is None
