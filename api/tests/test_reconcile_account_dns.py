"""The per-account wildcard DNS record the reconcile ensures.

The record is what keeps an account's applications resolving while an ACME
challenge sits beneath its name — see openspec/specs/account-dns-record/spec.md.
"""

from __future__ import annotations

import pytest
from app.config import CaelusSettings
from app.services import deployments as deployment_service
from app.services import products, templates
from app.services.dns import DnsException
from app.services.jobs import JobService
from app.services.reconcile import DeploymentReconciler
from app.services.reconcile_constants import (
    DEPLOYMENT_STATUS_ERROR,
    DEPLOYMENT_STATUS_READY,
)
from app.models import (
    BillingInterval,
    PlanORM,
    PlanTemplateVersionORM,
    ProductORM,
)
from app.models.core import _utcnow
from tests.conftest import make_accepted_user, subdomain_for
from tests.provisioner_utils import FakeProvisioner


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(
        "app.services.reconcile.get_settings",
        lambda: CaelusSettings(
            wildcard_domains=[], domain="dev.freepod.eu", _env_file=None
        ),
    )


ACCOUNT_EMAIL = "alice@example.com"
ACCOUNT_FQDN = f"{subdomain_for(ACCOUNT_EMAIL)}.dev.freepod.eu"


@pytest.fixture
def account(db_session):
    return make_accepted_user(db_session, ACCOUNT_EMAIL)


def _seed(db_session, user, *, hostname: str, suffix: str = ""):
    product = products.create_product(
        db_session, payload=products.ProductCreate(name=f"dns-product{suffix}", description="d")
    )
    template = templates.create_template(
        db_session,
        payload=templates.ProductTemplateVersionCreate(
            product_id=product.id,
            chart_ref="oci://example/chart",
            chart_version="1.0.0",
            system_values_json={"replicas": 1},
            values_schema_json={
                "type": "object",
                "properties": {
                    "user": {
                        "type": "object",
                        "properties": {"domain": {"type": "string", "title": "hostname"}},
                        "additionalProperties": False,
                    }
                },
                "additionalProperties": False,
            },
        ),
    )
    product_orm = db_session.get(ProductORM, product.id)
    product_orm.template_id = template.id
    db_session.add(product_orm)
    db_session.commit()

    plan = PlanORM(name=f"plan{suffix}", product_id=product.id, created_at=_utcnow())
    db_session.add(plan)
    db_session.flush()
    ptv = PlanTemplateVersionORM(
        plan_id=plan.id,
        price_cents=0,
        billing_interval=BillingInterval.MONTHLY,
        storage_bytes=0,
        created_at=_utcnow(),
    )
    db_session.add(ptv)
    db_session.flush()
    plan.template_id = ptv.id
    db_session.commit()

    return deployment_service.create_deployment(
        db_session,
        payload=deployment_service.DeploymentCreate(
            user_id=user.id,
            desired_template_id=template.id,
            user_values_json={"user": {"domain": hostname}},
            plan_template_id=ptv.id,
        ),
    ).deployment.id


def _reconcile(db_session, deployment_id, monkeypatch):
    monkeypatch.setattr("app.services.reconcile.default_provisioner", FakeProvisioner())
    return DeploymentReconciler(session=db_session).reconcile(deployment_id)


def test_first_deployment_creates_the_accounts_wildcard(
    db_session, account, fake_dns, monkeypatch
):
    deployment_id = _seed(db_session, account, hostname="app.dev.freepod.eu")
    result = _reconcile(db_session, deployment_id, monkeypatch)

    assert result.status == DEPLOYMENT_STATUS_READY
    assert fake_dns.ensured == [ACCOUNT_FQDN]
    assert fake_dns.records == {f"*.{ACCOUNT_FQDN}"}


def test_the_bare_account_name_gets_no_record(db_session, account, fake_dns, monkeypatch):
    """One record per account is what the zone's record limit buys."""
    deployment_id = _seed(db_session, account, hostname="app.dev.freepod.eu")
    _reconcile(db_session, deployment_id, monkeypatch)

    assert ACCOUNT_FQDN not in fake_dns.records


def test_a_second_deployment_adds_nothing(db_session, account, fake_dns, monkeypatch):
    first_id = _seed(db_session, account, hostname="one.dev.freepod.eu")
    _reconcile(db_session, first_id, monkeypatch)
    second_id = _seed(db_session, account, hostname="two.dev.freepod.eu", suffix="-2")
    _reconcile(db_session, second_id, monkeypatch)

    assert fake_dns.records == {f"*.{ACCOUNT_FQDN}"}


def test_deleting_the_last_deployment_leaves_the_record(
    db_session, account, fake_dns, monkeypatch
):
    deployment_id = _seed(db_session, account, hostname="app.dev.freepod.eu")
    _reconcile(db_session, deployment_id, monkeypatch)
    before = set(fake_dns.records)

    jobs = JobService(db_session)
    for job in jobs.list_jobs(deployment_id=deployment_id, statuses=["queued", "running"]):
        jobs.mark_job_done(job_id=job.id)
    deployment_service.delete_deployment(
        db_session, deployment_id=deployment_id, user_id=account.id
    )
    _reconcile(db_session, deployment_id, monkeypatch)

    assert fake_dns.records == before


def test_a_dns_failure_fails_the_deployment_and_is_recorded(
    db_session, account, fake_dns, monkeypatch
):
    deployment_id = _seed(db_session, account, hostname="app.dev.freepod.eu")
    fake_dns.fail_with = DnsException("Could not create DNS record: provider unavailable")

    result = _reconcile(db_session, deployment_id, monkeypatch)

    assert result.status == DEPLOYMENT_STATUS_ERROR
    assert "provider unavailable" in result.last_error


def test_a_dns_failure_leaves_a_later_reconcile_able_to_retry(
    db_session, account, fake_dns, monkeypatch
):
    deployment_id = _seed(db_session, account, hostname="app.dev.freepod.eu")
    fake_dns.fail_with = DnsException("provider unavailable")
    assert _reconcile(db_session, deployment_id, monkeypatch).status == DEPLOYMENT_STATUS_ERROR

    fake_dns.fail_with = None
    result = _reconcile(db_session, deployment_id, monkeypatch)

    assert result.status == DEPLOYMENT_STATUS_READY
    assert fake_dns.records == {f"*.{ACCOUNT_FQDN}"}


def test_the_record_precedes_the_helm_release(db_session, account, fake_dns, monkeypatch):
    """Ordering the certificate work depends on: nothing is installed for an
    account whose name cannot be made to resolve."""
    provisioner = FakeProvisioner()
    monkeypatch.setattr("app.services.reconcile.default_provisioner", provisioner)
    deployment_id = _seed(db_session, account, hostname="app.dev.freepod.eu")
    fake_dns.fail_with = DnsException("provider unavailable")

    DeploymentReconciler(session=db_session).reconcile(deployment_id)

    assert [name for name, _ in provisioner.calls if name == "helm_upgrade_install"] == []
