"""The database housekeeping worker: the quota tick and its guards."""

from __future__ import annotations

import pytest
from datetime import UTC, datetime, timedelta
from sqlmodel import Session

from app import db_worker
from app.config import CaelusSettings
from app.services import relational_storage as rs
from app.services.errors import IntegrityException
from tests import tenant_cluster
from tests.conftest import TEST_DATABASE_URL
from tests.test_relational_storage import (  # noqa: F401  (fixtures)
    KEY,
    _bootstrapped_cluster,
    _clean_cluster,
    _connect_as_tenant,
    _deployment,
    _keyring,
    settings,
    tenant_db,
)


@pytest.fixture
def session(test_database, db_session):
    with Session(test_database.engine) as session:
        yield session


def _sized(tenant_db, percent_by_database: dict[str, float], allowance: int):
    """Report each database as a share of the allowance."""
    original = tenant_db.database_size_bytes

    def sized(name: str) -> int:
        return int(allowance * percent_by_database.get(name, 0) / 100)

    tenant_db.database_size_bytes = sized  # type: ignore[method-assign]
    return original


# ── Tick guarding ─────────────────────────────────────────────────────────


def test_a_failing_tick_does_not_stop_the_others():
    """Purge performs the only irreversible operation here, so a bug in one
    tick must not take quota enforcement down with it."""
    ran: list[str] = []

    def boom() -> db_worker.TickResult:
        ran.append("boom")
        raise RuntimeError("tick exploded")

    def fine() -> db_worker.TickResult:
        ran.append("fine")
        return db_worker.TickResult(name="fine", swept=1)

    results = db_worker.run_ticks([boom, fine])

    assert ran == ["boom", "fine"]
    assert [r.name for r in results] == ["fine"]


def test_one_deployments_failure_does_not_abandon_the_fleet(
    session, tenant_db, settings, monkeypatch
):
    healthy = _deployment(session)
    rs.ensure_database(session, healthy, tenant_db=tenant_db, settings=settings)
    broken = _deployment(session)
    rs.ensure_database(session, broken, tenant_db=tenant_db, settings=settings)

    real = rs.evaluate_quota_state

    def evaluate(session_, deployment, **kwargs):
        if deployment.id == broken.id:
            raise RuntimeError("measurement blew up")
        return real(session_, deployment, **kwargs)

    monkeypatch.setattr(rs, "evaluate_quota_state", evaluate)
    monkeypatch.setattr(db_worker.relational_storage, "evaluate_quota_state", evaluate)

    result = db_worker.quota_tick(session, tenant_db=tenant_db, settings=settings)

    assert result.swept == 1
    assert str(broken.id) in result.failed


# ── The sweep ─────────────────────────────────────────────────────────────


def test_the_sweep_walks_a_deployment_up_the_ladder_and_back(
    session, tenant_db, settings
):
    deployment = _deployment(session)
    credentials = rs.ensure_database(session, deployment, tenant_db=tenant_db, settings=settings)
    allowance = rs.resolve_quota_bytes(deployment)
    database = credentials.database

    original = _sized(tenant_db, {database: 10}, allowance)
    try:
        assert db_worker.quota_tick(session, tenant_db=tenant_db, settings=settings).swept == 1
        assert rs.get_record(session, deployment).quota_state == rs.QUOTA_OK

        for percent, expected in (
            (85, rs.QUOTA_WARNED),
            (100, rs.QUOTA_READONLY),
            (150, rs.QUOTA_BLOCKED),
            (120, rs.QUOTA_READONLY),
            (10, rs.QUOTA_OK),
        ):
            _sized(tenant_db, {database: percent}, allowance)
            result = db_worker.quota_tick(session, tenant_db=tenant_db, settings=settings)
            assert rs.get_record(session, deployment).quota_state == expected
            assert str(deployment.id) in result.changed
    finally:
        tenant_db.database_size_bytes = original  # type: ignore[method-assign]

    # Back at the bottom the tenant writes again, which is the property the
    # state name is standing in for.
    with _connect_as_tenant(credentials) as conn:
        conn.execute("CREATE TABLE writable_again (id int)")


