"""Deriving the chart and vars projections from one template schema.

The worked examples in `openspec/changes/deployment-vars/design.md` are
reproduced verbatim here, because they are what the UI, the catalog and the
vars service were all designed against: if derivation drifts from them, the
form and the store disagree about which channel a property belongs to.
"""

from __future__ import annotations

import pytest

from app.services.errors import IntegrityException, ValidationException
from app.services.template_values import (
    check_var_markers,
    derive_projections,
    schema_declares_vars,
    validate_user_values,
    validate_vars,
)

DIALECT = "https://json-schema.org/draft/2020-12/schema"

# design.md, "Worked example: a curated schema with vars".
VAULTWARDEN = {
    "$schema": DIALECT,
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "host": {
            "type": "string",
            "title": "Hostname",
            "description": "The fully qualified domain name used to access Vaultwarden",
        },
        "SIGNUPS_ALLOWED": {
            "type": "boolean",
            "x-caelus-target": "runtime",
            "title": "Allow open registration",
            "default": False,
        },
        "SIGNUPS_VERIFY": {
            "type": "boolean",
            "x-caelus-target": "runtime",
            "title": "Require email verification on signups",
            "default": True,
        },
        "ADMIN_TOKEN": {
            "type": "string",
            "x-caelus-target": "runtime",
            "x-caelus-sensitive": True,
            "title": "Password for the admin interface",
        },
    },
    "required": ["host"],
}

# design.md, "Worked example: `custom`".
CUSTOM = {
    "$schema": DIALECT,
    "type": "object",
    "additionalProperties": False,
    "x-caelus-vars-additional": True,
    "properties": {
        "hostname": {"type": "string", "title": "hostname", "minLength": 1, "maxLength": 253},
        "image": {"type": "string", "pattern": r"^$|^[0-9]+@sha256:[a-f0-9]{64}$"},
    },
    "required": ["hostname"],
}


# ── Derivation ────────────────────────────────────────────────────────────


def test_vaultwarden_derives_the_documented_chart_projection():
    chart = derive_projections(VAULTWARDEN).chart
    assert chart == {
        "$schema": DIALECT,
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "host": {
                "type": "string",
                "title": "Hostname",
                "description": (
                    "The fully qualified domain name used to access Vaultwarden"
                ),
            }
        },
        "required": ["host"],
    }


def test_vaultwarden_derives_the_documented_vars_projection():
    """The routing marker has done its job and does not survive; the
    sensitivity marker does, because the vars service reads it back out."""
    assert derive_projections(VAULTWARDEN).vars == {
        "$schema": DIALECT,
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "SIGNUPS_ALLOWED": {
                "type": "boolean",
                "title": "Allow open registration",
                "default": False,
            },
            "SIGNUPS_VERIFY": {
                "type": "boolean",
                "title": "Require email verification on signups",
                "default": True,
            },
            "ADMIN_TOKEN": {
                "type": "string",
                "x-caelus-sensitive": True,
                "title": "Password for the admin interface",
            },
        },
        "required": [],
    }


def test_custom_derives_an_open_vars_projection_and_a_closed_chart_one():
    """The one schema whose halves disagree, and the reason
    `x-caelus-vars-additional` exists: `custom` runs tenant-supplied code and
    cannot enumerate its environment, while its chart values stay closed."""
    projections = derive_projections(CUSTOM)
    assert projections.vars == {
        "$schema": DIALECT,
        "type": "object",
        "additionalProperties": True,
        "properties": {},
        "required": [],
    }
    assert projections.chart["additionalProperties"] is False
    assert sorted(projections.chart["properties"]) == ["hostname", "image"]
    assert projections.chart["required"] == ["hostname"]


def test_an_unmarked_schema_derives_an_empty_closed_vars_projection():
    """Closed by default, with no per-product boilerplate to write or forget."""
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"host": {"type": "string"}},
        "required": ["host"],
    }
    projections = derive_projections(schema)
    assert projections.vars == {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
        "required": [],
    }
    assert projections.chart["properties"] == {"host": {"type": "string"}}
    assert not schema_declares_vars(schema)


def test_a_template_with_no_schema_projects_nothing():
    assert derive_projections(None) == (None, None)
    assert derive_projections({}) == (None, None)


