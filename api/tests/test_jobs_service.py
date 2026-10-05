from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from app.models import DeploymentReconcileJobORM, ProductORM
from app.services import deployments, products, templates, users
from app.services.jobs import JobService
from app.services.errors import DeploymentInProgressException, NotFoundException
from tests.conftest import create_free_plan_template, make_accepted_user


def _seed_deployment(db_session, *, token: str = "jobs"):
    user = make_accepted_user(db_session, f"{token}-user@example.com")
    product = products.create_product(
        db_session,
        payload=products.ProductCreate(name=f"{token}-product", description=f"{token} desc"),
    )
    template = templates.create_template(
        db_session,
        payload=templates.ProductTemplateVersionCreate(
            product_id=product.id,
            chart_ref="oci://example/chart",
            chart_version="1.0.0",
            values_schema_json={
                "type": "object",
                "additionalProperties": False,
                "properties": {"domain": {"type": "string", "title": "hostname"}},
            },
        ),
    )
    product_orm = db_session.get(ProductORM, product.id)
    product_orm.template_id = template.id
    db_session.add(product_orm)
    db_session.commit()
    ptv_id = create_free_plan_template(db_session, product.id)
    deployment = deployments.create_deployment(
        db_session,
        payload=deployments.DeploymentCreate(
            user_id=user.id,
            desired_template_id=template.id,
            user_values_json={"domain": f"{token}.example.test"},
            plan_template_id=ptv_id,
        ),
    ).deployment
    return deployment.id


def _first_open_job_id(db_session, deployment_id: int) -> int:
    job = db_session.exec(
        select(DeploymentReconcileJobORM)
        .where(
            DeploymentReconcileJobORM.deployment_id == deployment_id,
            DeploymentReconcileJobORM.status.in_(("queued", "running")),
        )
        .order_by(DeploymentReconcileJobORM.id)
    ).first()
    assert job is not None
    return job.id


def test_enqueue_and_list_jobs_with_filters(db_session):
    jobs = JobService(db_session)
    deployment_id = _seed_deployment(db_session)
    jobs.mark_job_done(job_id=_first_open_job_id(db_session, deployment_id))

    first = jobs.enqueue_job(deployment_id=deployment_id, reason="update")
    jobs.mark_job_done(job_id=first.id)
    second = jobs.enqueue_job(
        deployment_id=deployment_id,
        reason="update",
        run_after=datetime.now(UTC) + timedelta(seconds=60),
    )

    listed_all = jobs.list_jobs(deployment_id=deployment_id, limit=20)
    assert len(listed_all) >= 3
    assert any(job.id == first.id for job in listed_all)
    assert any(job.id == second.id for job in listed_all)

    queued_only = jobs.list_jobs(deployment_id=deployment_id, statuses=["queued"], limit=20)
    assert all(job.status == "queued" for job in queued_only)


def test_claim_next_job_claims_one_then_reports_an_empty_queue(db_session):
    jobs = JobService(db_session)
    deployment_id = _seed_deployment(db_session)
    claimed = jobs.claim_next_job(worker_id="worker-a")
    assert claimed is not None
    assert claimed.deployment_id == deployment_id
    assert claimed.status == "running"
    assert claimed.locked_by == "worker-a"
    assert claimed.locked_at is not None

    jobs.mark_job_done(job_id=claimed.id)
    while True:
        next_job = jobs.claim_next_job(worker_id="worker-b")
        if next_job is None:
            break
        jobs.mark_job_done(job_id=next_job.id)

    assert jobs.claim_next_job(worker_id="worker-c") is None


def test_mark_job_done_and_fail_paths(db_session):
    jobs = JobService(db_session)
    deployment_id = _seed_deployment(db_session)
    claimed_seed = jobs.claim_next_job(worker_id="seed-worker")
    assert claimed_seed is not None
    jobs.mark_job_done(job_id=claimed_seed.id)

    job = jobs.enqueue_job(deployment_id=deployment_id, reason="update")
    claimed = jobs.claim_next_job(worker_id="worker-1")
    assert claimed is not None
    assert claimed.id == job.id

    failed = jobs.mark_job_failed(job_id=claimed.id, error="fatal")
    assert failed.status == "failed"
    assert failed.last_error == "fatal"
    assert failed.locked_by is None

    another = jobs.enqueue_job(deployment_id=deployment_id, reason="update")
    done = jobs.mark_job_done(job_id=another.id)
    assert done.status == "done"
    assert done.last_error is None


