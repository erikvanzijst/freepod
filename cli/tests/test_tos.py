"""Terms of Service acceptance, in `login` and in deploy preflight."""

from __future__ import annotations

import pytest

from freepod import FreepodError
from freepod.deploy import preflight
from freepod.tos import (
    ACCEPTED,
    AGREEMENT,
    DECLINED,
    DOCUMENTS,
    NO_TERMINAL,
    VERSION_UNKNOWN,
    accepted,
    current_version,
    document_urls,
    read,
    require,
    settle,
)

from test_deploy import TOS_VERSION, Platform, project_at, run

UI_COPY = (
    "I agree to the Freepod Terms of Service and Acceptable Use Policy, and "
    "acknowledge the Privacy Policy."
)


def unaccepted(**kwargs):
    return Platform(tos_version=None, **kwargs)


class Asker:
    """Stands in for the confirmation prompt, recording what it was shown."""

    def __init__(self, answer=True):
        self.answer = answer
        self.questions = []

    def __call__(self, question):
        self.questions.append(question)
        return self.answer


# --------------------------------------------------------------------------
# The document
# --------------------------------------------------------------------------


def test_the_prompt_is_the_web_uis_copy_verbatim():
    """The wording is the consent record. Paraphrasing it in a second client
    would mean two users agreed to two different sentences."""
    assert AGREEMENT == UI_COPY


def test_all_three_documents_are_named_and_linked(env):
    urls = document_urls(env)

    assert [title for title, _ in urls] == [
        "Terms of Service",
        "Acceptable Use Policy",
        "Privacy Policy",
    ]
    assert [url for _, url in urls] == [
        "https://freepod.eu/legal/terms",
        "https://freepod.eu/legal/aup",
        "https://freepod.eu/legal/privacy",
    ]


def test_the_documents_are_linked_on_the_environment_being_deployed_to(dev_env):
    """A dev deploy must not point at production's terms."""
    assert all("dev.freepod.eu" in url for _, url in document_urls(dev_env))


def test_an_unaccepted_account_is_a_document_not_an_error(make_api):
    """The platform models 'not accepted' as a 200 with null fields."""
    api, _, _ = make_api(unaccepted())

    record = read(api)

    assert record["version"] is None
    assert accepted(record) is False
    assert current_version(record) == TOS_VERSION


# --------------------------------------------------------------------------
# The version is learned, never carried
# --------------------------------------------------------------------------


def test_the_accepted_version_is_whatever_the_platform_reports(make_api):
    """Never a constant in this client: it is a release constant of the *API*
    image, and a stale copy would 409 every user until they upgraded."""
    api, _, _ = make_api(unaccepted(tos_current="2031-12-25"))
    asker = Asker(answer=True)

    assert settle(api, echo=lambda _m: None, ask=asker) == ACCEPTED


def test_no_terms_version_is_hardcoded_in_the_client():
    """The counterpart of `test_no_other_platform_bound_is_hardcoded`: a date
    literal here is the bug this whole indirection exists to prevent."""
    import re
    from pathlib import Path

    import freepod

    root = Path(freepod.__file__).parent
    for module in root.glob("*.py"):
        found = re.findall(r"\b(20\d\d-\d\d-\d\d)\b", module.read_text())
        assert not found, f"{module.name} carries a hardcoded date: {found}"


def test_an_api_that_does_not_report_the_version_offers_nothing(make_api, env):
    """Submitting a guessed version is precisely the 409 being guarded against,
    so nothing is shown and nothing is asked."""
    api, recorder, _ = make_api(unaccepted(tos_current=None))
    said = []
    asker = Asker(answer=True)

    assert settle(api, echo=said.append, ask=asker) == VERSION_UNKNOWN

    assert asker.questions == []
    assert said == []
    assert "POST" not in [r.method for r in recorder.requests]


def test_an_unreported_version_is_not_blamed_on_the_user(env):
    """The user may well have agreed. Reporting a platform gap as a decline
    tells them to change an answer that was never the problem."""
    from freepod.tos import explain

    message = explain(VERSION_UNKNOWN, env)

    assert "does not report which version" in message
    assert env.api_base in message
    assert "not accepted" not in message


