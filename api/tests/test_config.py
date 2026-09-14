import os

import pytest
from app.config import CaelusSettings


def test_default_values(monkeypatch):
    # Remove any CAELUS_* env vars so we test true defaults
    for key in list(os.environ):
        if key.startswith("CAELUS_"):
            monkeypatch.delenv(key)
    settings = CaelusSettings(
        _env_file=None,
    )
    assert settings.database_url == "postgresql+psycopg://caelus:caelus@localhost:5432/caelus"
    assert settings.log_level == "INFO"
    assert settings.domain == ""
    assert settings.wildcard_domains == []
    assert settings.reserved_hostnames == []


def test_env_var_loading(monkeypatch):
    monkeypatch.setenv("CAELUS_DATABASE_URL", "postgresql+psycopg://user:pw@example:5432/other")
    monkeypatch.setenv("CAELUS_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CAELUS_DOMAIN", "freepod.eu")
    settings = CaelusSettings(_env_file=None)
    assert settings.database_url == "postgresql+psycopg://user:pw@example:5432/other"
    assert settings.log_level == "DEBUG"
    assert settings.domain == "freepod.eu"


def test_list_field_json_parsing(monkeypatch):
    monkeypatch.setenv("CAELUS_WILDCARD_DOMAINS", '["app.deprutser.be","apps.example.com"]')
    monkeypatch.setenv("CAELUS_RESERVED_HOSTNAMES", '["smtp.app.deprutser.be"]')
    settings = CaelusSettings(_env_file=None)
    assert settings.wildcard_domains == ["app.deprutser.be", "apps.example.com"]
    assert settings.reserved_hostnames == ["smtp.app.deprutser.be"]


def test_var_encryption_keys_are_comma_separated(monkeypatch):
    """Unlike the other list fields, this one is not JSON.

    It arrives from a Kubernetes Secret an operator edits by hand, where a
    mistyped bracket costs the readability of every stored var. A Fernet key
    is urlsafe base64, so it never contains a comma.
    """
    monkeypatch.setenv("CAELUS_VAR_ENCRYPTION_KEYS", " newest= , older= ")
    settings = CaelusSettings(_env_file=None)
    assert settings.var_encryption_keys == ["newest=", "older="]


def test_var_encryption_keys_default_to_empty(monkeypatch):
    monkeypatch.delenv("CAELUS_VAR_ENCRYPTION_KEYS", raising=False)
    assert CaelusSettings(_env_file=None).var_encryption_keys == []


def test_tenant_db_settings_default_to_absent(monkeypatch):
    """A product that has not opted in never reads these, so nothing may
    require them at startup: an environment with no tenant cluster -- and every
    migration, test and CLI invocation -- must still construct settings."""
    for key in list(os.environ):
        if key.startswith("CAELUS_TENANT_DB_"):
            monkeypatch.delenv(key)
    settings = CaelusSettings(_env_file=None)
    assert settings.tenant_db_host == ""
    assert settings.tenant_db_admin_password == ""
    assert settings.tenant_db_pooler_host == ""
    # The names and ports are conventions, not per-environment facts, so they
    # carry defaults while the addresses and the credential do not.
    assert settings.tenant_db_port == 5432
    assert settings.tenant_db_admin_user == "caelus_admin"
    assert settings.tenant_db_maintenance_db == "postgres"
    assert settings.tenant_db_pooler_port == 6432


def test_tenant_db_settings_from_env(monkeypatch):
    monkeypatch.setenv("CAELUS_TENANT_DB_HOST", "caelus-tenant-postgres.caelus-dev.svc.cluster.local")
    monkeypatch.setenv("CAELUS_TENANT_DB_ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("CAELUS_TENANT_DB_POOLER_HOST", "caelus-tenant-pooler.caelus-dev.svc.cluster.local")
    monkeypatch.setenv("CAELUS_TENANT_DB_POOLER_PORT", "6432")
    settings = CaelusSettings(_env_file=None)
    assert settings.tenant_db_host == "caelus-tenant-postgres.caelus-dev.svc.cluster.local"
    assert settings.tenant_db_admin_password == "s3cret"
    assert settings.tenant_db_pooler_host == "caelus-tenant-pooler.caelus-dev.svc.cluster.local"
    assert settings.tenant_db_pooler_port == 6432


def test_registry_settings_default_to_absent(monkeypatch):
    for key in list(os.environ):
        if key.startswith("CAELUS_REGISTRY_"):
            monkeypatch.delenv(key)
    settings = CaelusSettings(_env_file=None)
    assert settings.registry_host == ""
    assert settings.registry_token_issuer == ""
    assert settings.registry_signing_private_key == ""
    assert settings.registry_pull_hmac_key == ""


def test_registry_signing_key_survives_the_environment(monkeypatch):
    """The PEM arrives through a Secret's env_from, newlines and all."""
    from app.services import registry_tokens

    key = registry_tokens.generate_private_key()
    monkeypatch.setenv("CAELUS_REGISTRY_SIGNING_PRIVATE_KEY", registry_tokens.private_key_pem(key))
    loaded = registry_tokens.load_private_key(
        CaelusSettings(_env_file=None).registry_signing_private_key
    )
    assert registry_tokens.key_id(loaded.public_key()) == registry_tokens.key_id(key.public_key())


def test_environment_defaults_to_dev(monkeypatch):
    """An unconfigured platform is never production."""
    monkeypatch.delenv("CAELUS_ENVIRONMENT", raising=False)
    assert CaelusSettings(_env_file=None).environment == "dev"


def test_environment_from_env(monkeypatch):
    monkeypatch.setenv("CAELUS_ENVIRONMENT", "prod")
    assert CaelusSettings(_env_file=None).environment == "prod"


def test_static_path_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CAELUS_STATIC_PATH", str(tmp_path))
    settings = CaelusSettings(_env_file=None)
    assert settings.static_path == tmp_path


def test_legacy_database_url_not_read(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://old-host/old-db")
    monkeypatch.delenv("CAELUS_DATABASE_URL", raising=False)
    settings = CaelusSettings(_env_file=None)
    assert settings.database_url == "postgresql+psycopg://caelus:caelus@localhost:5432/caelus"


def test_get_settings_is_cached():
    from app.config import get_settings

    get_settings.cache_clear()
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
    get_settings.cache_clear()
