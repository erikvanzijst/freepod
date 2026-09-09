"""The deployment log endpoint: transport, isolation, resume and failure modes.

Loki is faked throughout. What is being asserted is the API's own contract --
what query it constructs, what it puts on the wire, and how it behaves when the
store is unavailable -- none of which needs a real log store, and all of which
would be untestable against one.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest

from app.config import CaelusSettings
from app.models import DeploymentORM, DeploymentReconcileJobORM, DeploymentReleaseORM
from app.services import deployment_logs as log_service
from app.services.loki import LogEntry, LokiException
from app.services.jobs import JobService
from sqlmodel import select
from tests.conftest import client, db_session  # noqa: F401
from tests.conftest import create_free_plan_template, create_user


SCHEMA = {
    "type": "object",
    "properties": {"host": {"type": "string", "title": "hostname"}},
}

# Realistic nanosecond values: ~1.76e18, comfortably past the ~9.01e15 an
# IEEE-754 double represents exactly. That is the whole point of these.
TS1 = "1787066060123456789"
TS2 = "1787066061987654321"
RELEASE_UUID = "3f2a9c14-0b6d-4e18-9a77-5c1e8d4b2f60"


class FakeLoki:
    """Records the queries issued and replays canned batches."""

    def __init__(self, batches=None, raises: Exception | None = None):
        self.queries: list[dict] = []
        self._batches = list(batches or [])
        self._raises = raises

    async def aquery_range(self, *, query, start_ns, limit, direction, end_ns=None):
        self.queries.append(
            {
                "query": query,
                "start_ns": start_ns,
                "end_ns": end_ns,
                "limit": limit,
                "direction": direction,
            }
        )
        if self._raises is not None:
            raise self._raises
        return self._batches.pop(0) if self._batches else []

    def query_range(self, **kwargs):
        raise AssertionError("the endpoint must use the async client")


@pytest.fixture
def loki(monkeypatch):
    """Install a fake store and a base URL, so `from_settings` is satisfied."""
    holder = {}

    def install(batches=None, raises=None):
        fake = FakeLoki(batches=batches, raises=raises)
        holder["fake"] = fake
        monkeypatch.setattr(
            "app.api.users.LokiQueryClient.from_settings", staticmethod(lambda *a, **k: fake)
        )
        return fake

    yield install


@pytest.fixture(autouse=True)
def _log_settings(monkeypatch):
    """Pin the log settings so tests do not depend on ambient .env."""
    settings = CaelusSettings(
        loki_base_url="http://loki.invalid:3100",
        log_tail_lines=200,
        log_max_tail_lines=5000,
        log_poll_interval_seconds=0.01,
        log_keepalive_seconds=1,
        log_stream_max_lifetime_seconds=3600,
        log_max_streams_per_user=3,
        reserved_hostnames=[],
        domain="example.test",
        _env_file=None,
    )
    monkeypatch.setattr("app.api.users.get_settings", lambda: settings)
    return settings


def _setup(client, db_session, email, chart="custom"):
    """A user, product, canonical template, free plan and one deployment.

    `chart` is what matters: release pinning is offered only where the chart
    renders `caelus.dev/release-id`, which today is `custom` alone. Product
    names must be unique, so they are derived from the caller's email.
    """
    user_id = create_user(client, email)["id"]
    stem = email.split("@")[0]
    product_id = client.post(
        "/api/products", json={"name": f"{chart}-{stem}", "description": "d"}
    ).json()["id"]
    template_id = client.post(
        f"/api/products/{product_id}/templates",
        json={
            "chart_ref": f"oci://registry.home/helm/{chart}",
            "chart_version": "1.0.0",
            "values_schema_json": SCHEMA,
        },
    ).json()["id"]
    client.put(f"/api/products/{product_id}", json={"template_id": template_id})
    plan_id = create_free_plan_template(db_session, product_id)
    deployment_id = UUID(
        client.post(
            f"/api/users/{user_id}/deployments",
            json={
                "desired_template_id": template_id,
                "plan_template_id": plan_id,
                "user_values_json": {"host": f"{email.split('@')[0]}.example.com"},
            },
        ).json()["deployment"]["id"]
    )
    return user_id, template_id, deployment_id


def _events(body: str) -> list[dict]:
    """Parse an SSE body into (event, data, id) triples, keepalives excluded."""
    out = []
    for block in body.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        fields = {}
        for line in block.splitlines():
            if line.startswith(":"):
                continue
            key, _, value = line.partition(": ")
            fields[key] = value
        if "data" in fields:
            fields["data"] = json.loads(fields["data"])
        out.append(fields)
    return out


def _entry(ts, line, release=RELEASE_UUID):
    labels = {"namespace": "ns", "instance": "app"}
    if release is not None:
        labels["release_id"] = release
    return LogEntry(timestamp_ns=ts, line=line, labels=labels)


# ---------------------------------------------------------------------------
# The wire format
# ---------------------------------------------------------------------------


def test_a_bounded_read_emits_one_event_per_line_and_completes(client, db_session, loki):
    user_id, _, deployment_id = _setup(client, db_session, "logs@example.com")
    loki([[_entry(TS1, "hello"), _entry(TS2, "world")]])

    resp = client.get(f"/api/users/{user_id}/deployments/{deployment_id}/log")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["x-accel-buffering"] == "no"

    events = _events(resp.text)
    assert [e["event"] for e in events] == ["log", "log", "end"]
    assert [e["data"]["line"] for e in events[:2]] == ["hello", "world"]
    assert events[-1]["data"]["reason"] == "complete"


def test_the_timestamp_is_a_json_string_and_survives_the_wire(client, db_session, loki):
    """A nanosecond value exceeds what an IEEE-754 double holds exactly, so a
    JSON *number* would be silently rounded by any JavaScript consumer."""
    user_id, _, deployment_id = _setup(client, db_session, "ts@example.com")
    loki([[_entry(TS1, "hello")]])

    resp = client.get(f"/api/users/{user_id}/deployments/{deployment_id}/log")
    raw = next(b for b in resp.text.split("\n\n") if '"line":"hello"' in b)
    # Quoted in the raw payload, not just after parsing.
    assert f'"ts":"{TS1}"' in raw
    event = _events(resp.text)[0]
    assert isinstance(event["data"]["ts"], str)
    assert event["data"]["ts"] == TS1
    # Round-trips exactly through int, which a float would not.
    assert str(int(event["data"]["ts"])) == TS1


def test_the_event_id_mirrors_the_timestamp(client, db_session, loki):
    """So a stock `EventSource` consumer gets `Last-Event-ID` for free."""
    user_id, _, deployment_id = _setup(client, db_session, "id@example.com")
    loki([[_entry(TS1, "hello")]])
    resp = client.get(f"/api/users/{user_id}/deployments/{deployment_id}/log")
    event = _events(resp.text)[0]
    assert event["id"] == event["data"]["ts"] == TS1


def test_each_line_carries_its_release(client, db_session, loki):
    user_id, _, deployment_id = _setup(client, db_session, "attr@example.com")
    loki([[_entry(TS1, "a"), _entry(TS2, "b", release=None)]])
    resp = client.get(f"/api/users/{user_id}/deployments/{deployment_id}/log")
    events = _events(resp.text)
    assert events[0]["data"]["release"] == RELEASE_UUID
    # Null rather than absent on a pod with no release label -- a readable
    # deployment with attribution unavailable, not an error.
    assert events[1]["data"]["release"] is None


def test_a_deployment_that_wrote_nothing_is_an_empty_stream_not_an_error(client, db_session, loki):
    user_id, _, deployment_id = _setup(client, db_session, "silent@example.com")
    loki([[]])
    resp = client.get(f"/api/users/{user_id}/deployments/{deployment_id}/log")
    assert resp.status_code == 200
    events = _events(resp.text)
    assert [e["event"] for e in events] == ["end"]
    assert events[0]["data"]["reason"] == "complete"


# ---------------------------------------------------------------------------
# The query is the server's
# ---------------------------------------------------------------------------


def test_the_selector_is_built_from_the_deployment_row(client, db_session, loki):
    user_id, _, deployment_id = _setup(client, db_session, "sel@example.com")
    fake = loki([[]])
    client.get(f"/api/users/{user_id}/deployments/{deployment_id}/log")

    deployment = db_session.get(DeploymentORM, deployment_id)
    query = fake.queries[0]["query"]
    assert query == (
        f'{{namespace="{deployment.namespace}", instance="{deployment.name}", '
        f'container!="ssh"}}'
    )


@pytest.mark.parametrize(
    "param",
    ["query", "selector", "match", "matcher", "namespace", "logql", "expr", "instance"],
)
def test_a_client_supplied_selector_has_no_effect_on_the_query(client, db_session, loki, param):
    """Loki holds every tenant's output and the platform's own in one tenancy,
    so a client-influenced selector would be a cross-tenant read and a
    platform-secret read at once."""
    user_id, _, deployment_id = _setup(client, db_session, f"inj{param}@example.com")
    fake = loki([[]])

    client.get(
        f"/api/users/{user_id}/deployments/{deployment_id}/log",
        params={param: '{namespace="caelus-api"}'},
    )
    deployment = db_session.get(DeploymentORM, deployment_id)
    assert fake.queries[0]["query"] == (
        f'{{namespace="{deployment.namespace}", instance="{deployment.name}", '
        f'container!="ssh"}}'
    )
    assert "caelus-api" not in fake.queries[0]["query"]


def test_the_first_connect_is_backward_and_bounded(client, db_session, loki):
    """Loki defaults to `backward`, but it is passed explicitly, and the window
    is explicit too -- Loki's own default is one hour, which would silently
    return nothing for an application quiet longer than that."""
    user_id, _, deployment_id = _setup(client, db_session, "first@example.com")
    fake = loki([[]])
    client.get(f"/api/users/{user_id}/deployments/{deployment_id}/log", params={"tail": 50})
    assert fake.queries[0]["direction"] == "backward"
    assert fake.queries[0]["limit"] == 50
    assert fake.queries[0]["end_ns"] is not None


def test_the_tail_is_capped_by_the_platform(client, db_session, loki, _log_settings):
    user_id, _, deployment_id = _setup(client, db_session, "cap@example.com")
    fake = loki([[]])
    client.get(f"/api/users/{user_id}/deployments/{deployment_id}/log", params={"tail": 10**9})
    assert fake.queries[0]["limit"] == _log_settings.log_max_tail_lines


# ---------------------------------------------------------------------------
# Resuming
# ---------------------------------------------------------------------------


def test_resuming_is_inclusive_and_forward(client, db_session, loki):
    """Inclusive is the mechanism: every undelivered line is at or after the
    cursor, so it cannot leave a gap. Resuming at +1ns would drop any line
    sharing that instant."""
    user_id, _, deployment_id = _setup(client, db_session, "resume@example.com")
    fake = loki([[]])
    client.get(
        f"/api/users/{user_id}/deployments/{deployment_id}/log", params={"since": TS1}
    )
    assert fake.queries[0]["direction"] == "forward"
    assert fake.queries[0]["start_ns"] == int(TS1)  # exactly, not +1
    assert fake.queries[0]["end_ns"] is None


def test_a_line_sharing_the_boundary_nanosecond_is_redelivered(client, db_session, loki):
    """At-least-once. A duplicated line after a reconnect is the mechanism
    working; a missing one is the one being looked for."""
    user_id, _, deployment_id = _setup(client, db_session, "dup@example.com")
    loki([[_entry(TS1, "boundary"), _entry(TS1, "sibling")]])
    resp = client.get(
        f"/api/users/{user_id}/deployments/{deployment_id}/log", params={"since": TS1}
    )
    lines = [e["data"]["line"] for e in _events(resp.text) if e["event"] == "log"]
    assert lines == ["boundary", "sibling"]


@pytest.mark.parametrize(
    "bad", ["not-a-number", "-1", "1.5", "0", "12345", " 999 x", "1e18", "0x10"]
)
def test_a_malformed_resume_point_is_rejected_and_reaches_no_query(
    client, db_session, loki, bad
):
    user_id, _, deployment_id = _setup(client, db_session, f"bad{abs(hash(bad))}@example.com")
    fake = loki([[]])
    resp = client.get(
        f"/api/users/{user_id}/deployments/{deployment_id}/log", params={"since": bad}
    )
    assert resp.status_code == 400
    # Nothing derived from the supplied value reached the store.
    assert fake.queries == []


def test_a_valid_resume_point_is_an_int_before_it_becomes_start(client, db_session, loki):
    """Never through a float at any point: `float(TS1)` loses the low digits."""
    assert log_service.parse_resume_timestamp(TS1) == int(TS1)
    assert str(log_service.parse_resume_timestamp(TS1)) == TS1
    assert int(float(TS1)) != int(TS1)  # the corruption being avoided


# ---------------------------------------------------------------------------
# Release pinning
# ---------------------------------------------------------------------------


def _release(db_session, deployment_id, *, number, started=True):
    deployment = db_session.get(DeploymentORM, deployment_id)
    release = DeploymentReleaseORM(
        number=number,
        deployment_id=deployment.id,
        template_id=deployment.desired_template_id,
        started_at=__import__("datetime").datetime.now(__import__("datetime").UTC) if started else None,
    )
    db_session.add(release)
    db_session.commit()
    db_session.refresh(release)
    return release


def test_pinning_narrows_the_selector_to_one_release(client, db_session, loki):
    user_id, _, deployment_id = _setup(client, db_session, "pin@example.com")
    release = _release(db_session, deployment_id, number=2)
    fake = loki([[]])

    resp = client.get(
        f"/api/users/{user_id}/deployments/{deployment_id}/log", params={"release": 2}
    )
    assert resp.status_code == 200
    assert f'release_id="{release.id}"' in fake.queries[0]["query"]


def test_pinning_to_a_release_of_another_deployment_is_refused(client, db_session, loki):
    user_id, _, first = _setup(client, db_session, "pin1@example.com")
    _release(db_session, first, number=7)
    # A second deployment for the same user, which has no release 7.
    _, _, second = _setup(client, db_session, "pin2@example.com")
    fake = loki([[]])

    owner = db_session.get(DeploymentORM, second).user_id
    resp = client.get(f"/api/users/{owner}/deployments/{second}/log", params={"release": 7})
    assert resp.status_code == 404
    # No output from any other deployment was fetched.
    assert fake.queries == []


def test_pinning_on_a_product_without_release_labels_is_reported_not_empty(
    client, db_session, loki
):
    """An empty stream would assert the release produced no output, which is a
    different and misleading claim."""
    user_id, _, deployment_id = _setup(
        client, db_session, "curated@example.com", chart="nextcloud"
    )
    _release(db_session, deployment_id, number=2)
    fake = loki([[]])

    resp = client.get(
        f"/api/users/{user_id}/deployments/{deployment_id}/log", params={"release": 2}
    )
    assert resp.status_code == 400
    assert "attribution is unavailable" in resp.json()["detail"].lower()
    assert fake.queries == []


def test_the_unpinned_read_still_works_on_such_a_product(client, db_session, loki):
    user_id, _, deployment_id = _setup(
        client, db_session, "curated2@example.com", chart="nextcloud"
    )
    loki([[_entry(TS1, "nextcloud says hi", release=None)]])
    resp = client.get(f"/api/users/{user_id}/deployments/{deployment_id}/log")
    assert resp.status_code == 200
    assert [e["data"]["line"] for e in _events(resp.text) if e["event"] == "log"] == [
        "nextcloud says hi"
    ]


def test_pinning_to_a_release_that_never_ran_says_so(client, db_session, loki):
    user_id, _, deployment_id = _setup(client, db_session, "neverran@example.com")
    _release(db_session, deployment_id, number=3, started=False)
    loki([[]])

    resp = client.get(
        f"/api/users/{user_id}/deployments/{deployment_id}/log", params={"release": 3}
    )
    assert resp.status_code == 200
    events = _events(resp.text)
    assert events[-1]["data"]["reason"] == "release_never_ran"
    # And not a silent empty stream indistinguishable from a quiet application.
    assert not any(e["event"] == "log" for e in events)


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_another_users_deployment_is_404_not_403(client, db_session, loki):
    """Indistinguishable from one that does not exist, so the endpoint cannot
    be used to discover other users' deployments."""
    _, _, deployment_id = _setup(client, db_session, "owner@example.com")
    intruder_id = create_user(client, "intruder@example.com")["id"]
    fake = loki([[]])

    resp = client.get(f"/api/users/{intruder_id}/deployments/{deployment_id}/log")
    assert resp.status_code == 404
    assert fake.queries == []