def test_not_found_paths_raise(db_session):
    jobs = JobService(db_session)
    with pytest.raises(NotFoundException):
        jobs.mark_job_done(job_id=999999)
    with pytest.raises(NotFoundException):
        jobs.mark_job_failed(job_id=999999, error="x")


def test_dedupe_open_jobs_removes_duplicates(db_session):
    jobs = JobService(db_session)
    deployment_id = _seed_deployment(db_session)
    with pytest.raises(DeploymentInProgressException):
        jobs.enqueue_job(deployment_id=deployment_id, reason="update")
    db_session.rollback()
    removed = jobs.dedupe_open_jobs(deployment_id=deployment_id)
    assert removed == 0
    remaining_open = jobs.list_jobs(deployment_id=deployment_id, statuses=["queued"], limit=20)
    assert len(remaining_open) == 1


def test_list_jobs_multi_status_applies_global_limit_and_order(db_session):
    jobs = JobService(db_session)
    deployment_id = _seed_deployment(db_session)

    seed_job_id = _first_open_job_id(db_session, deployment_id)
    jobs.mark_job_done(job_id=seed_job_id)

    first = jobs.enqueue_job(deployment_id=deployment_id, reason="update")
    jobs.mark_job_done(job_id=first.id)
    second = jobs.enqueue_job(deployment_id=deployment_id, reason="update")

    listed = jobs.list_jobs(
        deployment_id=deployment_id,
        statuses=["done", "queued"],
        limit=2,
    )

    assert len(listed) == 2
    assert [job.id for job in listed] == [seed_job_id, first.id]
    assert [job.status for job in listed] == ["done", "done"]
    assert all(job.id != second.id for job in listed)


# ── Lease expiry ─────────────────────────────────────────────────────────────
# A worker that dies mid-reconcile (pod restart, OOM kill, eviction) strands its
# job at status='running' with locked_by naming a process that never comes back.
# The tests below cover the lease that lets a healthy worker take that work
# back.


def _strand_job(db_session, job_id: int, *, worker_id: str, age: timedelta) -> None:
    """Backdate a claimed job's lease to simulate a worker that died holding it."""
    job = db_session.get(DeploymentReconcileJobORM, job_id)
    job.locked_by = worker_id
    job.locked_at = datetime.now(UTC) - age
    db_session.add(job)
    db_session.commit()


def _set_run_after(db_session, job, *, age: timedelta) -> None:
    job.run_after = datetime.now(UTC) - age
    db_session.add(job)
    db_session.commit()


def _open_job_for(db_session, deployment_id):
    return db_session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == deployment_id
        )
    ).one()


def test_default_lease_leaves_headroom_over_the_helm_timeout():
    """The lease must never be tuned below Helm's own wall-clock budget.

    A lease shorter than HELM_TIMEOUT_SEC would let a second worker steal a job
    from a live worker that is legitimately waiting on ``helm upgrade --wait``.
    """
    from app.config import CaelusSettings
    from app.services.reconcile import HELM_TIMEOUT_SEC

    lease_seconds = CaelusSettings(_env_file=None).reconcile_job_lease_seconds
    assert lease_seconds == 600
    assert lease_seconds >= 2 * HELM_TIMEOUT_SEC


def test_expired_lease_is_reclaimed_and_bumps_attempt(db_session, caplog):
    jobs = JobService(db_session)
    deployment_id = _seed_deployment(db_session)

    claimed = jobs.claim_next_job(worker_id="worker-dead")
    assert claimed is not None
    assert claimed.attempt == 0
    _strand_job(db_session, claimed.id, worker_id="worker-dead", age=timedelta(minutes=30))

    with caplog.at_level("WARNING", logger="app.services.jobs"):
        reclaimed = jobs.claim_next_job(worker_id="worker-live")

    assert reclaimed is not None
    assert reclaimed.id == claimed.id
    assert reclaimed.deployment_id == deployment_id
    assert reclaimed.status == "running"
    assert reclaimed.locked_by == "worker-live"
    assert reclaimed.locked_at is not None
    # Reclaims are counted so a job stuck in a crash loop is evident from the
    # row itself, not only from the logs.
    assert reclaimed.attempt == 1

    messages = [record.getMessage() for record in caplog.records]
    reclaim_logs = [m for m in messages if "Reclaimed expired reconcile job lease" in m]
    assert len(reclaim_logs) == 1, messages
    assert "worker_id=worker-live" in reclaim_logs[0]
    assert "previous_locked_by=worker-dead" in reclaim_logs[0]
    assert "previous_locked_at=" in reclaim_logs[0]

    # A second expiry keeps retrying rather than giving up: only a completed
    # reconcile can move the deployment out of provisioning/deleting.
    _strand_job(db_session, reclaimed.id, worker_id="worker-live", age=timedelta(minutes=30))
    again = jobs.claim_next_job(worker_id="worker-live-2")
    assert again is not None
    assert again.id == claimed.id
    assert again.attempt == 2


