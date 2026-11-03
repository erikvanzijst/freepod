"""Chart values and vars validated together against the whole template schema.

Each half is still checked against its own projection; these tests cover the
additional pass over the merged document, on every path that changes what a
deployment's values or vars are.
"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml
from jsonschema import validate as jsonschema_validate
from sqlmodel import select

from app.models import DeploymentORM, DeploymentReconcileJobORM, DeploymentReleaseORM
from app.services.errors import IntegrityException, ValidationException
from app.services.jobs import JobService
from app.services.reconcile_constants import DEPLOYMENT_STATUS_READY
from app.services.template_values import (
    DOCUMENT_KEYWORDS,
    KEY_SET_KEYWORDS,
    derive_projections,
    validate_document,
    validate_user_values,
    validate_vars,
)
from tests.conftest import (  # noqa: F401
    client,
    create_free_plan_template,
    create_user,
    db_session,
)

DIALECT = "https://json-schema.org/draft/2020-12/schema"
SECRET = "hunter2"

# Sign in with Freepod replaces the app's own admin login, so the admin
# password var is demanded only when sign-in is off.
CONDITIONAL = {
    "$schema": DIALECT,
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "host": {"type": "string", "title": "hostname"},
        "auth": {"type": "object", "properties": {"enabled": {"type": "boolean"}}},
        "ADMIN_PASSWORD": {
            "type": "string",
            "x-caelus-target": "runtime",
            "x-caelus-sensitive": True,
        },
        "LOG_LEVEL": {"type": "string", "x-caelus-target": "runtime"},
    },
    "required": ["host"],
    "if": {
        "required": ["auth"],
        "properties": {
            "auth": {"required": ["enabled"], "properties": {"enabled": {"const": False}}}
        },
    },
    "then": {
        "required": ["ADMIN_PASSWORD"],
        "properties": {"ADMIN_PASSWORD": {"minLength": 12}},
    },
}

SIGN_IN_OFF = {"host": "app.example.test", "auth": {"enabled": False}}
SIGN_IN_ON = {"host": "app.example.test", "auth": {"enabled": True}}
GOOD_PASSWORD = "correct-horse-battery"

# `custom`'s shape: a closed chart half, an open vars half, and here a rule
# demanding an undeclared var whenever sign-in is on.
OPEN_CONDITIONAL = {
    "$schema": DIALECT,
    "type": "object",
    "additionalProperties": False,
    "x-caelus-vars-additional": True,
    "properties": {
        "hostname": {"type": "string", "title": "hostname"},
        "auth": {"type": "object", "properties": {"enabled": {"type": "boolean"}}},
    },
    "required": ["hostname"],
    "if": {
        "required": ["auth"],
        "properties": {"auth": {"properties": {"enabled": {"const": True}}}},
    },
    "then": {"required": ["SESSION_SECRET"]},
}


def _check(values, vars, schema=CONDITIONAL, *, error=IntegrityException):
    """Every pass a deployment write runs, in the order it runs them."""
    validate_user_values(values, schema)
    validate_vars(vars, derive_projections(schema).vars)
    validate_document(values, vars, schema, error=error)


# ── The full-document pass ───────────────────────────────────────────────


def test_a_conditional_spanning_both_halves_is_satisfied_by_a_var():
    _check(SIGN_IN_OFF, {"ADMIN_PASSWORD": GOOD_PASSWORD})


def test_a_conditional_spanning_both_halves_refuses_a_missing_var():
    with pytest.raises(IntegrityException) as exc:
        _check(SIGN_IN_OFF, {})
    assert str(exc.value) == 'vars.ADMIN_PASSWORD: failed constraint "required"'


def test_a_conditional_that_does_not_apply_demands_nothing():
    _check(SIGN_IN_ON, {})
    _check({"host": "app.example.test"}, {"LOG_LEVEL": "debug"})


def test_the_chart_projection_leaves_document_keywords_to_the_full_pass():
    chart = derive_projections(CONDITIONAL).chart
    assert not DOCUMENT_KEYWORDS & set(chart)
    assert chart["additionalProperties"] is False


def test_a_chart_side_failure_is_located_in_user_values_json():
    schema = {
        **CONDITIONAL,
        "if": {"required": ["LOG_LEVEL"]},
        "then": {"required": ["auth"]},
    }
    with pytest.raises(IntegrityException) as exc:
        _check({"host": "app.example.test"}, {"LOG_LEVEL": "debug"}, schema)
    assert str(exc.value) == 'user_values_json.auth: failed constraint "required"'


def test_dependent_required_across_halves_names_the_missing_key():
    schema = {
        key: value for key, value in CONDITIONAL.items() if key not in ("if", "then")
    }
    schema["dependentRequired"] = {"LOG_LEVEL": ["auth"]}
    with pytest.raises(IntegrityException) as exc:
        _check({"host": "app.example.test"}, {"LOG_LEVEL": "debug"}, schema)
    assert str(exc.value) == 'user_values_json.auth: failed constraint "dependentRequired"'


def test_vars_are_coerced_before_the_full_pass():
    schema = {
        "$schema": DIALECT,
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "host": {"type": "string"},
            "SIGNUPS_ALLOWED": {"type": "boolean", "x-caelus-target": "runtime"},
        },
        "if": {
            "required": ["SIGNUPS_ALLOWED"],
            "properties": {"SIGNUPS_ALLOWED": {"const": True}},
        },
        "then": {"required": ["host"]},
    }
    _check({}, {"SIGNUPS_ALLOWED": "false"}, schema)
    with pytest.raises(IntegrityException) as exc:
        _check({}, {"SIGNUPS_ALLOWED": "true"}, schema)
    assert str(exc.value) == 'user_values_json.host: failed constraint "required"'


def test_the_caller_chooses_the_exception():
    with pytest.raises(ValidationException):
        _check(SIGN_IN_OFF, {}, error=ValidationException)


def test_a_template_without_a_schema_has_no_full_pass():
    validate_document({}, {}, None)


# ── Open vars projections (`custom`) ─────────────────────────────────────


def test_an_open_vars_projection_keeps_accepting_undeclared_vars():
    """The root's `additionalProperties: false` belongs to the chart half."""
    _check(
        {"hostname": "app.example.test"},
        {"DATABASE_URL": "postgres://x", "FEATURE_FLAG": "on"},
        OPEN_CONDITIONAL,
    )


