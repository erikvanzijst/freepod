"""The one-off move from `<app>.<handle>.<domain>` to `<app>-<handle>.<tenant_domain>`."""

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlmodel import select

from app.config import CaelusSettings
from app.models import (
    DeploymentORM,
    DeploymentReconcileJobORM,
    DeploymentReleaseORM,
    ProductORM,
    ProductTemplateVersionORM,
    UserORM,
)
from app.services.reconcile_constants import DEPLOYMENT_STATUS_PROVISIONING, DEPLOYMENT_STATUS_READY
from tests.conftest import make_deployment_with_release

_SPEC = importlib.util.spec_from_file_location(
    "migrate_tenant_hostnames",
    Path(__file__).resolve().parent.parent / "scripts" / "migrate_tenant_hostnames.py",
)
migrate = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = migrate
_SPEC.loader.exec_module(migrate)

SETTINGS = CaelusSettings(
    domain="freepod.eu",
    tenant_domain="freepod.app",
    platform_domains=["freepod.eu", "freepod.app"],
    environment="prod",
    _env_file=None,
)

SCHEMA = {
    "type": "object",
    "properties": {
        "ingress": {
            "type": "object",
            "properties": {"host": {"type": "string", "title": "hostname"}},
        },
        "public": {"type": "object", "properties": {"url": {"type": "string", "title": "Hostname"}}},
        "other": {"type": "string"},
    },
}


@pytest.fixture(autouse=True)
def tenant_settings(monkeypatch):
    # The update the script makes is validated by the hostname rules as deployed.
    monkeypatch.setattr(
        "app.services.hostnames.get_settings",
        lambda: CaelusSettings(**{**SETTINGS.model_dump(), "domain": ""}, _env_file=None),
    )


@pytest.fixture
def seed(db_session):
    product = ProductORM(name="migrate-product")
    db_session.add(product)
    db_session.flush()
    template = ProductTemplateVersionORM(
        product_id=product.id,
        chart_ref="oci://example/chart",
        chart_version="1.0.0",
        values_schema_json=SCHEMA,
    )
    db_session.add(template)
    db_session.flush()

    def deploy(email, handle, hostname, *, status=DEPLOYMENT_STATUS_READY, name):
        user = db_session.exec(select(UserORM).where(UserORM.email == email)).first()
        if user is None:
            user = UserORM(email=email, handle=handle)
            db_session.add(user)
            db_session.flush()
        deployment = make_deployment_with_release(
            db_session,
            user_id=user.id,
            desired_template_id=template.id,
            hostname=hostname,
            user_values_json={
                "ingress": {"host": hostname},
                "public": {"url": hostname},
                "other": hostname,
            },
            status=status,
            name=name,
            namespace=name,
        )
        db_session.commit()
        return deployment.id

    return deploy


def test_a_dry_run_plans_and_changes_nothing(db_session, seed):
    dep = seed("alice@example.com", "alice", "photos.alice.freepod.eu", name="photos")
    lines = []

    moves = migrate.run(db_session, settings=SETTINGS, dry_run=True, out=lines.append)

    assert [(m.old, m.new) for m in moves] == [("photos.alice.freepod.eu", "photos-alice.freepod.app")]
    assert db_session.get(DeploymentORM, dep).hostname == "photos.alice.freepod.eu"
    assert db_session.exec(select(DeploymentReconcileJobORM)).all() == []


def test_apply_rewrites_every_hostname_path_and_queues_a_reconcile(db_session, seed):
    dep = seed("alice@example.com", "alice", "photos.alice.freepod.eu", name="photos")

    migrate.run(db_session, settings=SETTINGS, dry_run=False, out=lambda _l: None)

    db_session.expire_all()
    row = db_session.get(DeploymentORM, dep)
    assert row.hostname == "photos-alice.freepod.app"
    assert row.status == DEPLOYMENT_STATUS_PROVISIONING
    assert row.user_values_json == {
        "ingress": {"host": "photos-alice.freepod.app"},
        "public": {"url": "photos-alice.freepod.app"},
        "other": "photos.alice.freepod.eu",
    }
    releases = db_session.exec(
        select(DeploymentReleaseORM).where(DeploymentReleaseORM.deployment_id == dep)
    ).all()
    assert len(releases) == 2
    jobs = db_session.exec(select(DeploymentReconcileJobORM)).all()
    assert [job.deployment_id for job in jobs] == [dep]


def test_a_second_run_finds_nothing_to_do(db_session, seed):
    seed("alice@example.com", "alice", "photos.alice.freepod.eu", name="photos")
    migrate.run(db_session, settings=SETTINGS, dry_run=False, out=lambda _l: None)
    lines = []

    again = migrate.run(db_session, settings=SETTINGS, dry_run=False, out=lines.append)

    assert again == []
    assert lines == ["Nothing to move."]


def test_other_hostnames_are_left_alone(db_session, seed):
    seed("alice@example.com", "alice", "photos.example.com", name="custom")
    seed("alice@example.com", "alice", "notes-alice.freepod.app", name="flat")
    seed("bob@example.com", "bob", "stolen.alice.freepod.eu", name="foreign")

    assert migrate.plan(db_session, SETTINGS) == []


def test_a_failed_move_is_reported_and_the_rest_continue(db_session, seed):
    seed("alice@example.com", "alice", "busy.alice.freepod.eu", status=DEPLOYMENT_STATUS_PROVISIONING, name="busy")
    ok = seed("alice@example.com", "alice", "fine.alice.freepod.eu", name="fine")
    lines = []

    moved = migrate.run(db_session, settings=SETTINGS, dry_run=False, out=lines.append)

    assert [m.old for m in moved] == ["fine.alice.freepod.eu"]
    assert any(line.startswith("FAILED busy.alice.freepod.eu") for line in lines)
    assert db_session.get(DeploymentORM, ok).hostname == "fine-alice.freepod.app"


def test_the_redirect_snippet_names_the_old_hostnames(db_session, seed):
    seed("alice@example.com", "alice", "photos.alice.freepod.eu", name="photos")
    lines = []

    migrate.run(db_session, settings=SETTINGS, dry_run=True, out=lines.append)

    snippet = "\n".join(lines[lines.index("") + 1 :])
    assert snippet == 'legacy_tenant_redirects = {\n  prod = [\n    "photos.alice.freepod.eu",\n  ]\n}'
