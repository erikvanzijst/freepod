"""The var encryption keyring: fingerprints, rotation, and the startup checks.

Nothing here depends on the parent rows, but `deployment_var.deployment_id` is
a real foreign key, so the `author` fixture builds a deployment to hang the
vars off.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlmodel import Session, select

from app.config import CaelusSettings
from app.models import (
    DeploymentDatabaseORM,
    DeploymentVarORM,
    ProductTemplateVersionORM,
    ProductORM,
    UserORM,
)
from app.models.core import _utcnow
from app.services import var_crypto
from app.services.var_crypto import (
    ENCRYPTED_COLUMNS,
    Keyring,
    VarEncryptionException,
    key_fingerprint,
    rotate_encrypted_values,
    verify_keyring,
)
from tests.conftest import db_session, make_deployment_with_release  # noqa: F401


KEY_A = Fernet.generate_key().decode()
KEY_B = Fernet.generate_key().decode()
KEY_C = Fernet.generate_key().decode()


@pytest.fixture
def author(db_session):
    """The user writing the vars, plus a deployment for them to belong to."""
    token = uuid4().hex[:8]
    user = UserORM(email=f"vars-{token}@example.com")
    product = ProductORM(name=f"vars-product-{token}", created_at=_utcnow())
    db_session.add(user)
    db_session.add(product)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(product)

    template = ProductTemplateVersionORM(
        product_id=product.id, chart_ref="oci://example/chart", chart_version="1.0.0"
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    deployment = make_deployment_with_release(
        db_session,
        user_id=user.id,
        desired_template_id=template.id,
        hostname=f"{token}.example.test",
        name=f"app-{token}",
        namespace=f"ns-{token}",
    )
    db_session.commit()
    db_session.refresh(deployment)
    return SimpleNamespace(id=user.id, user=user, deployment_id=deployment.id)


@pytest.fixture
def keyring_settings(monkeypatch):
    """Point `get_settings` (and the cached keyring) at an explicit key list."""

    def configure(keys: list[str]) -> None:
        monkeypatch.setattr(
            "app.services.var_crypto.get_settings",
            lambda: CaelusSettings(var_encryption_keys=keys, _env_file=None),
        )
        var_crypto.get_keyring.cache_clear()

    yield configure
    var_crypto.get_keyring.cache_clear()


def _add_var(session, author, *, key, value_encrypted, key_id, deployment_id=None):
    row = DeploymentVarORM(
        deployment_id=deployment_id or author.deployment_id,
        key=key,
        value_encrypted=value_encrypted,
        key_id=key_id,
        created_by=author.id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _add_database(session, author, *, password_encrypted, key_id):
    """The keyring's second encrypted column: a tenant's database password."""
    name = "dpl_" + author.deployment_id.hex
    row = DeploymentDatabaseORM(
        deployment_id=author.deployment_id,
        db_name=name,
        role_name=name,
        password_encrypted=password_encrypted,
        key_id=key_id,
        created_at=_utcnow(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ── The registry ──────────────────────────────────────────────────────────


def test_every_encrypted_column_in_the_schema_is_registered():
    """The gap this registry exists to close is a column nobody declared.

    Such a column passes the startup check and is skipped by rotation, so it
    strands its plaintext the moment its key is retired -- by an operator
    following the documented procedure correctly. Anything in the schema
    carrying a `key_id` must therefore be registered here.
    """
    from sqlmodel import SQLModel

    import app.models  # noqa: F401  (registers every table)

    with_key_id = {
        name for name, table in SQLModel.metadata.tables.items() if "key_id" in table.columns
    }
    assert with_key_id == {column.table for column in ENCRYPTED_COLUMNS}


# ── Fingerprints and round-tripping ───────────────────────────────────────


def test_round_trip():
    keyring = Keyring([KEY_A])
    ciphertext, key_id = keyring.encrypt("hunter2")
    assert ciphertext != "hunter2"
    assert keyring.decrypt(ciphertext, key_id) == "hunter2"


def test_fingerprint_is_stable_and_independent_of_position():
    """The whole point of a fingerprint: it names the key, not its slot.

    A positional identifier would be destroyed by the operation it exists to
    support -- rotation prepends, which would renumber every historical row.
    """
    assert key_fingerprint(KEY_A) == key_fingerprint(KEY_A)
    assert len(key_fingerprint(KEY_A)) == 8
    assert key_fingerprint(KEY_A) != key_fingerprint(KEY_B)

    first = Keyring([KEY_A, KEY_B]).key_ids
    prepended = Keyring([KEY_C, KEY_A, KEY_B]).key_ids
    assert first == [key_fingerprint(KEY_A), key_fingerprint(KEY_B)]
    assert prepended[1:] == first


def test_prepending_a_key_leaves_existing_values_readable():
    old = Keyring([KEY_A])
    ciphertext, key_id = old.encrypt("hunter2")

    rotated = Keyring([KEY_B, KEY_A])
    assert rotated.current_key_id() == key_fingerprint(KEY_B)
    # The row is untouched: same ciphertext, same key_id, still readable.
    assert rotated.decrypt(ciphertext, key_id) == "hunter2"
    assert key_id == key_fingerprint(KEY_A)
    # And new writes use the new key.
    _, new_key_id = rotated.encrypt("hunter2")
    assert new_key_id == key_fingerprint(KEY_B)


def test_dropping_a_key_names_the_missing_fingerprint():
    ciphertext, key_id = Keyring([KEY_A]).encrypt("hunter2")
    with pytest.raises(VarEncryptionException) as exc:
        Keyring([KEY_B]).decrypt(ciphertext, key_id)
    assert key_id in str(exc.value)


def test_empty_keyring_cannot_encrypt():
    with pytest.raises(VarEncryptionException):
        Keyring([]).encrypt("hunter2")


def test_a_colliding_key_list_is_rejected_at_construction():
    with pytest.raises(VarEncryptionException) as exc:
        Keyring([KEY_A, KEY_A])
    assert key_fingerprint(KEY_A) in str(exc.value)


# ── Startup verification ──────────────────────────────────────────────────


def test_verify_passes_on_an_empty_store(db_session, keyring_settings):
    keyring_settings([KEY_A])
    verify_keyring(db_session)


def test_verify_names_the_migration_when_the_table_is_missing(
    test_database, keyring_settings
):
    """The first thing anyone pulling this branch hits is a stale database.

    A throwaway schema holding every table *except* the var tables stands in
    for a database that has not been migrated far enough. Same
    `search_path` trick the migration tests use.
    """
    from sqlalchemy import create_engine, text
    from sqlmodel import SQLModel

    schema = f"stale_{uuid4().hex[:8]}"
    with test_database.engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    stale = create_engine(
        test_database.engine.url,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    try:
        SQLModel.metadata.create_all(
            stale,
            tables=[
                table
                for name, table in SQLModel.metadata.tables.items()
                if name not in ("deployment_var", "release_var")
            ],
        )
        keyring_settings([KEY_A])
        with Session(stale) as session:
            with pytest.raises(VarEncryptionException) as exc:
                verify_keyring(session)
        assert "alembic upgrade head" in str(exc.value)
    finally:
        stale.dispose()
        with test_database.engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def test_verify_fails_on_a_fingerprint_collision(db_session, keyring_settings):
    keyring_settings([KEY_A, KEY_A])
    with pytest.raises(VarEncryptionException):
        verify_keyring(db_session)


def test_verify_fails_when_a_stored_key_is_not_configured(
    db_session, author, keyring_settings
):
    keyring_settings([KEY_A])
    ciphertext, key_id = var_crypto.encrypt("hunter2")
    _add_var(db_session, author, key="TOKEN", value_encrypted=ciphertext, key_id=key_id)

    keyring_settings([KEY_B])
    with pytest.raises(VarEncryptionException) as exc:
        verify_keyring(db_session)
    assert key_id in str(exc.value)


def test_verify_ignores_tombstones(db_session, author, keyring_settings):
    """A tombstone names no key, so it can never make the keyring insufficient."""
    keyring_settings([KEY_A])
    _add_var(db_session, author, key="TOKEN", value_encrypted=None, key_id=None)
    keyring_settings([KEY_B])
    verify_keyring(db_session)


def test_verify_fails_on_an_empty_keyring_when_a_template_declares_vars(
    db_session, keyring_settings
):
    product = ProductORM(name=f"p-{uuid4().hex[:8]}", created_at=_utcnow())
    db_session.add(product)
    db_session.commit()
    template = ProductTemplateVersionORM(
        product_id=product.id,
        chart_ref="oci://example/chart",
        chart_version="1.0.0",
        values_schema_json={
            "type": "object",
            "additionalProperties": False,
            "properties": {"ADMIN_TOKEN": {"type": "string", "x-caelus-target": "runtime"}},
        },
    )
    db_session.add(template)
    db_session.commit()

    keyring_settings([])
    with pytest.raises(VarEncryptionException) as exc:
        verify_keyring(db_session)
    assert str(template.id) in str(exc.value)

    # A key configured, and the same store verifies.
    keyring_settings([KEY_A])
    verify_keyring(db_session)


def test_empty_keyring_is_fine_when_no_template_declares_vars(
    db_session, keyring_settings
):
    product = ProductORM(name=f"p-{uuid4().hex[:8]}", created_at=_utcnow())
    db_session.add(product)
    db_session.commit()
    db_session.add(
        ProductTemplateVersionORM(
            product_id=product.id,
            chart_ref="oci://example/chart",
            chart_version="1.0.0",
            values_schema_json={"type": "object", "additionalProperties": False, "properties": {"replicas": {"type": "integer"}}},
        )
    )
    db_session.commit()

    keyring_settings([])
    verify_keyring(db_session)


def test_a_deleted_template_does_not_force_a_keyring(db_session, keyring_settings):
    product = ProductORM(name=f"p-{uuid4().hex[:8]}", created_at=_utcnow())
    db_session.add(product)
    db_session.commit()
    db_session.add(
        ProductTemplateVersionORM(
            product_id=product.id,
            chart_ref="oci://example/chart",
            chart_version="1.0.0",
            deleted_at=_utcnow(),
            values_schema_json={
                "type": "object",
                "additionalProperties": False,
                "properties": {"ADMIN_TOKEN": {"type": "string", "x-caelus-target": "runtime"}},
            },
        )
    )
    db_session.commit()

    keyring_settings([])
    verify_keyring(db_session)


def test_verify_fails_when_a_database_password_names_an_unconfigured_key(
    db_session, author, keyring_settings
):
    """The failure D4 is written to prevent: a key retired while tenant
    passwords still name it. Before the registry, only vars were checked, so
    this passed startup and surfaced inside a reconcile instead."""
    keyring_settings([KEY_A])
    ciphertext, key_id = var_crypto.encrypt("tenant-password")
    _add_database(db_session, author, password_encrypted=ciphertext, key_id=key_id)

    keyring_settings([KEY_B])
    with pytest.raises(VarEncryptionException) as exc:
        verify_keyring(db_session)
    assert key_id in str(exc.value)
    assert "deployment_database" in str(exc.value)


def test_verify_reports_every_column_that_cannot_be_read(
    db_session, author, keyring_settings
):
    """One rollout, one message: an operator fixing a key list needs to see
    everything it strands, not the first table alphabetically."""
    keyring_settings([KEY_A])
    var_ciphertext, key_id = var_crypto.encrypt("hunter2")
    _add_var(db_session, author, key="TOKEN", value_encrypted=var_ciphertext, key_id=key_id)
    db_ciphertext, _ = var_crypto.encrypt("tenant-password")
    _add_database(db_session, author, password_encrypted=db_ciphertext, key_id=key_id)

    keyring_settings([KEY_B])
    with pytest.raises(VarEncryptionException) as exc:
        verify_keyring(db_session)
    assert "deployment_var.value_encrypted" in str(exc.value)
    assert "deployment_database.password_encrypted" in str(exc.value)


def test_empty_keyring_is_fatal_once_a_database_password_is_stored(
    db_session, author, keyring_settings
):
    """Not only when a template declares vars. A stored password is a secret
    nothing can reproduce -- PostgreSQL keeps only a SCRAM verifier -- so a
    process that cannot read it must refuse to start rather than defer the
    failure into somebody's reconcile."""
    keyring_settings([KEY_A])
    ciphertext, key_id = var_crypto.encrypt("tenant-password")
    _add_database(db_session, author, password_encrypted=ciphertext, key_id=key_id)

    keyring_settings([])
    with pytest.raises(VarEncryptionException) as exc:
        verify_keyring(db_session)
    message = str(exc.value)
    assert "CAELUS_VAR_ENCRYPTION_KEYS is empty" in message
    assert "deployment_database.password_encrypted" in message