def test_a_conditional_may_demand_an_undeclared_var():
    with pytest.raises(IntegrityException) as exc:
        _check({"hostname": "app.example.test", "auth": {"enabled": True}}, {}, OPEN_CONDITIONAL)
    assert str(exc.value) == 'vars.SESSION_SECRET: failed constraint "required"'

    _check(
        {"hostname": "app.example.test", "auth": {"enabled": True}},
        {"SESSION_SECRET": "s", "OTHER": "o"},
        OPEN_CONDITIONAL,
    )


def test_an_undeclared_chart_value_is_still_refused_by_its_projection():
    with pytest.raises(IntegrityException):
        _check({"hostname": "app.example.test", "extra": 1}, {}, OPEN_CONDITIONAL)


@pytest.mark.parametrize("keyword", sorted(KEY_SET_KEYWORDS - {"additionalProperties"}))
def test_root_key_set_keywords_do_not_reach_the_vars_half(keyword):
    constraint = {
        "unevaluatedProperties": False,
        "patternProperties": {"^[A-Z_]+$": {"type": "integer"}},
        "propertyNames": {"pattern": "^[a-z]+$"},
        "minProperties": 3,
        "maxProperties": 1,
    }[keyword]
    schema = {**OPEN_CONDITIONAL, keyword: constraint}
    validate_document({"hostname": "a"}, {"SOME_VAR": "x", "OTHER": "y"}, schema)


# ── Sensitive values never leak ──────────────────────────────────────────


def test_a_full_pass_failure_never_carries_a_var_value(caplog):
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(IntegrityException) as exc:
            _check(SIGN_IN_OFF, {"ADMIN_PASSWORD": SECRET})

    assert str(exc.value) == 'vars.ADMIN_PASSWORD: failed constraint "minLength"'
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None
    assert SECRET not in "".join(traceback.format_exception(exc.value))
    assert SECRET not in repr(exc.value.args)
    assert SECRET not in caplog.text


def test_a_projection_failure_never_chains_a_var_value():
    with pytest.raises(ValidationException) as exc:
        validate_vars({"PW": SECRET}, {"type": "object", "properties": {"PW": {"minLength": 12}}})
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None
    assert SECRET not in "".join(traceback.format_exception(exc.value))


# ── Every catalog template keeps working ─────────────────────────────────

PRODUCTS = Path(__file__).resolve().parents[2] / "products"
CATALOG_SCHEMAS = {
    path.stem: yaml.safe_load(path.read_text())["template"]["values_schema"]
    for path in sorted((PRODUCTS / "catalog").glob("*/*.yaml"))
    if path.stem == path.parent.name
}
CANDIDATE_STRINGS = ("app.example.test", "Str0ng!Passw0rd-Example")
# Keywords whose effect on a document the projections already fully apply.
PROJECTED_KEYWORDS = {"$schema", "type", "title", "description", "properties", "required", "$defs"}


