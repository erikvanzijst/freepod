"""Subject identity, and where attribution comes from."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

import pytest
from sqlmodel import select

from app.models import (
    DeploymentORM,
    ProductORM,
    ProductTemplateVersionORM,
    UsageSampleORM,
    UsageSubjectORM,
    UserORM,
)
from app.models.usage import SubjectKind
from app.services.usage.opencost import Allocation
from app.services.usage.subjects import (
    UNRESOLVED,
    is_degraded,
    resolve_subjects,
    subject_ref,
    upsert_subject,
)
from tests.conftest import make_deployment_with_release

OBSERVED = datetime(2026, 9, 23, 11, 5)


def _allocation(
    namespace="tenant-ns",
    controller_kind="deployment",
    controller="app-abc123",
    container="main",
    **kwargs,
) -> Allocation:
    return Allocation(
        namespace=namespace,
        controller_kind=controller_kind,
        controller=controller,
        container=container,
        window_start=datetime(2026, 9, 23, 10),
        window_end=datetime(2026, 9, 23, 11),
        minutes=Decimal(60),
        fields={"cpuCoreHours": Decimal("0.05")},
        **kwargs,
    )


@pytest.fixture
def tenant(db_session):
    """A deployment in its own namespace, as the reconciler would have made it."""
    user = UserORM(email="owner@example.com")
    product = ProductORM(name="bookstack")
    db_session.add(user)
    db_session.add(product)
    db_session.commit()
    template = ProductTemplateVersionORM(
        product_id=product.id,
        chart_ref="oci://example/bookstack",
        chart_version="1.0.0",
        values_schema_json={},
    )
    db_session.add(template)
    db_session.commit()
    deployment = make_deployment_with_release(
        db_session,
        user_id=user.id,
        desired_template_id=template.id,
        name="books",
        namespace="tenant-ns",
    )
    db_session.commit()
    return deployment


# identity


def test_the_reference_names_namespace_kind_controller_and_container():
    assert subject_ref(_allocation()) == "tenant-ns/deployment/app-abc123/main"


def test_pod_restarts_map_to_one_subject(db_session):
    """Pod names churn; the controller does not. Nothing here reads the pod."""
    first = _allocation()
    after_restart = _allocation()
    assert subject_ref(first) == subject_ref(after_restart)

    subjects = resolve_subjects(db_session, [first, after_restart], observed_at=OBSERVED)
    db_session.commit()
    assert len(subjects) == 1
    assert len(db_session.exec(select(UsageSubjectORM)).all()) == 1


def test_a_rollout_does_not_fragment_a_subject(db_session):
    """OpenCost collapses ReplicaSet to Deployment, so no pod-template hash appears."""
    before = _allocation(controller="bookstack-8d56q1-bookstack")
    after = _allocation(controller="bookstack-8d56q1-bookstack")
    resolve_subjects(db_session, [before, after], observed_at=OBSERVED)
    db_session.commit()
    assert len(db_session.exec(select(UsageSubjectORM)).all()) == 1


def test_two_containers_of_one_deployment_are_separate_subjects(db_session):
    """The immich case: two containers named `main` under different controllers."""
    server = _allocation(controller="immich-server", container="main")
    ml = _allocation(controller="immich-machine-learning", container="main")
    subjects = resolve_subjects(db_session, [server, ml], observed_at=OBSERVED)
    db_session.commit()
    assert len(subjects) == 2


def test_a_sidecar_is_its_own_subject(db_session):
    app = _allocation(container="main")
    ssh = _allocation(container="ssh")
    assert subject_ref(app) != subject_ref(ssh)
    assert len(resolve_subjects(db_session, [app, ssh], observed_at=OBSERVED)) == 2


# attribution


def test_a_tenant_namespace_resolves_to_its_deployment(db_session, tenant):
    resolve_subjects(db_session, [_allocation()], observed_at=OBSERVED)
    db_session.commit()
    subject = db_session.exec(select(UsageSubjectORM)).one()
    assert subject.deployment_id == tenant.id
    assert subject.namespace == "tenant-ns"


def test_a_platform_namespace_is_recorded_with_no_deployment(db_session):
    """Unattributed overhead is measurable rather than invisible."""
    resolve_subjects(
        db_session, [_allocation(namespace="monitoring")], observed_at=OBSERVED
    )
    db_session.commit()
    subject = db_session.exec(select(UsageSubjectORM)).one()
    assert subject.deployment_id is None
    assert subject.namespace == "monitoring"


def test_an_unknown_namespace_is_recorded_with_no_deployment(db_session):
    resolve_subjects(
        db_session, [_allocation(namespace="who-is-this")], observed_at=OBSERVED
    )
    db_session.commit()
    assert db_session.exec(select(UsageSubjectORM)).one().deployment_id is None


def test_attribution_survives_the_deployment_being_deleted(db_session, tenant):
    """Its row persists, so a past period stays attributable."""
    resolve_subjects(db_session, [_allocation()], observed_at=OBSERVED)
    db_session.commit()

    tenant.status = "deleted"
    tenant.deleted_at = OBSERVED
    db_session.add(tenant)
    db_session.commit()

    resolve_subjects(db_session, [_allocation()], observed_at=OBSERVED)
    db_session.commit()
    assert db_session.exec(select(UsageSubjectORM)).one().deployment_id == tenant.id


# backfill


def test_a_later_resolving_namespace_is_backfilled(db_session):
    """Subjects may be updated as attribution improves."""
    resolve_subjects(db_session, [_allocation()], observed_at=OBSERVED)
    db_session.commit()
    assert db_session.exec(select(UsageSubjectORM)).one().deployment_id is None

    user = UserORM(email="late@example.com")
    product = ProductORM(name="late")
    db_session.add(user)
    db_session.add(product)
    db_session.commit()
    template = ProductTemplateVersionORM(
        product_id=product.id,
        chart_ref="oci://example/late",
        chart_version="1.0.0",
        values_schema_json={},
    )
    db_session.add(template)
    db_session.commit()
    deployment = make_deployment_with_release(
        db_session,
        user_id=user.id,
        desired_template_id=template.id,
        name="late",
        namespace="tenant-ns",
    )
    db_session.commit()

    resolve_subjects(db_session, [_allocation()], observed_at=OBSERVED)
    db_session.commit()
    assert db_session.exec(select(UsageSubjectORM)).one().deployment_id == deployment.id


def test_a_backfill_leaves_samples_untouched(db_session, tenant):
    from app.services.usage import ledger
    from app.services.usage.ledger import SampleRow
    from tests.usage_fixtures import CATALOG
    from app.models import UsageMetricORM

    for name, axis, unit, kind, role in CATALOG:
        db_session.add(
            UsageMetricORM(name=name, axis=axis, unit=unit, kind=kind, role=role)
        )
    db_session.commit()

    subjects = resolve_subjects(db_session, [_allocation()], observed_at=OBSERVED)
    subject_id = next(iter(subjects.values()))
    ledger.record_samples(
        db_session,
        [
            SampleRow(
                subject_id=subject_id,
                metric="cpu_core_hours",
                window_start=datetime(2026, 9, 23, 10),
                interval_seconds=3600,
                value=Decimal("0.05"),
            )
        ],
        observed_at=OBSERVED,
    )
    db_session.commit()
    before = db_session.exec(select(UsageSampleORM)).one()
    recorded = (before.value, before.observed_at, before.window_start)

    resolve_subjects(db_session, [_allocation()], observed_at=datetime(2026, 9, 24, 9))
    db_session.commit()

    after = db_session.exec(select(UsageSampleORM)).one()
    assert (after.value, after.observed_at, after.window_start) == recorded


def test_a_resolved_deployment_is_never_cleared(db_session, tenant):
    """A later window that fails to resolve must not undo the attribution."""
    from app.services.usage.subjects import upsert_subject

    resolve_subjects(db_session, [_allocation()], observed_at=OBSERVED)
    db_session.commit()
    ref = subject_ref(_allocation())
    assert db_session.exec(select(UsageSubjectORM)).one().deployment_id == tenant.id

    upsert_subject(
        db_session,
        ref=ref,
        namespace="tenant-ns",
        deployment_id=None,
        observed_at=datetime(2026, 9, 24, 9),
    )
    db_session.commit()

    subject = db_session.exec(select(UsageSubjectORM)).one()
    assert subject.deployment_id == tenant.id
    assert subject.last_seen_at == datetime(2026, 9, 24, 9)


def test_a_deployment_with_recorded_usage_cannot_be_hard_deleted(db_session, tenant):
    """The foreign key is what makes attribution survive deletion.

    The platform soft-deletes, so this is a guard rather than a workflow: anything
    that later wants to purge deployment rows has to deal with the ledger first.
    """
    from sqlalchemy.exc import IntegrityError

    resolve_subjects(db_session, [_allocation()], observed_at=OBSERVED)
    db_session.commit()

    db_session.delete(tenant)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# degraded subjects


def test_an_unresolved_controller_is_recorded_not_skipped(db_session, tenant):
    degraded = _allocation(controller_kind=None, controller=None)
    assert subject_ref(degraded) == f"tenant-ns/{UNRESOLVED}/{UNRESOLVED}/main"

    resolve_subjects(db_session, [degraded], observed_at=OBSERVED)
    db_session.commit()
    subject = db_session.exec(select(UsageSubjectORM)).one()
    assert subject.deployment_id == tenant.id, "still billed to its owner"


def test_a_degraded_subject_is_distinguishable_from_a_resolved_one(db_session, tenant):
    resolved = _allocation()
    degraded = _allocation(controller_kind=None, controller=None)
    resolve_subjects(db_session, [resolved, degraded], observed_at=OBSERVED)
    db_session.commit()

    refs = {s.ref for s in db_session.exec(select(UsageSubjectORM)).all()}
    assert len(refs) == 2
    assert sum(is_degraded(ref) for ref in refs) == 1


def test_a_degraded_period_is_queryable_from_the_ledger_alone(db_session, tenant):
    """The proportion collected in a degraded state must be determinable."""
    resolve_subjects(
        db_session,
        [
            _allocation(container="a"),
            _allocation(container="b"),
            _allocation(container="c", controller_kind=None, controller=None),
        ],
        observed_at=OBSERVED,
    )
    db_session.commit()
    refs = [s.ref for s in db_session.exec(select(UsageSubjectORM)).all()]
    assert sum(is_degraded(r) for r in refs) == 1
    assert len(refs) == 3


def test_the_vendor_token_never_reaches_the_ledger(db_session):
    """`__unallocated__` is translated at the boundary, so a rename cannot reach us."""
    resolve_subjects(
        db_session,
        [_allocation(controller_kind=None, controller=None)],
        observed_at=OBSERVED,
    )
    db_session.commit()
    assert "__unallocated__" not in db_session.exec(select(UsageSubjectORM)).one().ref


# concurrency


def test_resolving_the_same_subject_twice_yields_one_row(db_session):
    first = resolve_subjects(db_session, [_allocation()], observed_at=OBSERVED)
    db_session.commit()
    second = resolve_subjects(db_session, [_allocation()], observed_at=OBSERVED)
    db_session.commit()
    assert first == second
    assert len(db_session.exec(select(UsageSubjectORM)).all()) == 1


# other subject kinds


def test_a_build_subject_is_distinct_from_a_container_with_the_same_ref(db_session, tenant):
    """Kind is part of the identity, so a build's id can never collide with a
    container reference."""
    build = upsert_subject(
        db_session,
        kind=SubjectKind.BUILD,
        ref="same-ref",
        namespace="caelus-builds",
        deployment_id=tenant.id,
        observed_at=OBSERVED,
    )
    container = upsert_subject(
        db_session, ref="same-ref", namespace="tenant-ns", observed_at=OBSERVED
    )
    db_session.commit()

    assert build != container
    subject = db_session.get(UsageSubjectORM, build)
    assert (subject.kind, subject.deployment_id) == (SubjectKind.BUILD, tenant.id)