def test_the_api_refuses_to_start_on_a_stranded_database_password(
    db_session, author, keyring_settings
):
    """The check has to bite where a human is watching: process startup."""
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app as fastapi_app

    keyring_settings([KEY_A])
    ciphertext, key_id = var_crypto.encrypt("tenant-password")
    _add_database(db_session, author, password_encrypted=ciphertext, key_id=key_id)
    keyring_settings([KEY_B])

    # A generator, like the real dependency: the lifespan closes what it opens.
    def _session():
        yield db_session

    fastapi_app.dependency_overrides[get_session] = _session
    try:
        with pytest.raises(VarEncryptionException) as exc:
            with TestClient(fastapi_app):
                pass
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)
    assert key_id in str(exc.value)


def test_the_worker_refuses_to_start_on_a_stranded_database_password(
    cli_runner, db_session, author, keyring_settings
):
    """`caelus worker` runs the same gate before it claims a single job."""
    runner, cli_app = cli_runner
    keyring_settings([KEY_A])
    ciphertext, key_id = var_crypto.encrypt("tenant-password")
    _add_database(db_session, author, password_encrypted=ciphertext, key_id=key_id)
    keyring_settings([KEY_B])

    result = runner.invoke(cli_app, ["worker"])
    assert result.exit_code != 0
    assert key_id in (getattr(result, "stderr", "") or result.output)