def test_a_deployment_awaiting_purge_is_left_alone(session, tenant_db, settings):
    deployment = _deployment(session)
    credentials = rs.ensure_database(session, deployment, tenant_db=tenant_db, settings=settings)
    rs.teardown_database(session, deployment, tenant_db=tenant_db, settings=settings)

    result = db_worker.quota_tick(session, tenant_db=tenant_db, settings=settings)

    assert result.swept == 0
    assert not tenant_db.fetchval(
        "SELECT rolcanlogin FROM pg_roles WHERE rolname = %s", (credentials.user,)
    )


# ── Threshold mail ────────────────────────────────────────────────────────


@pytest.fixture
def sent(monkeypatch):
    """Capture what would have gone to the relay."""
    messages: list[dict] = []

    def send_email(*, to, subject, body, html=None, settings=None):
        messages.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr("app.services.relational_storage.mailer.send_email", send_email)
    return messages


def test_a_deployment_hovering_above_a_threshold_is_mailed_once(
    session, tenant_db, settings, sent
):
    deployment = _deployment(session)
    credentials = rs.ensure_database(session, deployment, tenant_db=tenant_db, settings=settings)
    allowance = rs.resolve_quota_bytes(deployment)
    original = tenant_db.database_size_bytes
    try:
        for percent in (85, 87, 82):
            _sized(tenant_db, {credentials.database: percent}, allowance)
            db_worker.quota_tick(session, tenant_db=tenant_db, settings=settings)
        assert len(sent) == 1
        assert "80% full" in sent[0]["subject"]
        assert sent[0]["to"] == deployment.user.email

        # Crossing the next rung is news again.
        _sized(tenant_db, {credentials.database: 95}, allowance)
        db_worker.quota_tick(session, tenant_db=tenant_db, settings=settings)
        assert len(sent) == 2
        assert "90% full" in sent[1]["subject"]

        # At the allowance the message says what changed for the application.
        _sized(tenant_db, {credentials.database: 101}, allowance)
        db_worker.quota_tick(session, tenant_db=tenant_db, settings=settings)
        assert len(sent) == 3
        assert "read-only" in sent[2]["subject"]
        assert "read-only" in sent[2]["body"]

        # And 150% is deliberately silent: the tenant has been told twice.
        _sized(tenant_db, {credentials.database: 160}, allowance)
        db_worker.quota_tick(session, tenant_db=tenant_db, settings=settings)
        assert len(sent) == 3
        assert rs.get_record(session, deployment).quota_state == rs.QUOTA_BLOCKED
    finally:
        tenant_db.database_size_bytes = original  # type: ignore[method-assign]


def test_falling_back_to_ok_re_arms_the_ladder(session, tenant_db, settings, sent):
    deployment = _deployment(session)
    credentials = rs.ensure_database(session, deployment, tenant_db=tenant_db, settings=settings)
    allowance = rs.resolve_quota_bytes(deployment)
    original = tenant_db.database_size_bytes
    try:
        for percent in (85, 10, 85):
            _sized(tenant_db, {credentials.database: percent}, allowance)
            db_worker.quota_tick(session, tenant_db=tenant_db, settings=settings)
    finally:
        tenant_db.database_size_bytes = original  # type: ignore[method-assign]

    assert len(sent) == 2


def test_an_unsent_mail_is_retried_rather_than_suppressed(
    session, tenant_db, settings, monkeypatch
):
    """The suppression marker records that a tenant was told. A relay outage
    means they were not."""
    deployment = _deployment(session)
    credentials = rs.ensure_database(session, deployment, tenant_db=tenant_db, settings=settings)
    allowance = rs.resolve_quota_bytes(deployment)

    attempts: list[int] = []

    def failing(*, to, subject, body, html=None, settings=None):
        attempts.append(1)
        return False

    monkeypatch.setattr("app.services.relational_storage.mailer.send_email", failing)
    original = tenant_db.database_size_bytes
    try:
        _sized(tenant_db, {credentials.database: 85}, allowance)
        db_worker.quota_tick(session, tenant_db=tenant_db, settings=settings)
        assert rs.get_record(session, deployment).warned_threshold is None

        db_worker.quota_tick(session, tenant_db=tenant_db, settings=settings)
    finally:
        tenant_db.database_size_bytes = original  # type: ignore[method-assign]

    assert len(attempts) == 2
    # The quota state itself is recorded regardless of the relay.
    assert rs.get_record(session, deployment).quota_state == rs.QUOTA_WARNED