def test_an_unknown_deployment_is_404(client, db_session, loki):
    user_id, _, _ = _setup(client, db_session, "unknown@example.com")
    loki([[]])
    resp = client.get(f"/api/users/{user_id}/deployments/{uuid4()}/log")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Store unavailability
# ---------------------------------------------------------------------------


def test_an_unreachable_store_is_503_not_an_empty_success(client, db_session, loki):
    """The one failure mode this requirement exists to prevent: an empty 200
    asserts the application printed nothing."""
    user_id, _, deployment_id = _setup(client, db_session, "down@example.com")
    loki(raises=LokiException("connection refused"))

    resp = client.get(f"/api/users/{user_id}/deployments/{deployment_id}/log")
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


def test_an_unconfigured_store_is_reported_as_a_platform_condition(
    client, db_session, monkeypatch
):
    user_id, _, deployment_id = _setup(client, db_session, "unconf@example.com")
    monkeypatch.setattr(
        "app.api.users.get_settings",
        lambda: CaelusSettings(loki_base_url="", reserved_hostnames=[], domain="example.test", _env_file=None),
    )
    resp = client.get(f"/api/users/{user_id}/deployments/{deployment_id}/log")
    assert resp.status_code >= 400
    assert resp.status_code != 200


# ---------------------------------------------------------------------------
# Stream limits
# ---------------------------------------------------------------------------