# ── Rotation ──────────────────────────────────────────────────────────────


def test_rotation_rewrites_representation_and_preserves_plaintext(
    db_session, author, keyring_settings
):
    keyring_settings([KEY_A])
    rows = []
    for name in ("ONE", "TWO", "THREE"):
        ciphertext, key_id = var_crypto.encrypt(f"value-{name}")
        rows.append(
            _add_var(db_session, author, key=name, value_encrypted=ciphertext, key_id=key_id)
        )
    original_ids = [row.id for row in rows]

    keyring_settings([KEY_B, KEY_A])
    assert rotate_encrypted_values(db_session, batch_size=2) == 3

    for row, original_id in zip(rows, original_ids):
        db_session.refresh(row)
        assert row.id == original_id, "rotation must not move a row in history"
        assert row.key_id == key_fingerprint(KEY_B)
        assert var_crypto.decrypt(row.value_encrypted, row.key_id) == f"value-{row.key}"

    # Nothing left to do, and saying so is how an operator knows KEY_A can go.
    assert rotate_encrypted_values(db_session) == 0


def test_a_half_swept_table_is_fully_readable(db_session, author, keyring_settings):
    """Interrupting the sweep is safe: every row still names its own key."""
    keyring_settings([KEY_A])
    for name in ("ONE", "TWO", "THREE"):
        ciphertext, key_id = var_crypto.encrypt(f"value-{name}")
        _add_var(db_session, author, key=name, value_encrypted=ciphertext, key_id=key_id)

    keyring_settings([KEY_B, KEY_A])

    class Interrupted(Exception):
        pass

    def stop_after_first_batch(rotated: int) -> None:
        raise Interrupted

    with pytest.raises(Interrupted):
        rotate_encrypted_values(db_session, batch_size=1, on_batch=stop_after_first_batch)

    rows = db_session.exec(select(DeploymentVarORM).order_by(DeploymentVarORM.id)).all()
    assert {row.key_id for row in rows} == {key_fingerprint(KEY_A), key_fingerprint(KEY_B)}
    for row in rows:
        assert var_crypto.decrypt(row.value_encrypted, row.key_id) == f"value-{row.key}"

    # Resuming finishes the job; the interrupted batch is not redone.
    assert rotate_encrypted_values(db_session) == 2
    assert verify_keyring(db_session) is None