def test_a_changed_version_between_reading_and_accepting_is_reported(make_api):
    api, _, _ = make_api(unaccepted(tos_post_status=409))

    with pytest.raises(FreepodError) as raised:
        settle(api, echo=lambda _m: None, ask=Asker(answer=True))

    assert "the terms changed" in str(raised.value)


# --------------------------------------------------------------------------
# Accepting
# --------------------------------------------------------------------------


def test_accepting_records_the_version_the_platform_reported(make_api):
    platform = unaccepted()
    api, _, _ = make_api(platform)

    assert settle(api, echo=lambda _m: None, ask=Asker(answer=True)) == ACCEPTED
    assert platform.bodies["tos"] == {"version": TOS_VERSION}


def test_an_account_on_an_older_version_is_not_re_prompted(make_api):
    """Deliberate, not an oversight. The platform's deploy gate is
    `tos_accepted_version is not None` — it does not compare versions — so
    re-prompting here would block a deploy the platform would happily accept,
    and would do it in a client the platform never asked to enforce anything.

    The client now has both values and could implement re-approval the moment
    the platform requires it. Until then, refusing on its own initiative is the
    client inventing policy.
    """
    platform = Platform(tos_version="2026-01-01", tos_current="2026-07-01")
    api, _, _ = make_api(platform)
    asker = Asker()

    assert settle(api, echo=lambda _m: None, ask=asker) == ACCEPTED
    assert asker.questions == []
    assert "tos" not in platform.bodies


def test_an_already_accepted_account_is_never_asked(make_api):
    platform = Platform()
    api, _, _ = make_api(platform)
    asker = Asker()

    assert settle(api, echo=lambda _m: None, ask=asker) == ACCEPTED
    assert asker.questions == []
    assert "tos" not in platform.bodies


def test_declining_records_nothing(make_api):
    platform = unaccepted()
    api, _, _ = make_api(platform)

    assert settle(api, echo=lambda _m: None, ask=Asker(answer=False)) == DECLINED
    assert "tos" not in platform.bodies


def test_the_documents_are_shown_before_the_question(make_api):
    """Nobody can agree to something they were not offered."""
    api, _, _ = make_api(unaccepted())
    said = []

    settle(api, echo=said.append, ask=Asker(answer=True))

    shown = "\n".join(said)
    for title, _ in DOCUMENTS:
        assert title in shown


def test_a_non_interactive_run_neither_asks_nor_accepts(make_api):
    platform = unaccepted()
    api, _, _ = make_api(platform)
    asker = Asker()

    assert settle(api, interactive=False, echo=lambda _m: None, ask=asker) == NO_TERMINAL
    assert asker.questions == []
    assert "tos" not in platform.bodies


# --------------------------------------------------------------------------
# `require` — the deploy gate
# --------------------------------------------------------------------------


def test_require_passes_once_accepted(make_api):
    api, _, _ = make_api(unaccepted())
    require(api, echo=lambda _m: None, ask=Asker(answer=True))


def test_require_refuses_a_decline_and_says_nothing_was_built(make_api):
    api, _, _ = make_api(unaccepted())

    with pytest.raises(FreepodError) as raised:
        require(api, echo=lambda _m: None, ask=Asker(answer=False))

    assert "nothing" in str(raised.value).lower()


def test_require_without_a_terminal_names_how_to_accept(make_api):
    api, _, _ = make_api(unaccepted())

    with pytest.raises(FreepodError) as raised:
        require(api, interactive=False, echo=lambda _m: None)

    assert "freepod login" in str(raised.value)


# --------------------------------------------------------------------------
# Preflight integration
# --------------------------------------------------------------------------