def test_fresh_lease_is_not_reclaimed(db_session):
    jobs = JobService(db_session)
    _seed_deployment(db_session)

    claimed = jobs.claim_next_job(worker_id="worker-busy")
    assert claimed is not None

    # Just claimed: nobody else may touch it.
    assert jobs.claim_next_job(worker_id="worker-thief") is None

    # Still inside the lease window (a slow but healthy Helm wait).
    _strand_job(db_session, claimed.id, worker_id="worker-busy", age=timedelta(minutes=9))
    assert jobs.claim_next_job(worker_id="worker-thief") is None

    still_owned = db_session.get(DeploymentReconcileJobORM, claimed.id)
    assert still_owned.locked_by == "worker-busy"
    assert still_owned.attempt == 0


def test_lease_interval_is_configurable(db_session, monkeypatch):
    from app.config import CaelusSettings

    jobs = JobService(db_session)
    _seed_deployment(db_session)
    claimed = jobs.claim_next_job(worker_id="worker-busy")
    assert claimed is not None
    _strand_job(db_session, claimed.id, worker_id="worker-busy", age=timedelta(minutes=2))

    # Default 10 minute lease: two minutes in, the job is still owned.
    assert jobs.claim_next_job(worker_id="worker-thief") is None

    short_lease = CaelusSettings(reconcile_job_lease_seconds=60, _env_file=None)
    monkeypatch.setattr("app.services.jobs.get_settings", lambda: short_lease)
    reclaimed = jobs.claim_next_job(worker_id="worker-thief")
    assert reclaimed is not None
    assert reclaimed.id == claimed.id
    assert reclaimed.locked_by == "worker-thief"


def test_running_job_without_locked_at_is_reclaimable(db_session):
    """A running row with no lease at all can only be corruption; don't strand it."""
    jobs = JobService(db_session)
    _seed_deployment(db_session)

    claimed = jobs.claim_next_job(worker_id="worker-dead")
    assert claimed is not None
    job = db_session.get(DeploymentReconcileJobORM, claimed.id)
    job.locked_at = None
    db_session.add(job)
    db_session.commit()

    reclaimed = jobs.claim_next_job(worker_id="worker-live")
    assert reclaimed is not None
    assert reclaimed.id == claimed.id
    assert reclaimed.locked_by == "worker-live"


def test_expired_lease_is_served_before_a_newer_queued_job(db_session):
    """Reclaimed work rejoins the queue on run_after; it is not sent to the back."""
    jobs = JobService(db_session)
    stranded_deployment = _seed_deployment(db_session, token="stranded")
    queued_deployment = _seed_deployment(db_session, token="queued")

    stranded = jobs.claim_next_job(worker_id="worker-dead")
    assert stranded is not None
    assert stranded.deployment_id == stranded_deployment
    queued = _open_job_for(db_session, queued_deployment)

    _set_run_after(db_session, stranded, age=timedelta(hours=2))
    _set_run_after(db_session, queued, age=timedelta(hours=1))
    _strand_job(db_session, stranded.id, worker_id="worker-dead", age=timedelta(minutes=30))

    first = jobs.claim_next_job(worker_id="worker-1")
    assert first is not None and first.id == stranded.id
    second = jobs.claim_next_job(worker_id="worker-2")
    assert second is not None and second.id == queued.id


def test_older_queued_job_is_served_before_an_expired_lease(db_session):
    """An expired lease does not jump the queue either; oldest run_after wins."""
    jobs = JobService(db_session)
    stranded_deployment = _seed_deployment(db_session, token="stranded")
    queued_deployment = _seed_deployment(db_session, token="queued")

    stranded = jobs.claim_next_job(worker_id="worker-dead")
    assert stranded is not None
    assert stranded.deployment_id == stranded_deployment
    queued = _open_job_for(db_session, queued_deployment)

    _set_run_after(db_session, stranded, age=timedelta(hours=1))
    _set_run_after(db_session, queued, age=timedelta(hours=3))
    _strand_job(db_session, stranded.id, worker_id="worker-dead", age=timedelta(minutes=30))

    first = jobs.claim_next_job(worker_id="worker-1")
    assert first is not None and first.id == queued.id
    second = jobs.claim_next_job(worker_id="worker-2")
    assert second is not None and second.id == stranded.id


