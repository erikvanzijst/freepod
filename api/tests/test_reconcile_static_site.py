"""The reconciler projects the release's build into `caelus.build` (static-site-sizing).

The facts come from the build the release records, never from user values, and
are emitted on every apply so a system override always holds the keys.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from app.models import BuildORM, DeploymentORM, DeploymentReleaseORM, ProductTemplateVersionORM
from app.services import template_values
from app.services.build_constants import (
    BUILD_STATUS_FAILED,
    BUILD_STATUS_QUEUED,
    BUILD_STATUS_SUCCEEDED,
)
from app.services.errors import IntegrityException
from app.services.reconcile import DeploymentReconciler
from tests.conftest import db_session  # noqa: F401
from tests.provisioner_utils import FakeProvisioner
from tests.test_reconcile_service import (  # noqa: F401
    _reconcile_tls_settings,
    _seed_deployment,
)

NO_BUILD = {"image": "", "staticSite": False}


def _build(
    db_session, deployment: DeploymentORM, *, static_site: bool, status=BUILD_STATUS_SUCCEEDED
):
    succeeded = status == BUILD_STATUS_SUCCEEDED
    image = f"{deployment.user_id}@sha256:{uuid4().hex * 2}" if succeeded else None
    build = BuildORM(
        deployment_id=deployment.id,
        artifact_id=uuid4().hex,
        status=status,
        image=image,
        static_site=static_site,
    )
    db_session.add(build)
    db_session.commit()
    return build


def _release(db_session, deployment_id, build: BuildORM | None) -> None:
    """Point the deployment at a new release shipping `build`."""
    deployment = db_session.get(DeploymentORM, deployment_id)
    current = db_session.get(DeploymentReleaseORM, deployment.desired_release_id)
    release = DeploymentReleaseORM(
        number=current.number + 1,
        deployment_id=deployment.id,
        template_id=deployment.desired_template_id,
        build_id=build.id if build else None,
    )
    db_session.add(release)
    deployment.desired_release_id = release.id
    db_session.add(deployment)
    db_session.commit()


def _apply(db_session, deployment_id) -> dict:
    provisioner = FakeProvisioner()
    DeploymentReconciler(session=db_session, provisioner=provisioner).reconcile(deployment_id)
    db_session.expire_all()
    return next(c[1] for c in provisioner.calls if c[0] == "helm_upgrade_install")["values"]


@pytest.fixture
def deployment(db_session) -> DeploymentORM:
    return db_session.get(DeploymentORM, _seed_deployment(db_session))


@pytest.mark.parametrize("static_site", [True, False])
def test_a_release_projects_its_builds_image_and_verdict(db_session, deployment, static_site):
    build = _build(db_session, deployment, static_site=static_site)
    _release(db_session, deployment.id, build)

    values = _apply(db_session, deployment.id)

    assert values["caelus"]["build"] == {"image": build.image, "staticSite": static_site}


def test_a_release_without_a_build_is_not_a_static_site(db_session, deployment):
    assert _apply(db_session, deployment.id)["caelus"]["build"] == NO_BUILD


@pytest.mark.parametrize("status", [BUILD_STATUS_QUEUED, BUILD_STATUS_FAILED])
def test_a_build_that_did_not_succeed_projects_nothing(db_session, deployment, status):
    build = _build(db_session, deployment, static_site=True, status=status)
    _release(db_session, deployment.id, build)

    assert _apply(db_session, deployment.id)["caelus"]["build"] == NO_BUILD


def test_each_release_follows_its_own_build(db_session, deployment):
    static = _build(db_session, deployment, static_site=True)
    server = _build(db_session, deployment, static_site=False)

    for build in (static, server, static, None):
        _release(db_session, deployment.id, build)
        expected = {"image": build.image, "staticSite": build.static_site} if build else NO_BUILD
        assert _apply(db_session, deployment.id)["caelus"]["build"] == expected


def test_re_applying_a_release_re_projects_it(db_session, deployment):
    """A lease reclaim or a retry renders the same release again."""
    build = _build(db_session, deployment, static_site=True)
    _release(db_session, deployment.id, build)

    first = _apply(db_session, deployment.id)["caelus"]["build"]
    again = _apply(db_session, deployment.id)["caelus"]["build"]

    assert first == again == {"image": build.image, "staticSite": True}


def test_a_tenant_cannot_claim_a_static_site_through_user_values(db_session, deployment):
    """Planted on a schema that permits it, so the merge itself is exercised; see
    `test_a_tenant_cannot_forge_the_release_id_through_user_values`."""
    template = db_session.get(ProductTemplateVersionORM, deployment.desired_template_id)
    template.values_schema_json = {"type": "object", "additionalProperties": True}
    db_session.add(template)
    forged = f"{deployment.user_id}@sha256:{'e' * 64}"
    deployment.user_values_json = {
        **(deployment.user_values_json or {}),
        "image": forged,
        "caelus": {"build": {"image": forged, "staticSite": True}},
    }
    db_session.add(deployment)
    db_session.commit()

    assert _apply(db_session, deployment.id)["caelus"]["build"] == NO_BUILD


def test_the_custom_schema_refuses_caelus_values_outright():
    repo = Path(__file__).resolve().parents[2]
    catalog = repo / "products" / "catalog" / "custom" / "custom.yaml"
    schema = yaml.safe_load(catalog.read_text())["template"]["values_schema"]

    with pytest.raises(IntegrityException, match="was unexpected"):
        template_values.validate_user_values(
            {"hostname": "a.example.test", "caelus": {"build": {"staticSite": True}}}, schema
        )
    with pytest.raises(IntegrityException, match="was unexpected"):
        template_values.validate_user_values(
            {"hostname": "a.example.test", "staticSiteResources": {"requests": {"memory": "1Mi"}}},
            schema,
        )
