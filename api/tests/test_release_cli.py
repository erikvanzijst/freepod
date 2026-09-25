"""`caelus list-releases` / `get-release` — the CLI half of the release reads.

Thin shells over `services/deployments.py`, so these check the shell: the
output shape, the not-found exit, and that a non-admin cannot name another
account. `caelus` has no `require_self`, so that last one is the CLI's own
guard rather than the router's.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlmodel import Session

from app.models import (
    BuildORM,
    DeploymentORM,
    DeploymentReleaseORM,
    ProductORM,
    ProductTemplateVersionORM,
    UserORM,
)
from app.db import get_engine
from app.services.build_constants import BUILD_STATUS_SUCCEEDED
from tests.conftest import cli_runner, make_free_subscription  # noqa: F401

CLI_EMAIL = "cli-test@example.com"
IMAGE = "reg/app@sha256:" + "e" * 64


def _stdout(result) -> str:
    return getattr(result, "stdout", result.output)


@pytest.fixture
def world(cli_runner):
    """The acting user, a deployment, and releases 1 (succeeded) and 2 (queued)."""

    with Session(get_engine()) as session:
        user = UserORM(email=CLI_EMAIL)
        session.add(user)
        product = ProductORM(name="p", description="d")
        session.add(product)
        session.commit()
        session.refresh(user)
        session.refresh(product)

        template = ProductTemplateVersionORM(
            product_id=product.id,
            version=1,
            chart_ref="oci://example/chart",
            chart_version="1.0.0",
            values_schema_json={},
            default_values_json={},
        )
        session.add(template)
        session.commit()
        session.refresh(template)

        release_id = uuid4()
        deployment = DeploymentORM(
            user_id=user.id,
            desired_template_id=template.id,
            desired_release_id=release_id,
            subscription_id=make_free_subscription(
                session, user_id=user.id, product_id=product.id
            ),
            name="dep",
            namespace="ns",
        )
        session.add(deployment)
        first = DeploymentReleaseORM(
            id=release_id,
            number=1,
            deployment_id=deployment.id,
            template_id=template.id,
        )
        session.add(first)
        session.commit()

        # A build belongs to a deployment, so it can only exist once the
        # deployment does; release 1 is then the one that shipped it.
        build = BuildORM(
            deployment_id=deployment.id,
            artifact_id="a" * 32,
            status=BUILD_STATUS_SUCCEEDED,
            image=IMAGE,
        )
        session.add(build)
        session.commit()
        first.build_id = build.id
        session.add(first)
        session.commit()
        session.add(
            DeploymentReleaseORM(
                id=uuid4(),
                number=2,
                deployment_id=deployment.id,
                template_id=template.id,
            )
        )
        session.commit()
        session.refresh(deployment)
        return {"user_id": user.id, "deployment_id": deployment.id}


def test_list_releases_reports_them_most_recent_first(cli_runner, world):
    runner, app = cli_runner

    result = runner.invoke(
        app, ["list-releases", str(world["user_id"]), str(world["deployment_id"])]
    )

    assert result.exit_code == 0, _stdout(result)
    out = _stdout(result)
    assert "number: 2" in out and "number: 1" in out
    assert out.index("number: 2") < out.index("number: 1")


def test_get_release_reads_by_number_and_inlines_the_build(cli_runner, world):
    runner, app = cli_runner

    result = runner.invoke(
        app, ["get-release", str(world["user_id"]), str(world["deployment_id"]), "1"]
    )

    assert result.exit_code == 0, _stdout(result)
    assert IMAGE in _stdout(result)


def test_get_release_exits_for_a_number_never_reached(cli_runner, world):
    runner, app = cli_runner

    result = runner.invoke(
        app, ["get-release", str(world["user_id"]), str(world["deployment_id"]), "9"]
    )

    assert result.exit_code != 0
    assert IMAGE not in _stdout(result)


def test_a_non_admin_cannot_read_another_users_releases(cli_runner, world):

    runner, app = cli_runner
    with Session(get_engine()) as session:
        other = UserORM(email="someone-else@example.com")
        session.add(other)
        session.commit()
        session.refresh(other)
        other_id = other.id

    result = runner.invoke(
        app, ["list-releases", str(other_id), str(world["deployment_id"])]
    )

    assert result.exit_code == 1
    assert "admin" in (result.stderr if hasattr(result, "stderr") else _stdout(result))


def test_an_admin_may_read_another_users_releases(cli_runner, world):

    runner, app = cli_runner
    with Session(get_engine()) as session:
        acting = session.get(UserORM, world["user_id"])
        acting.is_admin = True
        other = UserORM(email="someone-else@example.com")
        session.add(acting)
        session.add(other)
        session.commit()
        session.refresh(other)
        other_id = other.id

    result = runner.invoke(
        app, ["list-releases", str(other_id), str(world["deployment_id"])]
    )

    assert result.exit_code == 0, _stdout(result)
    assert "number: 1" in _stdout(result)
