"""The domain name an account is addressed under, in deploy preflight.

The client never claims one: choosing it is a one-time, irreversible decision
whose comprehensibility rests on showing a whole address, which a terminal
cannot carry. It refuses, names the cause, and points at the browser (D8).
"""

from __future__ import annotations

import pytest

from freepod import FreepodError
from freepod.deploy import preflight
from freepod.subdomain import DEPLOY_REFUSAL_CODE, explain, held, read, require

from test_deploy import Platform, deployment, project_at, run

NO_DOMAIN = {"subdomain": None, "fqdn": None, "domain": "freepod.eu"}


def without_domain(**kwargs):
    return Platform(subdomain=NO_DOMAIN, **kwargs)


# --- Reading it --------------------------------------------------------------

def test_a_held_name_is_reported(make_api):
    api, _, _ = make_api(Platform())

    assert held(read(api)) == "erik.freepod.eu"


def test_an_absent_name_is_a_value_not_an_error(make_api):
    api, _, _ = make_api(without_domain())

    assert read(api) == NO_DOMAIN
    assert held(NO_DOMAIN) is None


# --- Refusing ----------------------------------------------------------------

def test_a_create_without_a_domain_name_stops_in_preflight(make_api, tmp_path):
    platform = without_domain()
    project_at(tmp_path, values={"hostname": "myapp.erik.freepod.eu"})
    api, _, _ = make_api(platform)

    with pytest.raises(FreepodError) as raised:
        preflight(api, "prod", root=tmp_path, echo=lambda _m: None, interactive=False)

    assert "does not have a domain name" in str(raised.value)


def test_nothing_is_packed_or_built(make_api, tmp_path):
    """The refusal lands before any write, so no archive and no build exist."""
    platform = without_domain()
    project_at(tmp_path, values={"hostname": "myapp.erik.freepod.eu"})
    api, _, _ = make_api(platform)

    with pytest.raises(FreepodError):
        preflight(api, "prod", root=tmp_path, echo=lambda _m: None, interactive=False)

    assert platform.bodies == {}


def test_the_refusal_is_actionable(make_api):
    api, _, _ = make_api(without_domain())
    message = explain(api.env)

    assert "does not have a domain name" in message
    assert "permanent" in message
    assert api.env.api_base in message
    assert "Nothing has been packed, built or deployed" in message


def test_a_missing_domain_name_is_not_reported_as_something_else(make_api, tmp_path):
    platform = without_domain()
    project_at(tmp_path, values={"hostname": "myapp.erik.freepod.eu"})
    api, _, _ = make_api(platform)

    with pytest.raises(FreepodError) as raised:
        preflight(api, "prod", root=tmp_path, echo=lambda _m: None, interactive=False)

    message = str(raised.value)
    assert "terms" not in message
    assert "log in" not in message and "authenticat" not in message
    assert "invalid" not in message


def test_an_update_never_asks_for_a_domain_name(make_api, tmp_path):
    """Only a create is gated, exactly as the terms are."""
    platform = without_domain(
        reads=[
            deployment(status="ready", generation=3),
            deployment(status="ready", generation=4),
        ],
    )
    project_at(
        tmp_path,
        values={"hostname": "myapp.erik.freepod.eu"},
        pointer={"id": deployment()["id"], "name": "custom-d8dtx4"},
    )
    api, _, _ = make_api(platform)

    plan = preflight(api, "prod", root=tmp_path, echo=lambda _m: None, interactive=False)

    assert plan.deployment is not None


# --- Nothing here claims one -------------------------------------------------

def test_no_flag_claims_a_domain_name():
    from freepod.cli import cli

    flags = []
    for command in cli.commands.values():
        flags.extend(option.name for option in command.params)
    assert not any("subdomain" in name or "domain" in name for name in flags)


def test_the_client_offers_no_way_to_claim_one():
    """No command reaches the claim; the browser is the only place it is made."""
    import inspect

    from freepod import subdomain

    source = inspect.getsource(subdomain)
    assert "api.post" not in source and "POST" not in source


def test_the_platforms_own_refusal_is_recognized_by_its_code():
    """Matched by identifier, not by prose the client does not own."""
    assert DEPLOY_REFUSAL_CODE == "subdomain_required"


# --- Everything else is unaffected -------------------------------------------

def test_login_succeeds_without_a_domain_name(make_api, tmp_path, monkeypatch):
    """Authentication also serves automation and read-only use, neither of which
    a domain name is a precondition for."""
    platform = without_domain()
    api, _, _ = make_api(platform)

    assert api.me()["id"] == platform.user_id


def test_read_only_commands_are_unaffected(make_api):
    platform = without_domain()
    api, _, _ = make_api(platform)

    assert api.products()
    assert api.me()
