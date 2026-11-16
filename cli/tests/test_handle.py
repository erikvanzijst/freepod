"""The handle an account's hostnames end in, in deploy preflight.

The client never claims one: choosing it is a one-time, irreversible decision
whose comprehensibility rests on showing a whole address, which a terminal
cannot carry. It refuses, names the cause, and points at the browser.
"""

from __future__ import annotations


from freepod.deploy import preflight
from freepod.handle import explain, read, suffix

from test_deploy import Platform, deployment, project_at

NO_HANDLE = {"handle": None, "suffix": None, "domain": "freepod.app"}


def without_handle(**kwargs):
    return Platform(handle=NO_HANDLE, **kwargs)


# --- Reading it --------------------------------------------------------------

def test_a_held_handle_reports_its_suffix(make_api):
    api, _, _ = make_api(Platform())

    assert suffix(read(api)) == "-erik.freepod.app"


def test_an_absent_handle_is_a_value_not_an_error(make_api):
    api, _, _ = make_api(without_handle())

    assert read(api) == NO_HANDLE
    assert suffix(NO_HANDLE) is None


# --- Refusing ----------------------------------------------------------------

def test_the_refusal_is_actionable(make_api):
    api, _, _ = make_api(without_handle())
    message = explain(api.env)

    assert "does not have a handle" in message
    assert "permanent" in message
    assert api.env.api_base in message
    assert "Nothing has been packed, built or deployed" in message


def test_an_update_never_asks_for_a_handle(make_api, tmp_path):
    """Only a create is gated, exactly as the terms are."""
    platform = without_handle(
        reads=[
            deployment(status="ready", generation=3),
            deployment(status="ready", generation=4),
        ],
    )
    project_at(
        tmp_path,
        values={"hostname": "myapp"},
        pointer={"id": deployment()["id"], "name": "custom-d8dtx4"},
    )
    api, _, _ = make_api(platform)

    plan = preflight(api, "prod", root=tmp_path, echo=lambda _m: None, interactive=False)

    assert plan.deployment is not None


# --- Nothing here claims one -------------------------------------------------

def test_no_flag_claims_a_handle():
    from freepod.cli import cli

    flags = []
    for command in cli.commands.values():
        flags.extend(option.name for option in command.params)
    assert not any("handle" in name or "domain" in name for name in flags)


def test_the_client_offers_no_way_to_claim_one():
    """No command reaches the claim; the browser is the only place it is made."""
    import inspect

    from freepod import handle

    source = inspect.getsource(handle)
    assert "api.post" not in source and "POST" not in source


# --- Everything else is unaffected -------------------------------------------

def test_login_succeeds_without_a_handle(make_api, tmp_path, monkeypatch):
    """Authentication also serves automation and read-only use, neither of which
    a handle is a precondition for."""
    platform = without_handle()
    api, _, _ = make_api(platform)

    assert api.me()["id"] == platform.user_id


def test_read_only_commands_are_unaffected(make_api):
    platform = without_handle()
    api, _, _ = make_api(platform)

    assert api.products()
    assert api.me()