def test_a_reconcile_evaluation_sends_nothing(session, tenant_db, settings, sent):
    deployment = _deployment(session)
    rs.ensure_database(session, deployment, tenant_db=tenant_db, settings=settings)
    allowance = rs.resolve_quota_bytes(deployment)
    record = rs.get_record(session, deployment)
    original = tenant_db.database_size_bytes
    try:
        _sized(tenant_db, {record.db_name: 95}, allowance)
        rs.ensure_database(session, deployment, tenant_db=tenant_db, settings=settings)
    finally:
        tenant_db.database_size_bytes = original  # type: ignore[method-assign]

    assert sent == []


# ── Purge ─────────────────────────────────────────────────────────────────


def _due_for_purge(session, deployment, tenant_db, settings, *, days_ago: float = 1):
    """Tear down, then move the deadline into the past."""
    rs.teardown_database(session, deployment, tenant_db=tenant_db, settings=settings)
    record = rs.get_record(session, deployment)
    record.purge_after = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago)
    session.add(record)
    session.commit()
    return record


def test_a_due_deployment_is_destroyed(session, tenant_db, settings):
    deployment = _deployment(session)
    credentials = rs.ensure_database(session, deployment, tenant_db=tenant_db, settings=settings)
    _due_for_purge(session, deployment, tenant_db, settings)

    result = db_worker.purge_tick(session, tenant_db=tenant_db, settings=settings)

    assert result.swept == 1
    assert not tenant_db.database_exists(credentials.database)
    assert not tenant_db.role_exists(credentials.user)
    # The row goes with the objects: its absence is what "not provisioned"
    # means, and leaving it would make the orphan sweep lie.
    assert rs.get_record(session, deployment) is None


def test_a_deployment_inside_its_grace_period_is_left_alone(session, tenant_db, settings):
    deployment = _deployment(session)
    credentials = rs.ensure_database(session, deployment, tenant_db=tenant_db, settings=settings)
    rs.teardown_database(session, deployment, tenant_db=tenant_db, settings=settings)

    result = db_worker.purge_tick(session, tenant_db=tenant_db, settings=settings)

    assert result.swept == 0
    assert tenant_db.database_exists(credentials.database)
    assert rs.get_record(session, deployment) is not None


def test_a_live_deployment_is_never_purged(session, tenant_db, settings):
    """No `purge_after` at all: the deployment was never deleted."""
    deployment = _deployment(session)
    credentials = rs.ensure_database(session, deployment, tenant_db=tenant_db, settings=settings)

    assert db_worker.purge_tick(session, tenant_db=tenant_db, settings=settings).swept == 0
    assert tenant_db.database_exists(credentials.database)


def test_purging_a_row_that_is_not_due_is_refused(session, tenant_db, settings):
    """The guard lives with the destruction, not only in the query that finds
    it: a caller with a bad clock must not be able to skip the window."""
    deployment = _deployment(session)
    rs.ensure_database(session, deployment, tenant_db=tenant_db, settings=settings)
    rs.teardown_database(session, deployment, tenant_db=tenant_db, settings=settings)
    record = rs.get_record(session, deployment)

    with pytest.raises(IntegrityException):
        rs.purge_database(session, record, tenant_db=tenant_db, settings=settings)

    record.purge_after = None
    session.add(record)
    session.commit()
    with pytest.raises(IntegrityException):
        rs.purge_database(session, record, tenant_db=tenant_db, settings=settings)


def test_a_run_is_capped(session, tenant_db, settings, monkeypatch):
    """A clock that jumped must not cascade into destroying the whole fleet."""
    for _ in range(3):
        deployment = _deployment(session)
        rs.ensure_database(session, deployment, tenant_db=tenant_db, settings=settings)
        _due_for_purge(session, deployment, tenant_db, settings)

    capped = CaelusSettings(
        **{**settings.model_dump(), "db_worker_max_purges_per_run": 2}, _env_file=None
    )
    assert db_worker.purge_tick(session, tenant_db=tenant_db, settings=capped).swept == 2
    # The rest are still there for the next run, not lost.
    assert db_worker.purge_tick(session, tenant_db=tenant_db, settings=capped).swept == 1


