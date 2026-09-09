"""Schema-driven prompting and hostname handling."""

from __future__ import annotations

import pytest

from freepod.values import (
    ValueCollector,
    ValueError_,
    check_constraints,
    describe_reason,
    is_hostname_property,
    missing_required,
    normalize_hostname,
)

# The real schema from dev's `custom` product template, trimmed to shape.
CUSTOM_SCHEMA = {
    "type": "object",
    "properties": {
        "hostname": {
            "type": "string",
            "title": "hostname",
            "minLength": 1,
            "maxLength": 253,
            "description": "The fully qualified hostname for the app.",
        },
        "image": {
            "type": "string",
            "pattern": "^$|^[0-9]+@sha256:[a-f0-9]{64}$",
        },
    },
    "required": ["hostname"],
    "additionalProperties": False,
}

ACCOUNT_FQDN = "erik.dev.freepod.eu"


class Asker:
    """A scripted stand-in for `click.prompt`."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, text, default=None):
        self.prompts.append(text)
        if not self.answers:
            raise AssertionError(f"unexpected extra prompt: {text}")
        return self.answers.pop(0)


def collector(schema=CUSTOM_SCHEMA, *, answers=(), usable=True, reasons=None, **kwargs):
    messages = []
    verdicts = list(reasons) if reasons else None

    def check(fqdn):
        if verdicts:
            reason = verdicts.pop(0)
            return {"fqdn": fqdn, "usable": reason is None, "reason": reason}
        return {"fqdn": fqdn, "usable": usable, "reason": None if usable else "in_use"}

    asker = Asker(*answers)
    instance = ValueCollector(
        schema,
        account_fqdn=ACCOUNT_FQDN,
        check_hostname=check,
        echo=messages.append,
        ask=asker,
        **kwargs,
    )
    return instance, asker, messages


# --------------------------------------------------------------------------
# Required vs optional (task 6.1)
# --------------------------------------------------------------------------


def test_only_required_properties_are_prompted_for():
    values, asker, _ = collector(answers=["myapp"])
    result = values.collect()

    assert result == {"hostname": "myapp.erik.dev.freepod.eu"}
    assert len(asker.prompts) == 1, "image is not required and must not be asked for"


def test_an_optional_property_is_never_written():
    values, _, _ = collector(answers=["myapp"])
    assert "image" not in values.collect()


def test_an_unknown_required_property_is_prompted_for():
    """A new required field appears without a client release."""
    schema = {
        "properties": {
            "hostname": {"type": "string", "title": "hostname"},
            "region": {"type": "string", "description": "Where to run it."},
        },
        "required": ["hostname", "region"],
    }
    values, asker, messages = collector(schema, answers=["myapp", "eu-west"])

    assert values.collect() == {"hostname": "myapp.erik.dev.freepod.eu", "region": "eu-west"}
    assert any("region" in prompt for prompt in asker.prompts)
    assert any("Where to run it." in message for message in messages)


def test_an_empty_required_list_asks_nothing():
    values, asker, _ = collector({"properties": {}, "required": []})
    assert values.collect() == {}
    assert asker.prompts == []


# --------------------------------------------------------------------------
# Local constraints (task 6.2)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec,value,expected",
    [
        ({"minLength": 3}, "ab", "at least 3"),
        ({"maxLength": 4}, "abcde", "at most 4"),
        ({"pattern": "^[a-z]+$"}, "ABC", "pattern"),
        ({"enum": ["a", "b"]}, "c", "one of: a, b"),
        ({"minLength": 1}, "", "at least 1 character"),
    ],
)
def test_constraint_violations_are_explained(spec, value, expected):
    problem = check_constraints("field", value, spec)
    assert problem is not None and expected in problem


@pytest.mark.parametrize(
    "spec,value",
    [
        ({"minLength": 3}, "abc"),
        ({"maxLength": 4}, "abcd"),
        ({"pattern": "^[a-z]+$"}, "abc"),
        ({"enum": ["a", "b"]}, "b"),
        ({}, "anything"),
    ],
)
def test_satisfied_constraints_pass(spec, value):
    assert check_constraints("field", value, spec) is None


def test_an_uncompilable_pattern_is_left_to_the_platform():
    assert check_constraints("field", "x", {"pattern": "([unclosed"}) is None


def test_a_constraint_violation_re_prompts():
    schema = {
        "properties": {"code": {"type": "string", "pattern": "^[a-z]{3}$"}},
        "required": ["code"],
    }
    values, asker, messages = collector(schema, answers=["TOOLONG", "abc"])

    assert values.collect() == {"code": "abc"}
    assert len(asker.prompts) == 2
    assert any("pattern" in message for message in messages)


# --------------------------------------------------------------------------
# Hostname handling (task 6.3)
# --------------------------------------------------------------------------


def test_the_hostname_property_is_identified_by_title_case_insensitively():
    assert is_hostname_property({"title": "hostname"})
    assert is_hostname_property({"title": "Hostname"})
    assert is_hostname_property({"title": "  HOSTNAME  "})
    assert not is_hostname_property({"title": "host"})
    assert not is_hostname_property({})


def test_a_bare_label_becomes_a_platform_subdomain():
    assert normalize_hostname("MyApp", ACCOUNT_FQDN) == "myapp.erik.dev.freepod.eu"


def test_a_qualified_name_is_lowercased_and_left_intact():
    assert normalize_hostname("App.Example.COM", ACCOUNT_FQDN) == "app.example.com"


def test_a_trailing_dot_is_stripped():
    assert normalize_hostname("myapp.example.com.", ACCOUNT_FQDN) == "myapp.example.com"


def test_a_bare_label_completes_beneath_the_account_name():
    assert normalize_hostname("x", "erik.example") == "x.erik.example"


def test_a_bare_label_with_no_account_name_is_left_alone():
    assert normalize_hostname("myapp", None) == "myapp"


def test_the_completed_name_is_shown():
    values, _, messages = collector(answers=["myapp"])
    values.collect()
    assert any("myapp.erik.dev.freepod.eu" in message for message in messages)


# --------------------------------------------------------------------------
# The hostname check (task 6.4)
# --------------------------------------------------------------------------


def test_an_unusable_hostname_re_prompts_with_its_reason():
    values, asker, messages = collector(answers=["taken", "free"], reasons=["in_use", None])

    assert values.collect() == {"hostname": "free.erik.dev.freepod.eu"}
    assert len(asker.prompts) == 2
    assert any("already taken" in message for message in messages)


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("in_use", "already taken"),
        ("reserved", "reserved"),
        ("invalid", "not a valid hostname"),
        ("claimed", "another account holds"),
        ("not_resolving", "CNAME"),
    ],
)
def test_every_platform_reason_has_a_reading(reason, expected):
    assert expected in describe_reason(reason)


def test_an_unknown_reason_is_passed_through():
    assert "quota_exceeded" in describe_reason("quota_exceeded")


def test_a_usable_hostname_is_recorded():
    values, _, _ = collector(answers=["myapp"], usable=True)
    assert values.collect()["hostname"] == "myapp.erik.dev.freepod.eu"


def test_the_check_is_skipped_when_no_checker_is_supplied():
    """`deploy` skips it for an unchanged hostname — design D14."""
    instance = ValueCollector(
        CUSTOM_SCHEMA,
        account_fqdn=ACCOUNT_FQDN,
        check_hostname=None,
        echo=lambda _m: None,
        ask=Asker("myapp"),
    )
    assert instance.collect()["hostname"] == "myapp.erik.dev.freepod.eu"


# --------------------------------------------------------------------------
# Reuse by init and deploy (task 6.5)
# --------------------------------------------------------------------------


def test_only_missing_mode_leaves_settled_values_alone():
    values, asker, _ = collector(answers=[])
    result = values.collect({"hostname": "existing.erik.dev.freepod.eu"}, only_missing=True)

    assert result == {"hostname": "existing.erik.dev.freepod.eu"}
    assert asker.prompts == [], "a settled value must not be re-asked"


def test_only_missing_mode_prompts_for_what_is_absent():
    schema = {
        "properties": {
            "hostname": {"type": "string", "title": "hostname"},
            "region": {"type": "string"},
        },
        "required": ["hostname", "region"],
    }
    values, asker, _ = collector(schema, answers=["eu-west"])
    result = values.collect({"hostname": "existing.erik.dev.freepod.eu"}, only_missing=True)

    assert result == {"hostname": "existing.erik.dev.freepod.eu", "region": "eu-west"}
    assert len(asker.prompts) == 1


def test_an_empty_string_counts_as_missing():
    values, asker, _ = collector(answers=["myapp"])
    result = values.collect({"hostname": ""}, only_missing=True)
    assert result["hostname"] == "myapp.erik.dev.freepod.eu"
    assert len(asker.prompts) == 1


def test_unrelated_existing_values_are_carried_through():
    values, _, _ = collector(answers=[])
    result = values.collect(
        {"hostname": "a.erik.dev.freepod.eu", "custom_setting": "kept"}, only_missing=True
    )
    assert result["custom_setting"] == "kept"


def test_missing_required_reports_absent_names():
    assert missing_required(CUSTOM_SCHEMA, {}) == ["hostname"]
    assert missing_required(CUSTOM_SCHEMA, {"hostname": "a"}) == []
    assert missing_required(CUSTOM_SCHEMA, {"hostname": ""}) == ["hostname"]


# --------------------------------------------------------------------------
# No prompt available (task 6.6)
# --------------------------------------------------------------------------


def test_a_missing_value_with_no_prompt_names_the_field():
    instance = ValueCollector(CUSTOM_SCHEMA, account_fqdn=ACCOUNT_FQDN, interactive=False)

    with pytest.raises(ValueError_) as raised:
        instance.collect()

    message = str(raised.value)
    assert "hostname" in message
    assert "no terminal" in message


def test_a_present_but_invalid_value_with_no_prompt_names_the_constraint():
    schema = {
        "properties": {"code": {"type": "string", "minLength": 5}},
        "required": ["code"],
    }
    instance = ValueCollector(schema, interactive=False)

    with pytest.raises(ValueError_, match="at least 5"):
        instance.collect({"code": "ab"})


def test_a_valid_value_with_no_prompt_is_accepted():
    instance = ValueCollector(CUSTOM_SCHEMA, account_fqdn=ACCOUNT_FQDN, interactive=False)
    assert instance.collect({"hostname": "a.erik.dev.freepod.eu"}) == {"hostname": "a.erik.dev.freepod.eu"}