def test_derivation_does_not_mutate_the_source_schema():
    import copy

    before = copy.deepcopy(VAULTWARDEN)
    projections = derive_projections(VAULTWARDEN)
    projections.chart["properties"]["host"]["title"] = "clobbered"
    projections.vars["properties"]["ADMIN_TOKEN"]["title"] = "clobbered"
    assert VAULTWARDEN == before


# ── Validating each half against its own projection ───────────────────────


def test_a_runtime_property_is_not_demanded_as_a_chart_value():
    """The point of 3.3: `user_values_json` sees the chart projection only."""
    validate_user_values({"host": "example.test"}, VAULTWARDEN)


def test_a_runtime_property_submitted_as_a_chart_value_is_rejected():
    with pytest.raises(IntegrityException):
        validate_user_values(
            {"host": "example.test", "ADMIN_TOKEN": "hunter2"}, VAULTWARDEN
        )


def test_a_chart_property_submitted_as_a_var_is_rejected():
    projection = derive_projections(VAULTWARDEN).vars
    with pytest.raises(ValidationException) as exc:
        validate_vars({"host": "example.test"}, projection)
    assert "host" in str(exc.value)


def test_a_template_with_no_schema_rejects_vars():
    with pytest.raises(ValidationException) as exc:
        validate_vars({"ANYTHING": "1"}, derive_projections(None).vars)
    assert "not supported" in str(exc.value)


def test_an_undeclared_var_is_accepted_on_an_open_projection():
    validate_vars({"WHATEVER": "1"}, derive_projections(CUSTOM).vars)


@pytest.mark.parametrize(
    "value,expected_ok",
    [("true", True), ("false", True), ("True", False), ("yes", False), ("1", False)],
)
def test_booleans_are_coerced_from_their_wire_spelling(value, expected_ok):
    projection = derive_projections(VAULTWARDEN).vars
    if expected_ok:
        validate_vars({"SIGNUPS_ALLOWED": value}, projection)
    else:
        with pytest.raises(ValidationException):
            validate_vars({"SIGNUPS_ALLOWED": value}, projection)


@pytest.mark.parametrize(
    "declared,value,expected_ok",
    [
        ("integer", "42", True),
        ("integer", "-7", True),
        ("integer", "1_0", False),  # int("1_0") is 10 in Python; it is not what was typed
        ("integer", "4.2", False),
        ("number", "4.2", True),
        ("number", "1e3", True),
        ("number", "nan", False),  # float("nan") succeeds; the user typed a word
        ("string", "anything", True),
    ],
)
def test_numeric_vars_are_coerced_before_validation(declared, value, expected_ok):
    projection = derive_projections(
        {
            "type": "object",
            "properties": {"COUNT": {"type": declared, "x-caelus-target": "runtime"}},
        }
    ).vars
    if expected_ok:
        validate_vars({"COUNT": value}, projection)
    else:
        with pytest.raises(ValidationException):
            validate_vars({"COUNT": value}, projection)


def test_a_validation_failure_never_echoes_the_value():
    """design.md D13: `ValidationError.message` embeds the instance, and the
    message reaches the caller *and* the logs, which ship to Loki."""
    secret = "hunter2-swordfish"
    projection = derive_projections(
        {
            "type": "object",
            "properties": {
                "ADMIN_TOKEN": {
                    "type": "string",
                    "minLength": 64,
                    "x-caelus-target": "runtime",
                    "x-caelus-sensitive": True,
                }
            },
        }
    ).vars

    with pytest.raises(ValidationException) as exc:
        validate_vars({"ADMIN_TOKEN": secret}, projection)

    message = str(exc.value)
    assert message == 'vars.ADMIN_TOKEN: failed constraint "minLength"'
    substrings = {
        secret[i : i + n]
        for n in range(3, len(secret) + 1)
        for i in range(len(secret) - n + 1)
    }
    assert not [s for s in substrings if s in message]


# ── Marker meta-validation ────────────────────────────────────────────────


def test_the_worked_examples_pass_meta_validation():
    check_var_markers(VAULTWARDEN)
    check_var_markers(CUSTOM)
    check_var_markers(None)