def _sample(schema: dict[str, Any]) -> Any:
    """A value satisfying `schema`, for the constraints the catalog uses."""
    if "default" in schema:
        return schema["default"]
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        properties = schema.get("properties") or {}
        return {
            key: _sample(prop)
            for key, prop in properties.items()
            if key in (schema.get("required") or []) or "default" in prop
        }
    if kind == "boolean":
        return False
    if kind in ("integer", "number"):
        return schema.get("minimum", 1)
    if kind == "array":
        return []
    for candidate in CANDIDATE_STRINGS:
        try:
            jsonschema_validate(candidate, schema)
            return candidate
        except Exception:
            continue
    raise AssertionError(f"no sample string satisfies {schema}")


def _wire(value: Any) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def test_the_catalog_is_not_empty():
    assert CATALOG_SCHEMAS


@pytest.mark.parametrize("slug", sorted(CATALOG_SCHEMAS))
def test_a_catalog_schema_is_projected_without_loss(slug):
    """No root keyword the full pass applies that the projections do not.

    For such a schema the full pass accepts whatever both projections accept,
    so no existing deployment's write is newly refused.
    """
    schema = CATALOG_SCHEMAS[slug]
    extra = set(schema) - PROJECTED_KEYWORDS - KEY_SET_KEYWORDS
    assert {key for key in extra if not key.startswith("x-caelus-")} == set()


@pytest.mark.parametrize("slug", sorted(CATALOG_SCHEMAS))
def test_a_catalog_schema_accepts_representative_input(slug):
    schema = CATALOG_SCHEMAS[slug]
    document = _sample(schema)
    runtime = derive_projections(schema).vars["properties"]
    values = {k: v for k, v in document.items() if k not in runtime}
    vars = {k: _wire(v) for k, v in document.items() if k in runtime}
    if schema.get("x-caelus-vars-additional"):
        vars["DATABASE_URL"] = "postgres://example"
    _check(values, vars, schema)


# ── Through the API ──────────────────────────────────────────────────────


@pytest.fixture
def project(client, db_session):
    user_id = create_user(client, "fulldoc@example.com")["id"]
    product_id = client.post(
        "/api/products", json={"name": "fulldoc", "description": "d"}
    ).json()["id"]
    template_id = _add_template(client, product_id, CONDITIONAL)
    client.put(f"/api/products/{product_id}", json={"template_id": template_id})
    return {
        "client": client,
        "session": db_session,
        "user_id": user_id,
        "product_id": product_id,
        "template_id": template_id,
        "plan_template_id": create_free_plan_template(db_session, product_id),
    }


