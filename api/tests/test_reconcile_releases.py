"""The reconciler's half of the ledger: it applies a release and records its outcome.

The reconciler creates no releases. It reads `deployment.desired_release_id`,
marks when work began, runs Helm, and writes the outcome exactly once — on both
the success and the failure path — setting `applied_release_id` only on success.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import (
    DeploymentORM,
    DeploymentReleaseORM,
    ProductTemplateVersionORM,
    ReleaseStatus,
)
from app.services.reconcile import DeploymentReconciler
from tests.provisioner_utils import FakeProvisioner
from tests.test_reconcile_service import (  # noqa: F401
    _reconcile_tls_settings,
    _seed_deployment,
)
from tests.conftest import db_session  # noqa: F401


def _desired_release(db_session, deployment_id) -> DeploymentReleaseORM:
    deployment = db_session.get(DeploymentORM, deployment_id)
    return db_session.get(DeploymentReleaseORM, deployment.desired_release_id)


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------


def test_a_successful_apply_records_the_outcome_and_moves_the_applied_pointer(db_session):
    deployment_id = _seed_deployment(db_session)
    reconciler = DeploymentReconciler(session=db_session, provisioner=FakeProvisioner())

    reconciler.reconcile(deployment_id)

    db_session.expire_all()
    deployment = db_session.get(DeploymentORM, deployment_id)
    release = db_session.get(DeploymentReleaseORM, deployment.desired_release_id)
    assert release.started_at is not None
    assert release.ended_at is not None
    assert release.error is None
    assert release.helm_revision == 1
    assert release.status is ReleaseStatus.SUCCEEDED
    # What it desired is now what it is running.
    assert deployment.applied_release_id == release.id


def test_the_reconciler_creates_no_releases(db_session):
    deployment_id = _seed_deployment(db_session)
    before = db_session.exec(
        DeploymentReleaseORM.__table__.select()
    ).all()
    DeploymentReconciler(session=db_session, provisioner=FakeProvisioner()).reconcile(deployment_id)
    db_session.expire_all()
    after = db_session.exec(DeploymentReleaseORM.__table__.select()).all()
    assert len(after) == len(before) == 1


def test_the_release_identity_reaches_helm_as_a_system_value_and_nothing_else_does(db_session):
    deployment_id = _seed_deployment(db_session)
    provisioner = FakeProvisioner()
    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    deployment = db_session.get(DeploymentORM, deployment_id)
    release = _desired_release(db_session, deployment_id)
    values = next(c[1] for c in provisioner.calls if c[0] == "helm_upgrade_install")["values"]
    assert values["caelus"]["releaseId"] == str(deployment.desired_release_id)
    # Both spellings of the one release travel, because they answer to different
    # readers: the id is what the log pipeline keys a stream on, the number is
    # what `freepod releases` shows and what the SSH session banner reports.
    # A string, so an absent value is distinguishable from release 0.
    assert values["caelus"]["releaseNumber"] == str(release.number)
    # Chart values carry what a chart renders, and a build reference never is.
    assert "buildId" not in values["caelus"]
    assert "build_id" not in values["caelus"]


def test_a_tenant_cannot_forge_the_release_id_through_user_values(db_session):
    """System overrides are merged last, which is what the chart's
    `caelus.owner.id` assertion already rests on.

    The seeded template's schema forbids a `caelus` key outright, so the values
    are planted on a schema that permits one -- otherwise validation rejects the
    write long before precedence is reached, and the test would pass without
    exercising the merge at all.
    """
    deployment_id = _seed_deployment(db_session)
    deployment = db_session.get(DeploymentORM, deployment_id)
    template = db_session.get(
        ProductTemplateVersionORM, deployment.desired_template_id
    )
    template.values_schema_json = {"type": "object", "additionalProperties": True}
    db_session.add(template)
    deployment.user_values_json = {
        **(deployment.user_values_json or {}),
        "caelus": {"releaseId": "00000000-0000-0000-0000-000000000000"},
    }
    db_session.add(deployment)
    db_session.commit()

    provisioner = FakeProvisioner()
    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    db_session.expire_all()
    deployment = db_session.get(DeploymentORM, deployment_id)
    values = next(c[1] for c in provisioner.calls if c[0] == "helm_upgrade_install")["values"]
    assert values["caelus"]["releaseId"] == str(deployment.desired_release_id)


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------


def test_a_failed_apply_records_the_error_and_leaves_the_applied_pointer_alone(db_session):
    """`--atomic` has already rolled back to the previously applied release, so
    an unchanged `applied_release_id` is correct rather than a missed update."""
    deployment_id = _seed_deployment(db_session)
    # First rollout succeeds, so there is a previously applied release to keep.
    DeploymentReconciler(session=db_session, provisioner=FakeProvisioner()).reconcile(deployment_id)
    db_session.expire_all()
    deployment = db_session.get(DeploymentORM, deployment_id)
    first_release_id = deployment.applied_release_id

    # A second release for the same deployment, which will fail.
    second = DeploymentReleaseORM(
        number=2,
        deployment_id=deployment.id,
        template_id=deployment.desired_template_id,
        values_json=deployment.user_values_json,
    )
    db_session.add(second)
    deployment.desired_release_id = second.id
    db_session.add(deployment)
    db_session.commit()

    failing = FakeProvisioner()
    failing.raise_on_upgrade = RuntimeError("pod crashed on startup")
    DeploymentReconciler(session=db_session, provisioner=failing).reconcile(deployment_id)

    db_session.expire_all()
    deployment = db_session.get(DeploymentORM, deployment_id)
    second = db_session.get(DeploymentReleaseORM, second.id)
    assert second.ended_at is not None
    assert "pod crashed on startup" in second.error
    assert second.helm_revision is None
    assert second.status is ReleaseStatus.FAILED
    # Still desired, still failed, still running the earlier one.
    assert deployment.desired_release_id == second.id
    assert deployment.applied_release_id == first_release_id


def test_a_superseded_release_is_not_modified(db_session):
    deployment_id = _seed_deployment(db_session)
    DeploymentReconciler(session=db_session, provisioner=FakeProvisioner()).reconcile(deployment_id)
    db_session.expire_all()
    deployment = db_session.get(DeploymentORM, deployment_id)
    first = db_session.get(DeploymentReleaseORM, deployment.applied_release_id)
    snapshot = (first.started_at, first.ended_at, first.error, first.helm_revision, first.number)

    second = DeploymentReleaseORM(
        number=2, deployment_id=deployment.id, template_id=deployment.desired_template_id,
    )
    db_session.add(second)
    deployment.desired_release_id = second.id
    db_session.add(deployment)
    db_session.commit()
    DeploymentReconciler(session=db_session, provisioner=FakeProvisioner()).reconcile(deployment_id)

    db_session.expire_all()
    first = db_session.get(DeploymentReleaseORM, first.id)
    assert (first.started_at, first.ended_at, first.error, first.helm_revision, first.number) == snapshot


# ---------------------------------------------------------------------------
# A worker that died mid-Helm
# ---------------------------------------------------------------------------


class _KilledMidHelm(FakeProvisioner):
    """A worker that dies during `helm upgrade`.

    Raises a BaseException rather than an Exception on purpose: the reconciler
    catches Exception and turns it into a recorded failure, which is *not* what
    a killed process does. Nothing after the try block runs, exactly as with a
    SIGKILL.
    """

    def helm_upgrade_install(self, **kwargs):
        raise KeyboardInterrupt("worker killed")


def test_a_worker_killed_mid_helm_leaves_a_start_and_no_end(db_session):
    deployment_id = _seed_deployment(db_session)
    reconciler = DeploymentReconciler(session=db_session, provisioner=_KilledMidHelm())

    with pytest.raises(KeyboardInterrupt):
        reconciler.reconcile(deployment_id)

    db_session.rollback()
    db_session.expire_all()
    release = _desired_release(db_session, deployment_id)
    # `started_at` was committed before Helm ran -- that is the whole point of
    # committing it early -- so the abandonment is visible.
    assert release.started_at is not None
    assert release.ended_at is None
    assert release.error is None

    deployment = db_session.get(DeploymentORM, deployment_id)
    assert deployment.applied_release_id is None


def test_a_lease_reclaim_re_runs_the_same_release_without_rewriting_the_start(db_session):
    deployment_id = _seed_deployment(db_session)
    with pytest.raises(KeyboardInterrupt):
        DeploymentReconciler(session=db_session, provisioner=_KilledMidHelm()).reconcile(deployment_id)
    db_session.rollback()
    db_session.expire_all()

    abandoned = _desired_release(db_session, deployment_id)
    release_id, first_started_at = abandoned.id, abandoned.started_at

    # The reclaim: a second worker picks the job up and reconciles again.
    DeploymentReconciler(session=db_session, provisioner=FakeProvisioner()).reconcile(deployment_id)

    db_session.expire_all()
    deployment = db_session.get(DeploymentORM, deployment_id)
    # The *same* release, not a new one -- the reconciler creates none.
    assert deployment.desired_release_id == release_id
    release = db_session.get(DeploymentReleaseORM, release_id)
    # When work *first* began, not when the retry did. How many attempts there
    # were is the reconcile job's `attempt` counter, not something inferred here.
    assert release.started_at == first_started_at
    assert release.ended_at is not None
    assert deployment.applied_release_id == release_id


# ---------------------------------------------------------------------------
# The delete path
# ---------------------------------------------------------------------------


def test_a_delete_does_not_claim_or_complete_the_desired_release(db_session):
    """An uninstall is not a rollout, so it must not mark the desired release
    as having been applied by one."""
    deployment_id = _seed_deployment(db_session)
    deployment = db_session.get(DeploymentORM, deployment_id)
    deployment.deleted_at = datetime.now(UTC)
    db_session.add(deployment)
    db_session.commit()

    DeploymentReconciler(session=db_session, provisioner=FakeProvisioner()).reconcile(deployment_id)

    db_session.expire_all()
    release = _desired_release(db_session, deployment_id)
    assert release.started_at is None
    assert release.ended_at is None
    assert release.status is ReleaseStatus.QUEUED
    assert db_session.get(DeploymentORM, deployment_id).applied_release_id is None


# ---------------------------------------------------------------------------
# The failed release's own output reaches the user
# ---------------------------------------------------------------------------


class _FakeLokiClient:
    def __init__(self, entries=None, raises=None):
        self.entries = entries or []
        self.raises = raises
        self.queries: list[dict] = []

    def query_range(self, *, query, start_ns, limit, direction, end_ns=None):
        self.queries.append(
            {"query": query, "start_ns": start_ns, "limit": limit, "direction": direction}
        )
        if self.raises is not None:
            raise self.raises
        return self.entries


def _install_loki(monkeypatch, client):
    monkeypatch.setattr(
        "app.services.reconcile.LokiQueryClient.from_settings",
        staticmethod(lambda *a, **k: client),
    )
    return client


def _fail_reconcile(db_session, deployment_id, error="Timed out waiting for condition"):
    provisioner = FakeProvisioner()
    provisioner.raise_on_upgrade = RuntimeError(error)
    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)
    db_session.expire_all()
    return db_session.get(DeploymentORM, deployment_id)


def test_a_failed_apply_attaches_the_applications_own_output(db_session, monkeypatch):
    """`freepod deploy` reports *why* the application refused to start without
    a second command. Only possible because the lines outlive the pod that
    `--atomic` deleted."""
    from app.services.loki import LogEntry

    deployment_id = _seed_deployment(db_session)
    loki = _install_loki(
        monkeypatch,
        _FakeLokiClient(
            entries=[
                LogEntry("1787066060000000001", "Traceback (most recent call last):", {}),
                LogEntry("1787066060000000002", "KeyError: 'DATABASE_URL'", {}),
            ]
        ),
    )

    deployment = _fail_reconcile(db_session, deployment_id)
    assert "Timed out waiting for condition" in deployment.last_error
    assert "KeyError: 'DATABASE_URL'" in deployment.last_error
    assert "Application output" in deployment.last_error
    # Newest-first, and bounded to this rollout rather than to all of history.
    assert loki.queries[0]["direction"] == "backward"
    release = _desired_release(db_session, deployment_id)
    started = release.started_at.replace(tzinfo=UTC) if release.started_at.tzinfo is None else release.started_at
    assert loki.queries[0]["start_ns"] == int(started.timestamp() * 1_000_000_000)


def _use_chart(db_session, deployment_id, chart_ref):
    deployment = db_session.get(DeploymentORM, deployment_id)
    template = db_session.get(ProductTemplateVersionORM, deployment.desired_template_id)
    template.chart_ref = chart_ref
    db_session.add(template)
    db_session.commit()


@pytest.mark.parametrize("chart", ["custom", "nextcloud"])
def test_the_tail_is_pinned_to_the_release_whatever_the_chart(db_session, monkeypatch, chart):
    """A rollout overlaps the previous release's still-running pods, so an
    unpinned query would report the wrong release's output. Every chart labels
    its application pods, so no chart falls back to the deployment."""
    from app.services.loki import LogEntry

    deployment_id = _seed_deployment(db_session)
    _use_chart(db_session, deployment_id, f"oci://registry.home/helm/{chart}")
    loki = _install_loki(
        monkeypatch, _FakeLokiClient(entries=[LogEntry("1787066060000000001", "boom", {})])
    )

    deployment = _fail_reconcile(db_session, deployment_id)
    release = _desired_release(db_session, deployment_id)
    assert f'release_id="{release.id}"' in loki.queries[0]["query"]
    assert "boom" in deployment.last_error


def test_the_tail_survives_the_400_character_truncation(db_session, monkeypatch):
    """`AdapterCommandError._build_message` cuts Helm's detail at 400
    characters while building the exception. The tail is appended after
    `str(exc)`, so it is past that cut."""
    from app.proc import AdapterCommandError, CommandResult
    from app.services.loki import LogEntry

    deployment_id = _seed_deployment(db_session)
    _install_loki(
        monkeypatch,
        _FakeLokiClient(entries=[LogEntry("1787066060000000001", "THE REAL CAUSE", {})]),
    )

    helm_noise = "x" * 2000
    provisioner = FakeProvisioner()
    provisioner.raise_on_upgrade = AdapterCommandError(
        message="helm upgrade failed",
        result=CommandResult(command=["helm", "upgrade"], returncode=1, stdout="", stderr=helm_noise),
    )
    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)

    db_session.expire_all()
    deployment = db_session.get(DeploymentORM, deployment_id)
    # Helm's own detail was truncated...
    assert "..." in deployment.last_error
    assert deployment.last_error.count("x") < 500
    # ...and the application's output still made it through.
    assert "THE REAL CAUSE" in deployment.last_error


def test_an_unavailable_log_store_does_not_replace_the_helm_error(db_session, monkeypatch):
    """The Helm error is what the user actually needs; a store that is down
    must not turn a reported failure into a different, less useful one."""
    from app.services.loki import LokiException

    deployment_id = _seed_deployment(db_session)
    _install_loki(monkeypatch, _FakeLokiClient(raises=LokiException("connection refused")))

    deployment = _fail_reconcile(db_session, deployment_id)
    assert "Timed out waiting for condition" in deployment.last_error
    assert "Application output" not in deployment.last_error


def test_a_silent_application_adds_no_empty_section(db_session, monkeypatch):
    deployment_id = _seed_deployment(db_session)
    _install_loki(monkeypatch, _FakeLokiClient(entries=[]))
    deployment = _fail_reconcile(db_session, deployment_id)
    assert "Application output" not in deployment.last_error


def test_a_successful_apply_queries_no_logs(db_session, monkeypatch):
    deployment_id = _seed_deployment(db_session)
    loki = _install_loki(monkeypatch, _FakeLokiClient(entries=[]))
    DeploymentReconciler(session=db_session, provisioner=FakeProvisioner()).reconcile(deployment_id)
    assert loki.queries == []
