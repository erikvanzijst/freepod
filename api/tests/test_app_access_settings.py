"""Effective `auth` settings agree with the chart and app-auth (app-access-list D2)."""

from __future__ import annotations

import pytest

from app.services.app_access import AuthSettings, auth_settings


@pytest.mark.parametrize(
    ("system", "user", "want"),
    [
        (None, None, AuthSettings(False, "header", "anyone")),
        ({}, {"auth": {"enabled": True}}, AuthSettings(True, "header", "anyone")),
        ({"auth": {"enabled": True}}, {}, AuthSettings(True, "header", "anyone")),
        ({"auth": {"enabled": False}}, {"auth": {"enabled": True}}, AuthSettings(True, "header", "anyone")),
        ({"auth": {"enabled": True}}, {"auth": {"enabled": False}}, AuthSettings(False, "header", "anyone")),
        ({"auth": {"enabled": True, "access": "listed"}}, {}, AuthSettings(True, "header", "listed")),
        ({"auth": {"enabled": True, "access": "listed"}}, {"auth": {"access": "anyone"}}, AuthSettings(True, "header", "anyone")),
        ({"auth": {"enabled": True, "protocol": "oidc"}}, {}, AuthSettings(True, "oidc", "anyone")),
        ({"auth": {"enabled": True, "protocol": "oidc"}}, {"auth": {"protocol": "header"}}, AuthSettings(True, "header", "anyone")),
        ({}, {"auth": {"enabled": True, "protocol": "saml"}}, AuthSettings(False, "saml", "anyone")),
        ({}, {"auth": {"enabled": True, "access": "friends"}}, AuthSettings(True, "header", "listed")),
        ({}, {"auth": {"enabled": "true"}}, AuthSettings(False, "header", "anyone")),
        ({}, {"sso": {"enabled": True}}, AuthSettings(False, "header", "anyone")),
    ],
)
def test_effective_settings(system, user, want):
    assert auth_settings(system, user) == want


def test_listed_and_oidc_need_enabled():
    assert not AuthSettings(False, "header", "listed").listed
    assert not AuthSettings(False, "oidc", "anyone").oidc
    assert AuthSettings(True, "oidc", "listed").listed and AuthSettings(True, "oidc", "listed").oidc