def _add_template(client, product_id, schema, version="1.0.0"):
    response = client.post(
        f"/api/products/{product_id}/templates",
        json={
            "chart_ref": "registry.home/fulldoc/",
            "chart_version": version,
            "values_schema_json": schema,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create(project, values, vars=None):
    body = {
        "desired_template_id": project["template_id"],
        "plan_template_id": project["plan_template_id"],
        "user_values_json": values,
    }
    if vars is not None:
        body["vars"] = vars
    return project["client"].post(f"/api/users/{project['user_id']}/deployments", json=body)


def _created_ready(project, values, vars=None):
    response = _create(project, values, vars)
    assert response.status_code == 201, response.text
    deployment_id = UUID(response.json()["deployment"]["id"])
    session = project["session"]
    job = session.exec(
        select(DeploymentReconcileJobORM).where(
            DeploymentReconcileJobORM.deployment_id == deployment_id
        )
    ).one()
    JobService(session).mark_job_done(job_id=job.id)
    deployment = session.get(DeploymentORM, deployment_id)
    deployment.status = DEPLOYMENT_STATUS_READY
    deployment.applied_release_id = deployment.desired_release_id
    session.add(deployment)
    session.commit()
    return deployment_id


def _update(project, deployment_id, **body):
    body.setdefault("desired_template_id", project["template_id"])
    return project["client"].put(
        f"/api/users/{project['user_id']}/deployments/{deployment_id}", json=body
    )


def _end_request(project):
    """What closing a refused request's own session does in production."""
    project["session"].rollback()


def _vars_url(project, deployment_id):
    return f"/api/users/{project['user_id']}/deployments/{deployment_id}/vars/runtime"


def _releases(project, deployment_id):
    return project["session"].exec(
        select(DeploymentReleaseORM).where(DeploymentReleaseORM.deployment_id == deployment_id)
    ).all()


def test_create_honors_a_conditional_spanning_both_halves(project):
    response = _create(project, SIGN_IN_OFF, {"ADMIN_PASSWORD": {"value": GOOD_PASSWORD}})
    assert response.status_code == 201, response.text


def test_create_refuses_a_missing_conditional_var_with_409_and_leaves_nothing(project):
    response = _create(project, SIGN_IN_OFF)
    assert response.status_code == 409
    assert response.json()["detail"] == 'vars.ADMIN_PASSWORD: failed constraint "required"'
    assert project["session"].exec(select(DeploymentORM)).all() == []


def test_create_never_echoes_a_sensitive_value(project, caplog):
    with caplog.at_level(logging.DEBUG):
        response = _create(project, SIGN_IN_OFF, {"ADMIN_PASSWORD": {"value": SECRET}})
    assert response.status_code == 409
    assert response.json()["detail"] == 'vars.ADMIN_PASSWORD: failed constraint "minLength"'
    assert SECRET not in response.text
    assert SECRET not in caplog.text


def test_update_checks_new_values_against_stored_vars(project):
    deployment_id = _created_ready(project, SIGN_IN_ON)

    refused = _update(project, deployment_id, user_values_json=SIGN_IN_OFF)
    assert refused.status_code == 409
    assert refused.json()["detail"] == 'vars.ADMIN_PASSWORD: failed constraint "required"'
    _end_request(project)
    assert len(_releases(project, deployment_id)) == 1

    accepted = _update(
        project,
        deployment_id,
        user_values_json=SIGN_IN_OFF,
        vars={"ADMIN_PASSWORD": {"value": GOOD_PASSWORD}},
    )
    assert accepted.status_code == 200, accepted.text


def test_update_counts_a_stored_sensitive_var_it_does_not_resubmit(project):
    deployment_id = _created_ready(
        project, SIGN_IN_OFF, {"ADMIN_PASSWORD": {"value": GOOD_PASSWORD}}
    )
    response = _update(project, deployment_id, vars={"LOG_LEVEL": {"value": "debug"}})
    assert response.status_code == 200, response.text


def test_moving_to_a_template_with_a_new_rule_checks_the_stored_state(project):
    """An administrator's template move is validated against the target's rules."""
    open_schema = {
        key: value for key, value in CONDITIONAL.items() if key not in ("if", "then")
    }
    first = _add_template(project["client"], project["product_id"], open_schema, "0.9.0")
    project["client"].put(
        f"/api/products/{project['product_id']}", json={"template_id": first}
    )
    project["template_id"] = first
    deployment_id = _created_ready(project, SIGN_IN_OFF)

    refused = _update(project, deployment_id, desired_template_id=_conditional_template(project))
    assert refused.status_code == 409
    assert refused.json()["detail"] == 'vars.ADMIN_PASSWORD: failed constraint "required"'
    _end_request(project)
    assert project["session"].get(DeploymentORM, deployment_id).desired_template_id == first
    assert len(_releases(project, deployment_id)) == 1


def _conditional_template(project):
    return _add_template(project["client"], project["product_id"], CONDITIONAL, "2.0.0")


def test_the_vars_api_checks_vars_against_the_stored_chart_values(project):
    deployment_id = _created_ready(
        project, SIGN_IN_OFF, {"ADMIN_PASSWORD": {"value": GOOD_PASSWORD}}
    )
    client = project["client"]
    url = _vars_url(project, deployment_id)

    deleted = client.delete(f"{url}/ADMIN_PASSWORD")
    assert deleted.status_code == 400
    assert deleted.json()["detail"] == 'vars.ADMIN_PASSWORD: failed constraint "required"'

    replaced = client.put(url, json={"vars": {"LOG_LEVEL": {"value": "debug"}}})
    assert replaced.status_code == 400

    weakened = client.patch(url, json={"vars": {"ADMIN_PASSWORD": {"value": SECRET}}})
    assert weakened.status_code == 400
    assert SECRET not in weakened.text

    merged = client.patch(url, json={"vars": {"LOG_LEVEL": {"value": "debug"}}})
    assert merged.status_code == 200, merged.text


def test_the_vars_api_lets_a_rule_that_does_not_apply_stay_quiet(project):
    deployment_id = _created_ready(project, SIGN_IN_ON)
    response = project["client"].put(
        _vars_url(project, deployment_id), json={"vars": {"LOG_LEVEL": {"value": "debug"}}}
    )
    assert response.status_code == 200, response.text


def test_custom_style_deployments_keep_undeclared_vars(project):
    template_id = _add_template(
        project["client"], project["product_id"], OPEN_CONDITIONAL, "3.0.0"
    )
    project["client"].put(
        f"/api/products/{project['product_id']}", json={"template_id": template_id}
    )
    project["template_id"] = template_id
    values = {"hostname": "app.example.test", "auth": {"enabled": True}}

    refused = _create(project, values, {"DATABASE_URL": {"value": "postgres://x"}})
    assert refused.status_code == 409, refused.text

    created = _create(
        project,
        values,
        {"DATABASE_URL": {"value": "postgres://x"}, "SESSION_SECRET": {"value": "s"}},
    )
    assert created.status_code == 201, created.text
