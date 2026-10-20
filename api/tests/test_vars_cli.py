"""`caelus var` and the vars options on `create-deployment` / `update-deployment`.

Thin shells over `services/vars.py`, so these check the shell: input shapes,
that secrets stay off the command line and out of the output, attribution, and
the CLI's own self-or-admin guard, which `caelus` has in place of the REST
API's `require_self`.
"""

from __future__ import annotations

import json
from uuid import UUID

import pytest
import yaml
from sqlmodel import Session, select

from app.db import get_engine
from app.models import (
    DeploymentORM,
    DeploymentReconcileJobORM,
    ProductORM,
    ProductTemplateVersionORM,
    UserORM,
)
from app.services import vars as vars_service
from app.services.jobs import JobService
from app.services.reconcile_constants import DEPLOYMENT_STATUS_READY
from tests.conftest import (  # noqa: F401
    CURRENT_TOS_VERSION,
    cli_runner,
    create_free_plan_template,
    handle_for,
)

OPERATOR = "cli-test@example.com"
SECRET = "hunter2-swordfish"

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "x-caelus-vars-additional": True,
    "properties": {
        "host": {"type": "string", "title": "hostname"},
        "ADMIN_TOKEN": {
            "type": "string",
            "x-caelus-target": "runtime",
            "x-caelus-sensitive": True,
        },
    },
    "required": ["host", "ADMIN_TOKEN"],
}