def test_rotation_covers_every_registered_column(db_session, author, keyring_settings):
    """A sweep that missed a column would report zero while rows still named
    the old key -- exactly the state in which retiring it destroys data."""
    keyring_settings([KEY_A])
    var_ciphertext, key_id = var_crypto.encrypt("hunter2")
    var_row = _add_var(
        db_session, author, key="TOKEN", value_encrypted=var_ciphertext, key_id=key_id
    )
    db_ciphertext, _ = var_crypto.encrypt("tenant-password")
    db_row = _add_database(db_session, author, password_encrypted=db_ciphertext, key_id=key_id)

    keyring_settings([KEY_B, KEY_A])
    assert rotate_encrypted_values(db_session) == 2

    db_session.refresh(var_row)
    db_session.refresh(db_row)
    assert var_row.key_id == key_fingerprint(KEY_B)
    assert db_row.key_id == key_fingerprint(KEY_B)
    # The plaintexts are what actually matter, and neither moved.
    assert var_crypto.decrypt(var_row.value_encrypted, var_row.key_id) == "hunter2"
    assert var_crypto.decrypt(db_row.password_encrypted, db_row.key_id) == "tenant-password"

    # With nothing left naming KEY_A, the old key can go and the store still
    # verifies -- which is the claim the operator acts on.
    assert rotate_encrypted_values(db_session) == 0
    keyring_settings([KEY_B])
    assert verify_keyring(db_session) is None