def test_a_purge_succeeds_while_sessions_are_connected(session, tenant_db, settings):
    """`DROP DATABASE` fails outright while anyone is connected, which is why
    it is WITH (FORCE) and why it lives in a re-runnable tick."""
    deployment = _deployment(session)
    credentials = rs.ensure_database(session, deployment, tenant_db=tenant_db, settings=settings)
    conn = _connect_as_tenant(credentials)
    try:
        conn.execute("SELECT 1")
        _due_for_purge(session, deployment, tenant_db, settings)
        assert db_worker.purge_tick(session, tenant_db=tenant_db, settings=settings).swept == 1
    finally:
        conn.close()
    assert not tenant_db.database_exists(credentials.database)


# ── Orphans ───────────────────────────────────────────────────────────────


def test_a_role_without_a_database_is_reported(session, tenant_db, settings):
    """The partial-provisioning case: the role is created before the database
    and both before the row, so a worker killed in between leaves either."""
    tenant_db.execute("CREATE ROLE dpl_orphanrole NOLOGIN")

    result = db_worker.orphan_tick(session, tenant_db=tenant_db, settings=settings)

    assert result.orphans["roles"] == ["dpl_orphanrole"]
    assert result.orphans["databases"] == []
    assert result.swept == 1


def test_a_provisioned_deployment_is_not_an_orphan(session, tenant_db, settings):
    deployment = _deployment(session)
    rs.ensure_database(session, deployment, tenant_db=tenant_db, settings=settings)

    result = db_worker.orphan_tick(session, tenant_db=tenant_db, settings=settings)

    assert result.orphans == {"databases": [], "roles": []}


def test_the_orphan_sweep_destroys_nothing(session, tenant_db, settings):
    tenant_db.execute("CREATE ROLE dpl_orphanrole NOLOGIN")
    db_worker.orphan_tick(session, tenant_db=tenant_db, settings=settings)
    assert tenant_db.role_exists("dpl_orphanrole")


def test_a_deployment_awaiting_purge_is_not_an_orphan(session, tenant_db, settings):
    """Its row still accounts for it, which is the whole reason the row
    outlives the deployment."""
    deployment = _deployment(session)
    rs.ensure_database(session, deployment, tenant_db=tenant_db, settings=settings)
    rs.teardown_database(session, deployment, tenant_db=tenant_db, settings=settings)

    result = db_worker.orphan_tick(session, tenant_db=tenant_db, settings=settings)

    assert result.orphans == {"databases": [], "roles": []}


# ── Startup ───────────────────────────────────────────────────────────────


def test_every_tick_runs_on_the_first_pass(monkeypatch, settings):
    """A restart is also a full sweep: nothing waits a day to run once."""
    ran: list[str] = []

    def record(name):
        def tick(session, **kwargs):
            ran.append(name)
            return db_worker.TickResult(name=name)

        return tick

    monkeypatch.setattr(db_worker, "quota_tick", record("quota"))
    monkeypatch.setattr(db_worker, "purge_tick", record("purge"))
    monkeypatch.setattr(db_worker, "orphan_tick", record("orphan"))

    db_worker.run_db_worker(settings=settings, tenant_db=object(), max_passes=1)

    assert ran == ["quota", "purge", "orphan"]


def test_the_worker_starts_without_a_keyring(cli_runner, monkeypatch, settings):
    """Unlike the API and `caelus worker`: it decrypts nothing, so a keyring
    problem must not stop quota enforcement."""
    runner, cli_app = cli_runner
    monkeypatch.setattr(
        "app.services.var_crypto.get_settings",
        lambda: CaelusSettings(var_encryption_keys=[], _env_file=None),
    )
    passes: list[int] = []

    def run(*, settings=None, tenant_db=None, emit=None, max_passes=None):
        passes.append(1)

    monkeypatch.setattr("app.db_worker.run_db_worker", run)
    result = runner.invoke(cli_app, ["db-worker"])

    assert result.exit_code == 0, getattr(result, "stderr", result.output)
    assert passes == [1]