def test_an_unaccepted_first_deploy_is_stopped_before_anything_is_built(
    make_api, tmp_path, monkeypatch
):
    """The platform's own refusal is a 400 from the *create* call, which
    arrives after the archive is packed, uploaded, and built."""
    platform = unaccepted()
    project_at(tmp_path)
    monkeypatch.setattr("click.confirm", lambda *a, **k: False)

    with pytest.raises(FreepodError):
        run(make_api, platform, tmp_path)

    assert "/api/artifacts" not in platform.paths()
    assert f"/api/users/7/builds" not in platform.paths()


def test_a_headless_deploy_fails_rather_than_skipping_the_check(make_api, tmp_path):
    """No automation bypass, by design. A deploy with no terminal cannot ask,
    and the answer to "cannot ask" is to stop — never to proceed unaccepted.
    There is deliberately no flag that accepts on the operator's behalf.
    """
    platform = unaccepted()
    project_at(tmp_path)

    with pytest.raises(FreepodError) as raised:
        run(make_api, platform, tmp_path, interactive=False)

    assert "has not accepted" in str(raised.value)
    # Not a warning, not a skip: nothing whatsoever was spent.
    assert "/api/artifacts" not in platform.paths()
    assert f"/api/users/7/builds" not in platform.paths()
    assert "tos" not in platform.bodies
    assert not any(m == "POST" and "deployments" in p for m, p in platform.calls)


def test_no_flag_accepts_the_terms_on_the_operators_behalf(make_api, tmp_path):
    """The counterpart of the test above, stated as a property of the surface:
    consent is only ever recorded from an affirmative answer to the prompt.
    """
    from freepod.cli import cli

    flags = []
    for command in cli.commands.values():
        flags.extend(option.name for option in command.params)
    assert not any("accept" in name or "tos" in name or "terms" in name for name in flags)


def test_the_terms_are_settled_before_any_value_is_asked_for(make_api, tmp_path):
    """Collecting a hostname first would ask for work a decline then discards.

    The project carries no hostname *and* no acceptance, so both checks would
    fire. Whichever runs first is the one that reports.
    """
    platform = unaccepted()
    project_at(tmp_path, values={})
    api, _, _ = make_api(platform)

    with pytest.raises(FreepodError) as raised:
        preflight(api, "prod", root=tmp_path, echo=lambda _m: None, interactive=False)

    assert "accepted the Freepod terms" in str(raised.value)
    assert "hostname" not in str(raised.value)


def test_an_update_never_asks_about_the_terms(make_api, tmp_path):
    """Only a create is gated. Asking on every deploy would nag for a fact the
    platform records once, and the answer could not change the outcome."""
    from test_deploy import deployment

    platform = unaccepted(
        reads=[
            deployment(status="ready", generation=3),
            deployment(status="ready", generation=4),
        ],
        update=deployment(status="provisioning", generation=4),
    )
    project_at(tmp_path, pointer={"id": deployment()["id"], "name": "custom-d8dtx4"})

    run(make_api, platform, tmp_path)

    assert "/api/me/tos-acceptance" not in platform.paths()


def test_the_terms_are_only_settled_after_the_cheap_reads_refuse(make_api, tmp_path):
    """An instance with no free plan can never deploy, so asking anyone to
    accept terms for it is a question with no useful answer."""
    platform = unaccepted(plans=[])
    project_at(tmp_path)

    with pytest.raises(FreepodError) as raised:
        run(make_api, platform, tmp_path)

    assert "publishes no plans" in str(raised.value)
    assert "/api/me/tos-acceptance" not in platform.paths()


def test_a_create_refused_for_the_terms_is_not_reported_as_bad_values(
    make_api, tmp_path
):
    """The backstop for the race where acceptance is withdrawn mid-deploy. A
    generic 400 would send the user to edit a file that is already correct."""
    platform = Platform(
        create_status=400,
        create_detail="Terms of Service must be accepted before deploying",
    )
    project_at(tmp_path)

    with pytest.raises(FreepodError) as raised:
        run(make_api, platform, tmp_path)

    message = str(raised.value)
    assert "has not accepted its terms" in message
    assert "freepod login" in message
    # Creation precedes the build now, so nothing was built to lose.
    assert not any("/builds" in path for _method, path in platform.calls)