def test_the_stream_cap_is_released_when_a_stream_ends(client, db_session, loki):
    """Otherwise a user's cap leaks and they lock themselves out of their own
    logs after `limit` reads."""
    user_id, _, deployment_id = _setup(client, db_session, "capfree@example.com")
    loki([[], [], [], []])
    caller_id = client.get("/api/me").json()["id"]
    for _ in range(5):
        assert (
            client.get(f"/api/users/{user_id}/deployments/{deployment_id}/log").status_code
            == 200
        )
    assert log_service.stream_registry.open_count(caller_id) == 0


def test_too_many_concurrent_streams_are_refused(client, db_session, loki, _log_settings):
    """Counted per *caller*, not per deployment owner: the limit protects the
    single API worker from one client, and an administrator reading many users'
    logs is exactly the client it protects against."""
    user_id, _, deployment_id = _setup(client, db_session, "many@example.com")
    loki([[]])
    caller_id = client.get("/api/me").json()["id"]

    for _ in range(_log_settings.log_max_streams_per_user):
        log_service.stream_registry.acquire(
            caller_id, limit=_log_settings.log_max_streams_per_user
        )
    try:
        resp = client.get(f"/api/users/{user_id}/deployments/{deployment_id}/log")
        assert resp.status_code == 400
        assert "concurrent log streams" in resp.json()["detail"]
    finally:
        for _ in range(_log_settings.log_max_streams_per_user):
            log_service.stream_registry.release(caller_id)
    assert log_service.stream_registry.open_count(caller_id) == 0