def _user(session: Session, email: str, *, is_admin: bool = False) -> int:
    user = UserORM(
        email=email,
        is_admin=is_admin,
        handle=handle_for(email),
        tos_accepted_version=CURRENT_TOS_VERSION,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user.id


@pytest.fixture
def world(cli_runner):
    """The acting operator, who owns the account, and a product declaring a
    required sensitive var."""
    with Session(get_engine()) as session:
        user_id = _user(session, OPERATOR)
        product = ProductORM(name="vaultish", description="d")
        session.add(product)
        session.commit()
        session.refresh(product)
        template = ProductTemplateVersionORM(
            product_id=product.id,
            version=1,
            chart_ref="oci://example/vaultish",
            chart_version="1.0.0",
            values_schema_json=SCHEMA,
            default_values_json={},
        )
        session.add(template)
        session.commit()
        session.refresh(template)
        product.template_id = template.id
        session.add(product)
        session.commit()
        plan_template_id = create_free_plan_template(session, product.id)
    runner, app = cli_runner
    return {
        "runner": runner,
        "app": app,
        "user_id": user_id,
        "template_id": template.id,
        "plan_template_id": plan_template_id,
    }


def cli(world, *args, input=None, email=OPERATOR):
    return world["runner"].invoke(world["app"], ["--as-user", email, *args], input=input)


def _create(world, *extra, input=None):
    return cli(
        world,
        "create-deployment",
        "--user-id", str(world["user_id"]),
        "--desired-template-id", str(world["template_id"]),
        "--plan-template-id", str(world["plan_template_id"]),
        "--user-values-json", '{"host": "vault.example.test"}',
        *extra,
        input=input,
    )


@pytest.fixture
def deployment_id(world) -> str:
    result = _create(world, "--vars-file", "-", input=json.dumps({"vars": {"ADMIN_TOKEN": {"value": SECRET}}}))
    assert result.exit_code == 0, result.output
    return yaml.safe_load(result.output)["id"]


def var(world, deployment_id, *args, input=None, email=OPERATOR, user_id=None):
    sub, *rest = args
    return cli(
        world, "var", sub, str(user_id or world["user_id"]), str(deployment_id), *rest,
        input=input, email=email,
    )


def listed(world, deployment_id) -> dict:
    result = var(world, deployment_id, "list")
    assert result.exit_code == 0, result.output
    return yaml.safe_load(result.output)


def test_create_requires_the_templates_runtime_var(world):
    result = _create(world)
    assert result.exit_code != 0
    assert "required" in result.output


def test_create_takes_vars_from_stdin_into_the_first_release(world, deployment_id):
    assert SECRET not in json.dumps(listed(world, deployment_id))
    entry = listed(world, deployment_id)["vars"]["ADMIN_TOKEN"]
    assert entry["sensitive"] is True
    assert "value" not in entry

    with Session(get_engine()) as session:
        deployment = session.get(DeploymentORM, UUID(deployment_id))
        snapshot = vars_service.read_snapshot(session, deployment.desired_release_id)
    assert set(snapshot) == {"ADMIN_TOKEN"}


def test_create_rejects_a_malformed_vars_input(world):
    result = _create(world, "--vars-json", '{"ADMIN_TOKEN": "bare map"}')
    assert result.exit_code == 1
    assert '{"vars":' in result.output


def test_update_merges_vars(world, deployment_id):
    with Session(get_engine()) as session:
        job = session.exec(
            select(DeploymentReconcileJobORM).where(
                DeploymentReconcileJobORM.deployment_id == UUID(deployment_id)
            )
        ).one()
        JobService(session).mark_job_done(job_id=job.id)
        deployment = session.get(DeploymentORM, UUID(deployment_id))
        deployment.status = DEPLOYMENT_STATUS_READY
        deployment.applied_release_id = deployment.desired_release_id
        session.add(deployment)
        session.commit()
    result = cli(
        world,
        "update-deployment",
        "--user-id", str(world["user_id"]),
        "--deployment-id", deployment_id,
        "--desired-template-id", str(world["template_id"]),
        "--vars-json", '{"vars": {"LOG_LEVEL": {"value": "debug"}}}',
    )
    assert result.exit_code == 0, result.output
    assert set(listed(world, deployment_id)["vars"]) == {"ADMIN_TOKEN", "LOG_LEVEL"}


def test_set_get_and_attribution(world, deployment_id):
    result = var(world, deployment_id, "set", "LOG_LEVEL=info")
    assert result.exit_code == 0, result.output

    got = yaml.safe_load(var(world, deployment_id, "get", "LOG_LEVEL").output)
    assert got["vars"]["LOG_LEVEL"]["value"] == "info"
    assert got["vars"]["LOG_LEVEL"]["updated_by"]["id"] == world["user_id"]
    assert got["pending"] is True


def test_a_bare_key_is_prompted_without_echo(world, deployment_id):
    result = var(world, deployment_id, "set", "API_KEY", "--secret", input="s3cret-value\n")
    assert result.exit_code == 0, result.output
    assert "s3cret-value" not in result.output
    entry = listed(world, deployment_id)["vars"]["API_KEY"]
    assert entry["sensitive"] is True and "value" not in entry


def test_replace_deletes_what_is_not_given(world, deployment_id):
    var(world, deployment_id, "set", "A=1", "B=2")
    result = var(world, deployment_id, "set", "--replace", "--file", "-",
                 input=yaml.safe_dump({"vars": {"ADMIN_TOKEN": {}, "A": {"value": "1"}}}))
    assert result.exit_code == 0, result.output
    assert set(listed(world, deployment_id)["vars"]) == {"ADMIN_TOKEN", "A"}


def test_a_list_round_trips_into_a_replace(world, deployment_id):
    var(world, deployment_id, "set", "A=1")
    before = listed(world, deployment_id)
    result = var(world, deployment_id, "set", "--replace", "--file", "-", input=yaml.safe_dump(before))
    assert result.exit_code == 0, result.output
    after = listed(world, deployment_id)
    assert after["vars"] == before["vars"]


def test_rm_deletes_and_tolerates_absent_keys(world, deployment_id):
    var(world, deployment_id, "set", "A=1")
    result = var(world, deployment_id, "rm", "A", "NEVER_SET")
    assert result.exit_code == 0, result.output
    assert set(listed(world, deployment_id)["vars"]) == {"ADMIN_TOKEN"}


def test_a_reserved_key_fails_like_the_api_and_writes_nothing(world, deployment_id):
    result = var(world, deployment_id, "set", "A=1", "AWS_REGION=eu")
    assert result.exit_code != 0
    assert "AWS_REGION" in result.output
    assert set(listed(world, deployment_id)["vars"]) == {"ADMIN_TOKEN"}


def test_an_unknown_phase_is_not_found(world, deployment_id):
    result = var(world, deployment_id, "list", "--phase", "build")
    assert result.exit_code != 0
    assert "Unknown phase" in result.output


def test_a_mismatched_owner_is_not_found_even_for_an_admin(world, deployment_id):
    with Session(get_engine()) as session:
        admin_id = _user(session, "admin@example.com", is_admin=True)
    result = var(world, deployment_id, "list", email="admin@example.com", user_id=admin_id)
    assert result.exit_code != 0
    assert var(world, deployment_id, "list", email="admin@example.com").exit_code == 0


def test_a_non_admin_cannot_name_another_account(world, deployment_id):
    with Session(get_engine()) as session:
        _user(session, "mallory@example.com")
    result = var(world, deployment_id, "set", "A=1", email="mallory@example.com")
    assert result.exit_code == 1
    assert "admin privileges" in result.output
