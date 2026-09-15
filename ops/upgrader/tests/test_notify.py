import logging
import smtplib

import pytest

from upgrader import notify
from upgrader.config import Settings
from upgrader.db import ProductResult, Run

from .test_config import FULL


class FakeSMTP:
    sent: list = []
    refuse = False

    def __init__(self, host, port, timeout):
        self.address = (host, port)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def send_message(self, message):
        if FakeSMTP.refuse:
            raise smtplib.SMTPRecipientsRefused({"owner@example.test": (550, b"no")})
        FakeSMTP.sent.append((self.address, message))


@pytest.fixture(autouse=True)
def reset():
    FakeSMTP.sent, FakeSMTP.refuse = [], False


def settings(**env):
    return Settings.from_env({**FULL, "NOTIFY_EMAIL": "owner@example.test", **env})


def run(*products, state="completed", dry_run=True):
    r = Run(id=7, trigger="scheduled", dry_run=dry_run, state=state)
    r.products = list(products)
    return r


def product(slug, outcome, **fields):
    fields.setdefault("needs_human", [])
    return ProductResult(slug=slug, outcome=outcome, current_version="1.0.0", **fields)


def test_nothing_when_everything_is_up_to_date():
    r = run(product("immich", "up_to_date"), product("nextcloud", "skipped", skip_reason="PR #9"),
            product("vaultwarden", "would_skip", skip_reason="branch exists"))
    assert notify.send(r, settings(), smtp=FakeSMTP) is False
    assert FakeSMTP.sent == []


def test_one_email_for_a_would_open_product():
    r = run(product("immich", "up_to_date"),
            product("vaultwarden", "would_open", target_version="1.37.3",
                    branch="upgrade/vaultwarden-1.37.3", draft=False))
    assert notify.send(r, settings(DASHBOARD_URL="https://upgrader.freepod.eu"), smtp=FakeSMTP)
    [(address, message)] = FakeSMTP.sent
    assert address == ("smtp.mailer.svc.cluster.local", 25)
    assert message["To"] == "owner@example.test"
    assert message["From"] == "upgrader@freepod.eu"
    body = message.get_content()
    assert "vaultwarden: would open, 1.0.0 -> 1.37.3" in body
    assert "upgrade/vaultwarden-1.37.3" in body
    assert "immich: up to date" in body
    assert "https://upgrader.freepod.eu/runs/7" in body


def test_a_draft_lists_its_decisions():
    r = run(product("immich", "opened", target_version="v4.0.0", draft=True,
                    pr_url="https://github.com/erikvanzijst/freepod/pull/130",
                    needs_human=["Confirm the node supports x86-64-v2", "Plan the v4 migration"]),
            dry_run=False)
    assert notify.send(r, settings(), smtp=FakeSMTP)
    body = FakeSMTP.sent[0][1].get_content()
    assert "Draft pull request: https://github.com/erikvanzijst/freepod/pull/130" in body
    assert "Needs a human: Confirm the node supports x86-64-v2" in body
    assert "Needs a human: Plan the v4 migration" in body


def test_a_timed_out_product_is_named():
    r = run(product("nextcloud", "timed_out"), product("immich", "up_to_date"))
    assert notify.send(r, settings(), smtp=FakeSMTP)
    assert "nextcloud: timed out" in FakeSMTP.sent[0][1].get_content()


def test_a_failure_gives_its_error():
    r = run(product("immich", "failed", error="the session ended without writing result.json"))
    assert notify.send(r, settings(), smtp=FakeSMTP)
    assert "Error: the session ended without writing result.json" in FakeSMTP.sent[0][1].get_content()


def test_nothing_without_a_recipient():
    r = run(product("vaultwarden", "would_open", branch="upgrade/x"))
    assert notify.send(r, Settings.from_env(FULL), smtp=FakeSMTP) is False
    assert FakeSMTP.sent == []


def test_nothing_for_an_interrupted_run():
    r = run(product("vaultwarden", "interrupted"), product("immich", "failed", error="x"),
            state="interrupted")
    assert notify.send(r, settings(), smtp=FakeSMTP) is False


def test_a_refused_send_is_logged_and_changes_nothing(caplog):
    FakeSMTP.refuse = True
    p = product("vaultwarden", "would_open", branch="upgrade/x")
    r = run(p)
    with caplog.at_level(logging.ERROR):
        assert notify.send(r, settings(), smtp=FakeSMTP) is False
    assert "could not send the email for run 7" in caplog.text
    assert (r.state, p.outcome) == ("completed", "would_open")


def test_an_unreachable_relay_is_logged(caplog):
    def unreachable(*args, **kwargs):
        raise ConnectionRefusedError("no relay")

    with caplog.at_level(logging.ERROR):
        assert notify.send(run(product("immich", "failed", error="x")), settings(), smtp=unreachable) is False
    assert "could not send" in caplog.text