def test_stale_worker_cannot_complete_a_job_it_no_longer_owns(db_session, caplog):
    """A wedged worker waking up must not clobber the new owner's result."""
    jobs = JobService(db_session)
    _seed_deployment(db_session)

    stale = jobs.claim_next_job(worker_id="worker-wedged")
    assert stale is not None
    _strand_job(db_session, stale.id, worker_id="worker-wedged", age=timedelta(minutes=30))
    reclaimed = jobs.claim_next_job(worker_id="worker-live")
    assert reclaimed is not None and reclaimed.locked_by == "worker-live"

    with caplog.at_level("WARNING", logger="app.services.jobs"):
        ignored = jobs.mark_job_done(job_id=stale.id, worker_id="worker-wedged")

    assert ignored.status == "running"
    assert ignored.locked_by == "worker-live"
    assert any(
        "Refusing to mark reconcile job" in record.getMessage() for record in caplog.records
    ), [record.getMessage() for record in caplog.records]

    # Same for the failure path.
    still_running = jobs.mark_job_failed(
        job_id=stale.id, error="stale boom", worker_id="worker-wedged"
    )
    assert still_running.status == "running"
    assert still_running.last_error is None

    # The worker that actually holds the lease still wins.
    done = jobs.mark_job_done(job_id=stale.id, worker_id="worker-live")
    assert done.status == "done"
    assert done.locked_by is None


def test_mark_job_without_worker_id_stays_unconditional(db_session):
    """Admin/CLI callers that pass no worker id keep the old unguarded behavior."""
    jobs = JobService(db_session)
    _seed_deployment(db_session)

    claimed = jobs.claim_next_job(worker_id="worker-a")
    assert claimed is not None
    failed = jobs.mark_job_failed(job_id=claimed.id, error="boom")
    assert failed.status == "failed"
    assert failed.last_error == "boom"
    assert failed.locked_by is None


# ── Concurrency ────────────────────────────────────────────────────────────
# Everything above drives the claim from one session. `FOR UPDATE SKIP LOCKED`
# only earns its keep under real parallelism, which needs its own engine-level
# seeding rather than the per-test session.


def _seed_deployments_on_engine(engine, *, count: int) -> None:
    """`count` deployments, and therefore `count` queued create jobs."""
    token = uuid4().hex[:8]
    with Session(engine) as session:
        user = make_accepted_user(session, f"par-user-{token}@example.com")
        product = products.create_product(
            session,
            payload=products.ProductCreate(name=f"par-product-{token}", description="desc"),
        )
        template = templates.create_template(
            session,
            payload=templates.ProductTemplateVersionCreate(
                product_id=product.id,
                chart_ref="oci://example/chart",
                chart_version="1.0.0",
                values_schema_json={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"domain": {"type": "string", "title": "hostname"}},
                },
            ),
        )
        product_orm = session.get(ProductORM, product.id)
        product_orm.template_id = template.id
        session.add(product_orm)
        session.commit()

        # One queued "create" job per deployment: `uq_open_reconcile_job_per_
        # deployment` permits only one open job at a time, so N claimable jobs
        # means N deployments, not N jobs on one.
        plan_template_id = create_free_plan_template(session, product.id)
        for n in range(count):
            deployments.create_deployment(
                session,
                payload=deployments.DeploymentCreate(
                    user_id=user.id,
                    desired_template_id=template.id,
                    user_values_json={"domain": f"par-{token}-{n}.example.test"},
                    plan_template_id=plan_template_id,
                ),
            )


def _claim_once(engine, worker_id: str) -> int | None:
    with Session(engine) as session:
        job = JobService(session).claim_next_job(worker_id=worker_id)
        return None if job is None else job.id


def test_claim_next_job_never_double_claims_under_parallel_workers(
    test_database, db_session
):
    """Sixteen workers, eight jobs: every job claimed exactly once."""
    engine = test_database.engine
    expected_claims = 8
    _seed_deployments_on_engine(engine, count=expected_claims)

    worker_ids = [f"par-worker-{i}" for i in range(16)]
    with ThreadPoolExecutor(max_workers=16) as executor:
        claimed_ids = list(executor.map(lambda w: _claim_once(engine, w), worker_ids))

    non_null_claims = [job_id for job_id in claimed_ids if job_id is not None]
    assert len(non_null_claims) == expected_claims
    assert len(set(non_null_claims)) == expected_claims