@pytest.mark.parametrize(
    "name,schema",
    [
        (
            "properties.signups.properties.allowed",
            {
                "type": "object",
                "properties": {
                    "signups": {
                        "type": "object",
                        "properties": {
                            "allowed": {"type": "boolean", "x-caelus-target": "runtime"}
                        },
                    }
                },
            },
        ),
        (
            "signups.allowed",
            {
                "type": "object",
                "properties": {
                    "signups.allowed": {"type": "boolean", "x-caelus-target": "runtime"}
                },
            },
        ),
        (
            "GROUP",
            {
                "type": "object",
                "properties": {"GROUP": {"type": "object", "x-caelus-target": "runtime"}},
            },
        ),
        (
            "PORTS",
            {
                "type": "object",
                "properties": {"PORTS": {"type": "array", "x-caelus-target": "runtime"}},
            },
        ),
        (
            "host",
            {
                "type": "object",
                "properties": {"host": {"type": "string", "x-caelus-sensitive": True}},
            },
        ),
        (
            "PORT",
            {
                "type": "object",
                "properties": {"PORT": {"type": "integer", "x-caelus-target": "runtime"}},
            },
        ),
        (
            "AWS_REGION",
            {
                "type": "object",
                "properties": {
                    "AWS_REGION": {"type": "string", "x-caelus-target": "runtime"}
                },
            },
        ),
        (
            "CAELUS_ANYTHING",
            {
                "type": "object",
                "properties": {
                    "CAELUS_ANYTHING": {"type": "string", "x-caelus-target": "runtime"}
                },
            },
        ),
        (
            "RAILPACK_CONFIG_FILE",
            {
                "type": "object",
                "properties": {
                    "RAILPACK_CONFIG_FILE": {"type": "string", "x-caelus-target": "runtime"}
                },
            },
        ),
        (
            "TOKEN",
            {
                "type": "object",
                "properties": {"TOKEN": {"type": "string", "x-caelus-target": "pod"}},
            },
        ),
    ],
    ids=[
        "nested-runtime-property",
        "dotted-name",
        "object-typed",
        "array-typed",
        "sensitive-without-runtime",
        "reserved-exact-name",
        "reserved-aws-prefix",
        "reserved-caelus-prefix",
        "reserved-railpack-prefix",
        "unknown-target",
    ],
)
def test_an_illegal_marker_is_rejected_naming_the_property(name, schema):
    with pytest.raises(ValidationException) as exc:
        check_var_markers(schema)
    assert name in str(exc.value)


def test_a_too_long_name_is_rejected():
    schema = {
        "type": "object",
        "properties": {"A" * 65: {"type": "string", "x-caelus-target": "runtime"}},
    }
    with pytest.raises(ValidationException):
        check_var_markers(schema)
    schema = {
        "type": "object",
        "properties": {"A" * 64: {"type": "string", "x-caelus-target": "runtime"}},
    }
    check_var_markers(schema)


def test_non_boolean_markers_are_rejected():
    with pytest.raises(ValidationException):
        check_var_markers({"type": "object", "x-caelus-vars-additional": "yes"})
    with pytest.raises(ValidationException):
        check_var_markers(
            {
                "type": "object",
                "properties": {
                    "TOKEN": {
                        "type": "string",
                        "x-caelus-target": "runtime",
                        "x-caelus-sensitive": "yes",
                    }
                },
            }
        )


# --- create_template meta-validation: the chart projection must be closed ---
# The chart projection's values are tenant-submitted (POST /deployments), so an
# open one is a Helm-value injection vector. `caelus.*` is merged in after
# validation and never checked here, so this does not constrain platform features.
from app.services.templates import _check_values_schema  # noqa: E402


def test_check_values_schema_rejects_an_open_chart_projection() -> None:
    for schema in (
        {"type": "object", "properties": {"host": {"type": "string"}}},  # no additionalProperties
        {"type": "object"},  # open and property-less
    ):
        with pytest.raises(ValidationException):
            _check_values_schema(schema)


def test_check_values_schema_accepts_a_closed_chart_projection() -> None:
    _check_values_schema(
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"host": {"type": "string"}},
        }
    )  # no raise


def test_check_values_schema_closed_chart_still_allows_open_vars() -> None:
    # `custom`'s shape: chart closed at the root, vars left open to accept the
    # arbitrary environment its tenant code needs.
    _check_values_schema(
        {
            "type": "object",
            "additionalProperties": False,
            "x-caelus-vars-additional": True,
            "properties": {
                "hostname": {"type": "string", "title": "hostname"},
                "DEBUG": {"type": "string", "x-caelus-target": "runtime"},
            },
        }
    )  # no raise


def test_check_values_schema_allows_no_schema() -> None:
    _check_values_schema(None)  # a template that takes no user values
