"""Migration coverage for builds belonging to deployments.

Follows ``test_migration_namespace_unique``: a throwaway schema migrated to the
revision before this one, seeded by hand, then upgraded and inspected.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import TEST_DATABASE_URL
from tests.test_migration_namespace_unique import _alembic, _upgrade

BEFORE = "c6d7e8f9a0b1"
LINKED = "da4841625b1f"

T0 = datetime(2026, 9, 1, 12, 0, 0)


@pytest.fixture
def migrated_schema():
    """A throwaway schema at the revision before builds gained a deployment."""
    schema = f"mig_builddep_{uuid4().hex[:8]}"
    admin = create_engine(TEST_DATABASE_URL)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        _upgrade("upgrade", BEFORE, schema=schema)
        yield schema, create_engine(
            TEST_DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"}
        )
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def _user(conn) -> int:
    return conn.execute(
        text(
            'INSERT INTO "user" (email, is_admin, created_at) '
            "VALUES (:e, false, now()) RETURNING id"
        ),
        {"e": f"{uuid4().hex[:8]}@example.com"},
    ).scalar_one()


def _deployment(conn, user_id: int) -> UUID:
    """A deployment with an initial release naming no build."""
    product_id = conn.execute(
        text("INSERT INTO product (name, created_at) VALUES (:n, now()) RETURNING id"),
        {"n": f"prod-{uuid4().hex[:8]}"},
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
        text(
            "INSERT INTO plan (name, product_id, created_at) "
            "VALUES ('Free', :p, now()) RETURNING id"
        ),
        {"p": product_id},
    ).scalar_one()
    ptv_id = conn.execute(
        text(
            "INSERT INTO plan_template_version "
            "(plan_id, price_cents, billing_interval, created_at) "
            "VALUES (:pl, 0, 'monthly', now()) RETURNING id"
        ),
        {"pl": plan_id},
    ).scalar_one()
    sub_id = conn.execute(
        text(
            "INSERT INTO subscription "
            "(plan_template_id, user_id, status, payment_status, created_at) "
            "VALUES (:t, :u, 'active', 'current', now()) RETURNING id"
        ),
        {"t": ptv_id, "u": user_id},
    ).scalar_one()

    deployment_id, release_id = uuid4(), uuid4()
    conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    conn.execute(
        text(
            "INSERT INTO deployment (id, user_id, desired_template_id, name, namespace, "
            "status, generation, created_at, subscription_id, desired_release_id) "
            "VALUES (:id, :u, :t, :name, :ns, 'ready', 1, now(), :sub, :rel)"
        ),
        {
            "id": deployment_id,
            "u": user_id,
            "t": template_id,
            "name": f"app-{uuid4().hex[:6]}",
            "ns": f"ns-{uuid4().hex[:8]}",
            "sub": sub_id,
            "rel": release_id,
        },
    )
    conn.execute(
        text(
            "INSERT INTO deployment_release "
            "(id, number, deployment_id, template_id, created_at) "
            "VALUES (:id, 1, :dep, :t, :at)"
        ),
        {"id": release_id, "dep": deployment_id, "t": template_id, "at": T0},
    )
    return deployment_id


def _build(conn, user_id: int, *, status: str = "succeeded", image: str | None = None) -> UUID:
    build_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO build (id, user_id, artifact_id, status, created_at, image, log) "
            "VALUES (:id, :u, :a, :s, now(), :img, '')"
        ),
        {"id": build_id, "u": user_id, "a": uuid4().hex, "s": status, "img": image},
    )
    return build_id


def _release(
    conn, deployment_id: UUID, *, at: datetime, build_id: UUID | None = None, image: str | None = None
) -> None:
    """A later release of `deployment_id`, naming a build and/or carrying an image."""
    number, template_id = conn.execute(
        text(
            "SELECT max(number) + 1, max(template_id) FROM deployment_release "
            "WHERE deployment_id = :d"
        ),
        {"d": deployment_id},
    ).one()
    conn.execute(
        text(
            "INSERT INTO deployment_release "
            "(id, number, deployment_id, template_id, build_id, values_json, created_at) "
            "VALUES (:id, :n, :d, :t, :b, CAST(:v AS json), :at)"
        ),
        {
            "id": uuid4(),
            "n": number,
            "d": deployment_id,
            "t": template_id,
            "b": build_id,
            "v": json.dumps({"image": image} if image else {}),
            "at": at,
        },
    )


def _deployment_of(conn, build_id: UUID):
    return conn.execute(
        text("SELECT deployment_id FROM build WHERE id = :b"), {"b": build_id}
    ).scalar_one_or_none()


def test_builds_are_linked_by_release_then_by_image(migrated_schema):
    schema, engine = migrated_schema
    with engine.begin() as conn:
        owner = _user(conn)
        first, second = _deployment(conn, owner), _deployment(conn, owner)
        by_id = _build(conn, owner, image=f"{owner}@sha256:aaa")
        by_image = _build(conn, owner, image=f"{owner}@sha256:bbb")
        # Released into both deployments; the earlier release decides.
        shared = _build(conn, owner, image=f"{owner}@sha256:ccc")
        _release(conn, first, at=T0 + timedelta(hours=1), build_id=by_id)
        _release(conn, first, at=T0 + timedelta(hours=2), image=f"{owner}@sha256:bbb")
        _release(conn, second, at=T0 + timedelta(hours=3), image=f"{owner}@sha256:ccc")
        _release(conn, first, at=T0 + timedelta(hours=4), image=f"{owner}@sha256:ccc")

    _upgrade("upgrade", LINKED, schema=schema)

    with engine.begin() as conn:
        assert _deployment_of(conn, by_id) == first
        assert _deployment_of(conn, by_image) == first
        assert _deployment_of(conn, shared) == second


def test_a_recorded_build_wins_over_an_image_match(migrated_schema):
    """A release that named the build is better evidence than an image match."""
    schema, engine = migrated_schema
    with engine.begin() as conn:
        owner = _user(conn)
        named, other = _deployment(conn, owner), _deployment(conn, owner)
        build = _build(conn, owner, image=f"{owner}@sha256:ddd")
        _release(conn, other, at=T0 + timedelta(hours=1), image=f"{owner}@sha256:ddd")
        _release(conn, named, at=T0 + timedelta(hours=2), build_id=build)

    _upgrade("upgrade", LINKED, schema=schema)

    with engine.begin() as conn:
        assert _deployment_of(conn, build) == named


def test_an_image_released_by_another_owner_does_not_link(migrated_schema):
    schema, engine = migrated_schema
    with engine.begin() as conn:
        owner, stranger = _user(conn), _user(conn)
        theirs = _deployment(conn, stranger)
        build = _build(conn, owner, image=f"{owner}@sha256:eee")
        _release(conn, theirs, at=T0 + timedelta(hours=1), image=f"{owner}@sha256:eee")

    _upgrade("upgrade", LINKED, schema=schema)

    with engine.begin() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM build WHERE id = :b"), {"b": build}
        ).scalar_one() == 0


def test_builds_no_release_used_are_deleted(migrated_schema):
    schema, engine = migrated_schema
    with engine.begin() as conn:
        owner = _user(conn)
        deployment = _deployment(conn, owner)
        kept = _build(conn, owner, image=f"{owner}@sha256:fff")
        _release(conn, deployment, at=T0 + timedelta(hours=1), build_id=kept)
        unreleased = _build(conn, owner, image=f"{owner}@sha256:999")
        failed = _build(conn, owner, status="failed")

    _upgrade("upgrade", LINKED, schema=schema)

    with engine.begin() as conn:
        remaining = set(conn.execute(text("SELECT id FROM build")).scalars())
    assert remaining == {kept}
    assert unreleased not in remaining and failed not in remaining


def test_the_column_is_required_and_user_id_is_gone(migrated_schema):
    schema, engine = migrated_schema
    _upgrade("upgrade", LINKED, schema=schema)

    with engine.begin() as conn:
        columns = {
            name: nullable
            for name, nullable in conn.execute(
                text(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = 'build'"
                ),
                {"s": schema},
            )
        }
    assert columns["deployment_id"] == "NO"
    assert "user_id" not in columns


def test_an_in_flight_build_blocks_the_migration(migrated_schema):
    schema, engine = migrated_schema
    with engine.begin() as conn:
        owner = _user(conn)
        _build(conn, owner, status="running")

    result = _alembic("upgrade", LINKED, schema=schema)

    assert result.returncode != 0
    assert "queued or running" in result.stderr
    with engine.begin() as conn:
        # Nothing was applied: the build keeps its owner column.
        assert conn.execute(text("SELECT count(*) FROM build WHERE user_id IS NOT NULL")).scalar_one() == 1


def test_downgrade_restores_the_owner_from_the_deployment(migrated_schema):
    schema, engine = migrated_schema
    with engine.begin() as conn:
        owner = _user(conn)
        deployment = _deployment(conn, owner)
        build = _build(conn, owner, image=f"{owner}@sha256:abc")
        _release(conn, deployment, at=T0 + timedelta(hours=1), build_id=build)

    _upgrade("upgrade", LINKED, schema=schema)
    _upgrade("downgrade", BEFORE, schema=schema)

    with engine.begin() as conn:
        assert conn.execute(
            text("SELECT user_id FROM build WHERE id = :b"), {"b": build}
        ).scalar_one() == owner