def test_a_sweep_interrupted_between_columns_resumes(db_session, author, keyring_settings):
    """The sweep walks one column at a time, so the interruption that matters
    is the one after the first column is done and before the second starts."""
    keyring_settings([KEY_A])
    for name in ("ONE", "TWO"):
        ciphertext, key_id = var_crypto.encrypt(f"value-{name}")
        _add_var(db_session, author, key=name, value_encrypted=ciphertext, key_id=key_id)
    db_ciphertext, key_id = var_crypto.encrypt("tenant-password")
    db_row = _add_database(db_session, author, password_encrypted=db_ciphertext, key_id=key_id)

    keyring_settings([KEY_B, KEY_A])

    class Interrupted(Exception):
        pass

    def stop_after_the_vars(rotated: int) -> None:
        if rotated >= 2:
            raise Interrupted

    with pytest.raises(Interrupted):
        rotate_encrypted_values(db_session, batch_size=2, on_batch=stop_after_the_vars)

    # The vars are done, the password is not, and both are still readable.
    db_session.refresh(db_row)
    assert db_row.key_id == key_fingerprint(KEY_A)
    assert var_crypto.decrypt(db_row.password_encrypted, db_row.key_id) == "tenant-password"

    assert rotate_encrypted_values(db_session) == 1
    assert rotate_encrypted_values(db_session) == 0
    db_session.refresh(db_row)
    assert db_row.key_id == key_fingerprint(KEY_B)


def test_the_cli_rotates_and_reports_under_its_new_name(
    cli_runner, db_session, author, keyring_settings
):
    """`keyring-rotate`, not `vars-rotate`: it sweeps every encrypted column,
    and the old name told operators it only swept vars."""
    import yaml

    runner, cli_app = cli_runner
    keyring_settings([KEY_A])
    var_ciphertext, key_id = var_crypto.encrypt("hunter2")
    _add_var(db_session, author, key="TOKEN", value_encrypted=var_ciphertext, key_id=key_id)
    db_ciphertext, _ = var_crypto.encrypt("tenant-password")
    _add_database(db_session, author, password_encrypted=db_ciphertext, key_id=key_id)

    keyring_settings([KEY_B, KEY_A])
    result = runner.invoke(cli_app, ["keyring-rotate"])
    assert result.exit_code == 0, getattr(result, "stderr", result.output)
    reported = yaml.safe_load(getattr(result, "stdout", result.output))
    assert reported == {"rotated": 2, "current_key_id": key_fingerprint(KEY_B)}

    assert runner.invoke(cli_app, ["vars-rotate"]).exit_code != 0


def test_rotation_skips_tombstones(db_session, author, keyring_settings):
    keyring_settings([KEY_A])
    tombstone = _add_var(db_session, author, key="GONE", value_encrypted=None, key_id=None)
    keyring_settings([KEY_B, KEY_A])
    assert rotate_encrypted_values(db_session) == 0
    db_session.refresh(tombstone)
    assert tombstone.key_id is None
