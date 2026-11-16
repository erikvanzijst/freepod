"""The mutual deployment/release reference: deferred foreign keys at COMMIT.

The `deployment.desired_release_id` foreign key is DEFERRABLE INITIALLY
DEFERRED, so its check fires at COMMIT rather than at INSERT. That is what lets
production insert a deployment naming a release that does not exist yet, and it
is why an insert-order mistake or a dangling pointer has to be caught here.

Self-contained on purpose: rows are built with plain SQL against a schema this
module creates itself, so nothing here depends on the service layer's current
required fields or on state another test left behind.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session, create_engine




@pytest.fixture
def engine(test_database, db_session):
    """The shared test database: already migrated, and empty for this test.

    `db_session` is requested purely for its reset -- this file talks to the
    database through its own short-lived sessions.
    """
    return test_database.engine


@pytest.fixture
def parents(engine):
    """A user, product and template to hang deployments off, per test."""
    token = uuid4().hex[:8]
    with Session(engine) as session:
        user_id = session.exec(
            text(
                "INSERT INTO \"user\" (email, is_admin, created_at) "
                "VALUES (:email, false, now()) RETURNING id"
            ).bindparams(email=f"rel-pg-{token}@example.com")
        ).one()[0]
        product_id = session.exec(
            text(
                "INSERT INTO product (name, created_at, visibility, curated) "
                "VALUES (:name, now(), 'public', false) RETURNING id"
            ).bindparams(name=f"rel-pg-product-{token}")
        ).one()[0]
        template_id = session.exec(
            text(
                "INSERT INTO product_template_version "
                "(product_id, chart_ref, chart_version, created_at) "
                "VALUES (:pid, 'oci://example/chart', '1.0.0', now()) RETURNING id"
            ).bindparams(pid=product_id)
        ).one()[0]
        plan_id = session.exec(
            text(
                "INSERT INTO plan (product_id, name, created_at) "
                "VALUES (:pid, :name, now()) RETURNING id"
            ).bindparams(pid=product_id, name=f"free-{token}")
        ).one()[0]
        plan_template_id = session.exec(
            text(
                "INSERT INTO plan_template_version "
                "(plan_id, price_cents, billing_interval, storage_bytes, created_at) "
                "VALUES (:plid, 0, 'monthly', 0, now()) RETURNING id"
            ).bindparams(plid=plan_id)
        ).one()[0]
        subscription_id = session.exec(
            text(
                "INSERT INTO subscription "
                "(plan_template_id, user_id, status, payment_status, created_at) "
                "VALUES (:ptid, :uid, 'active', 'current', now()) RETURNING id"
            ).bindparams(ptid=plan_template_id, uid=user_id)
        ).one()[0]
        session.commit()
        return {
            "user_id": user_id,
            "template_id": template_id,
            "subscription_id": subscription_id,
            "token": token,
        }


def _insert_deployment(session, parents, *, deployment_id, desired_release_id, suffix=""):
    session.exec(
        text(
            "INSERT INTO deployment "
            "(id, user_id, desired_template_id, hostname, name, display_name, namespace, status, "
            " generation, created_at, desired_release_id, subscription_id) "
            "VALUES (:id, :uid, :tid, :host, :name, :name, :ns, 'provisioning', 1, now(), "
            "        :rid, :sid)"
        ).bindparams(
            id=deployment_id,
            uid=parents["user_id"],
            tid=parents["template_id"],
            sid=parents["subscription_id"],
            host=f"{parents['token']}{suffix}.example.test",
            name=f"app-{parents['token']}{suffix}",
            ns=f"ns-{parents['token']}{suffix}",
            rid=desired_release_id,
        )
    )


def _insert_release(session, parents, *, release_id, deployment_id, number=1):
    session.exec(
        text(
            "INSERT INTO deployment_release "
            "(id, number, deployment_id, template_id, created_at) "
            "VALUES (:id, :num, :did, :tid, now())"
        ).bindparams(
            id=release_id, num=number, did=deployment_id, tid=parents["template_id"]
        )
    )


def test_deployment_then_release_commits_under_the_deferred_constraint(engine, parents):
    """The production insert order: the deployment first, already naming a
    release that does not exist yet, then the release. Only a DEFERRABLE
    INITIALLY DEFERRED constraint permits this, and the check happens at
    COMMIT."""
    deployment_id, release_id = uuid4(), uuid4()
    with Session(engine) as session:
        _insert_deployment(
            session, parents, deployment_id=deployment_id, desired_release_id=release_id
        )
        # Not yet committed, and the pointer is dangling right now. An
        # immediate constraint would already have raised.
        _insert_release(session, parents, release_id=release_id, deployment_id=deployment_id)
        session.commit()

    with Session(engine) as session:
        row = session.exec(
            text("SELECT desired_release_id, applied_release_id FROM deployment WHERE id = :id")
            .bindparams(id=deployment_id)
        ).one()
    assert row[0] == release_id
    # Nothing has rolled out, so the deployment is running nothing.
    assert row[1] is None


def test_release_before_its_deployment_is_rejected(engine, parents):
    """The reverse order does *not* work, and must not: only the deployment's
    pointer is deferred. `deployment_release.deployment_id` is an ordinary
    immediate foreign key, which is what forces the order above."""
    from sqlalchemy.exc import IntegrityError

    deployment_id, release_id = uuid4(), uuid4()
    with Session(engine) as session:
        with pytest.raises(IntegrityError):
            _insert_release(
                session, parents, release_id=release_id, deployment_id=deployment_id
            )
            session.flush()


def test_a_dangling_desired_release_fails_at_commit(engine, parents):
    """Deferred is not absent. A transaction that never inserts the release it
    named is rejected -- at COMMIT rather than at INSERT, but rejected."""
    from sqlalchemy.exc import IntegrityError

    deployment_id, release_id = uuid4(), uuid4()
    with Session(engine) as session:
        _insert_deployment(
            session, parents, deployment_id=deployment_id, desired_release_id=release_id
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_the_release_number_is_unique_within_a_deployment(engine, parents):
    from sqlalchemy.exc import IntegrityError

    deployment_id, release_id = uuid4(), uuid4()
    with Session(engine) as session:
        _insert_deployment(
            session, parents, deployment_id=deployment_id, desired_release_id=release_id
        )
        _insert_release(session, parents, release_id=release_id, deployment_id=deployment_id)
        session.commit()

    with Session(engine) as session:
        with pytest.raises(IntegrityError):
            _insert_release(
                session, parents, release_id=uuid4(), deployment_id=deployment_id, number=1
            )
            session.commit()


def test_deleting_a_deployment_takes_its_releases_with_it(engine, parents):
    """A hard delete drops both rows in one transaction; the deferred check
    sees neither, which is why deferred NO ACTION replaces the ON DELETE SET
    NULL that would otherwise contradict the NOT NULL."""
    deployment_id, release_id = uuid4(), uuid4()
    with Session(engine) as session:
        _insert_deployment(
            session, parents, deployment_id=deployment_id, desired_release_id=release_id
        )
        _insert_release(session, parents, release_id=release_id, deployment_id=deployment_id)
        session.commit()

    with Session(engine) as session:
        session.exec(
            text("DELETE FROM deployment WHERE id = :id").bindparams(id=deployment_id)
        )
        session.commit()
        remaining = session.exec(
            text("SELECT count(*) FROM deployment_release WHERE deployment_id = :id")
            .bindparams(id=deployment_id)
        ).one()[0]
    assert remaining == 0


def test_desired_release_id_is_not_nullable(engine, parents):
    from sqlalchemy.exc import IntegrityError

    with Session(engine) as session:
        with pytest.raises(IntegrityError):
            _insert_deployment(
                session, parents, deployment_id=uuid4(), desired_release_id=None
            )
            session.flush()
