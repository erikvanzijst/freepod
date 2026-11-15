"""Migration coverage for the deployment identity backfill (deployment-identity).

Each run migrates a throwaway schema, as test_migration_namespace_unique.py
does, and drives Alembic as a subprocess for the same reason.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from tests.conftest import TEST_DATABASE_URL


API_ROOT = Path(__file__).resolve().parents[1]
BEFORE = "e3b9c5d1a7f4"
IDENTITY = "f1d7c3a9e5b2"


def _alembic(*args: str, schema: str) -> None:
    result = subprocess.run(
        [str(Path(sys.executable).parent / "alembic"), *args],
        cwd=API_ROOT,
        env={
            **os.environ,
            "CAELUS_DATABASE_URL": TEST_DATABASE_URL,
            "PGOPTIONS": f"-csearch_path={schema}",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stderr}"


@pytest.fixture
def migrated():
    schema = f"mig_identity_{uuid4().hex[:8]}"
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        _alembic("upgrade", BEFORE, schema=schema)
        yield schema, create_engine(
            TEST_DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"}
        )
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def _user(conn, handle: str) -> int:
    return conn.execute(
        text(
            'INSERT INTO "user" (email, handle, is_admin, created_at) '
            "VALUES (:e, :h, false, now()) RETURNING id"
        ),
        {"e": f"{handle}@example.com", "h": handle},
    ).scalar_one()


def _product(conn, name: str, slug: str | None) -> tuple[int, int, int]:
    product_id = conn.execute(
        text("INSERT INTO product (name, slug, created_at) VALUES (:n, :s, now()) RETURNING id"),
        {"n": name, "s": slug},
    ).scalar_one()
    template_id = conn.execute(
        text(
            "INSERT INTO product_template_version "
            "(product_id, chart_ref, chart_version, values_schema_json, created_at) "
            "VALUES (:p, 'oci://example/chart', '1.0.0', '{}', now()) RETURNING id"
        ),
        {"p": product_id},
    ).scalar_one()
    plan_id = conn.execute(
        text("INSERT INTO plan (name, product_id, created_at) VALUES ('Free', :p, now()) RETURNING id"),
        {"p": product_id},
    ).scalar_one()
    ptv_id = conn.execute(
        text(
            "INSERT INTO plan_template_version (plan_id, price_cents, billing_interval, created_at) "
            "VALUES (:pl, 0, 'monthly', now()) RETURNING id"
        ),
        {"pl": plan_id},
    ).scalar_one()
    return product_id, template_id, ptv_id


def _deployment(conn, *, user_id, product, hostname, status="ready", minute=0):
    _, template_id, ptv_id = product
    sub_id = conn.execute(
        text(
            "INSERT INTO subscription (plan_template_id, user_id, status, payment_status, created_at) "
            "VALUES (:t, :u, 'active', 'current', now()) RETURNING id"
        ),
        {"t": ptv_id, "u": user_id},
    ).scalar_one()
    deployment_id, release_id = uuid4(), uuid4()
    conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    conn.execute(
        text(
            "INSERT INTO deployment (id, user_id, desired_template_id, name, namespace, hostname, "
            "status, generation, created_at, subscription_id, desired_release_id) "
            "VALUES (:id, :u, :t, :name, :ns, :host, :status, 1, "
            "        timestamp '2026-01-01' + make_interval(mins => :minute), :sub, :rel)"
        ),
        {
            "id": deployment_id, "u": user_id, "t": template_id, "name": f"rel-{uuid4().hex[:6]}",
            "ns": f"ns-{uuid4().hex[:8]}", "host": hostname, "status": status,
            "minute": minute, "sub": sub_id, "rel": release_id,
        },
    )
    conn.execute(
        text(
            "INSERT INTO deployment_release (id, number, deployment_id, template_id, created_at) "
            "VALUES (:id, 1, :d, :t, now())"
        ),
        {"id": release_id, "d": deployment_id, "t": template_id},
    )
    return deployment_id


def _names(engine) -> dict:
    with engine.connect() as conn:
        return {
            row.id: row.display_name
            for row in conn.execute(text("SELECT id, display_name FROM deployment"))
        }


def test_the_backfill_names_every_deployment(migrated):
    schema, engine = migrated
    with engine.begin() as conn:
        erik = _user(conn, "erik")
        other = _user(conn, "fred")
        custom = _product(conn, "Custom user app", "custom")
        nextcloud = _product(conn, "Nextcloud", "nextcloud")
        sandbox = _product(conn, "Nextcloud SSO", None)
        tenant = _deployment(conn, user_id=erik, product=custom, hostname="arkanoid-erik.freepod.app", minute=1)
        domain = _deployment(conn, user_id=erik, product=custom, hostname="stuff.example.com", minute=2)
        nc1 = _deployment(conn, user_id=erik, product=nextcloud, hostname="cloud-erik.freepod.app", minute=3)
        nc2 = _deployment(conn, user_id=erik, product=nextcloud, hostname="cloud2-erik.freepod.app", minute=4)
        gone = _deployment(conn, user_id=erik, product=nextcloud, hostname=None, status="deleted", minute=5)
        theirs = _deployment(conn, user_id=other, product=nextcloud, hostname="cloud-fred.freepod.app", minute=6)
        sso = _deployment(conn, user_id=erik, product=sandbox, hostname="sso-erik.freepod.app", minute=7)
        clash = _deployment(conn, user_id=erik, product=custom, hostname="nextcloud-erik.freepod.app", minute=8)

    _alembic("upgrade", IDENTITY, schema=schema)

    assert _names(engine) == {
        tenant: "arkanoid",
        domain: "stuff.example.com",
        nc1: "Nextcloud",
        nc2: "Nextcloud 2",
        gone: "Nextcloud",
        theirs: "Nextcloud",
        sso: "Nextcloud SSO",
        clash: "nextcloud 3",
    }
    with engine.connect() as conn:
        assert conn.execute(text("SELECT DISTINCT managed_fields::text FROM deployment")).scalar_one() == "[]"


def test_the_index_refuses_a_duplicate_live_name(migrated):
    schema, engine = migrated
    with engine.begin() as conn:
        user_id = _user(conn, "erik")
        nextcloud = _product(conn, "Nextcloud", "nextcloud")
        _deployment(conn, user_id=user_id, product=nextcloud, hostname="a.example.com")
        second = _deployment(conn, user_id=user_id, product=nextcloud, hostname="b.example.com", minute=1)
    _alembic("upgrade", IDENTITY, schema=schema)
    with pytest.raises(Exception, match="uq_deployment_display_name"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE deployment SET display_name = 'NEXTCLOUD' WHERE id = :id"), {"id": second})


def test_the_downgrade_drops_the_columns(migrated):
    schema, engine = migrated
    with engine.begin() as conn:
        user_id = _user(conn, "erik")
        _deployment(conn, user_id=user_id, product=_product(conn, "Nextcloud", "nextcloud"), hostname="a.example.com")
    _alembic("upgrade", IDENTITY, schema=schema)
    _alembic("downgrade", BEFORE, schema=schema)
    with engine.connect() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = 'deployment'"
                ),
                {"s": schema},
            )
        }
    assert not columns & {"display_name", "description", "rel_icon_path", "icon_source_sha256", "managed_fields"}
    assert "name" in columns
