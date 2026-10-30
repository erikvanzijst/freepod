"""OIDC client secrets are derived exactly as app-auth verifies them."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.config import CaelusSettings
from app.services import app_auth_oidc

# Shared with daemons/app-auth/client_test.go: if either side changes the
# derivation, both tests fail.
VECTOR_KEY = "v1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
VECTOR_ID = "3d6f0a8e-1b2c-4d5e-8f90-a1b2c3d4e5f6"
VECTOR_SECRET = "nBv_vmyY6kRCnevk9TnrVr_5g2I008el3tTzhNkDr38"


def _use_keys(monkeypatch, keys: str) -> None:
    settings = CaelusSettings(app_auth_oidc_client_keys=keys, _env_file=None)
    monkeypatch.setattr("app.services.app_auth_oidc.get_settings", lambda: settings)


def test_the_shared_vector(monkeypatch):
    _use_keys(monkeypatch, VECTOR_KEY)
    assert app_auth_oidc.oidc_client_secret(UUID(VECTOR_ID)) == VECTOR_SECRET


def test_the_first_key_derives(monkeypatch):
    _use_keys(monkeypatch, "v2:" + "eno" * 16 + "," + VECTOR_KEY)
    assert app_auth_oidc.oidc_client_secret(UUID(VECTOR_ID)) != VECTOR_SECRET


def test_the_client_id_is_the_canonical_uuid():
    assert app_auth_oidc.client_id(UUID(VECTOR_ID.upper())) == VECTOR_ID


@pytest.mark.parametrize(
    "spec",
    ["", "nokey", "v1:not base64!", "v1:" + "AAAA", "a.b:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="],
)
def test_keyrings_app_auth_would_refuse_are_refused(spec):
    with pytest.raises(ValueError):
        app_auth_oidc.parse_keyring(spec)
