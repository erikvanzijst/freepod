"""Suite-wide fixtures, and the PostgreSQL test database the suite owns.

The suite runs against a real PostgreSQL database -- there is no in-memory
mode and no skip path. The database is created if missing, migrated once per
session with the real Alembic chain (so model/migration drift is a hard
failure rather than an invisible one), and reset to empty before every test.

See openspec/changes/drop-sqlite-support/design.md for why the reset is
DELETE rather than TRUNCATE, and why isolation is not rollback-per-test.
"""

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError, ProgrammingError

API_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_BIN = str(Path(sys.executable).parent / "alembic")

_NO_URL = """\
CAELUS_TEST_DATABASE_URL is not set.

The API test suite requires a reachable PostgreSQL server; it has no
in-memory mode. Inside the devcontainer the variable is set for you by
docker-compose.yml. Outside it:

    docker compose up -d postgres
    export CAELUS_TEST_DATABASE_URL=postgresql+psycopg://caelus:caelus@localhost:5432/caelus_test

The connecting user must hold CREATEDB (or be a superuser): the suite
creates and migrates the test database itself.
"""


def _resolve_test_database_url() -> str:
    """Resolve the test database URL, or fail the run with an explanation."""
    raw = os.environ.get("CAELUS_TEST_DATABASE_URL")
    if not raw:
        raise pytest.UsageError(_NO_URL)
    if not make_url(raw).database:
        raise pytest.UsageError(
            f"CAELUS_TEST_DATABASE_URL names no database: {raw!r}"
        )
    return raw


TEST_DATABASE_URL = _resolve_test_database_url()

# Point every engine in the process at the test database *before* any app
# module is imported. `app.db.get_engine()`, the `caelus` CLI, and the Alembic
# subprocess all resolve their URL from this one variable, so this single
# assignment is what keeps the suite off the dev database -- and what removed
# the `importlib.reload(app.db)` ritual the CLI fixture used to need.
os.environ["CAELUS_DATABASE_URL"] = TEST_DATABASE_URL

from cryptography.fernet import Fernet  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.deps import get_payment_provider  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    UserORM,
    PlanORM,
    PlanTemplateVersionORM,
    ProductTemplateVersionORM,
    SubscriptionORM,
    BillingInterval,
    DeploymentORM,
    DeploymentReleaseORM,
)
from app.models.core import _utcnow  # noqa: E402
from app.services.mollie import FakePaymentProvider  # noqa: E402

# ── The test database ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class TestDatabase:
    """The migrated test database, plus what has to be emptied between tests."""

    engine: Engine
    tables: tuple[str, ...]
    sequences: tuple[str, ...]


def _admin_url(url: str) -> str:
    """The same server, addressed through the always-present `postgres` db."""
    return make_url(url).set(database="postgres").render_as_string(hide_password=False)


def _ensure_database_exists(url: str) -> None:
    """Create the test database if it is not there yet. Idempotent."""
    target = make_url(url).database
    admin = create_engine(_admin_url(url), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{target}"'))
    except OperationalError as exc:
        raise pytest.UsageError(
            f"Cannot reach the PostgreSQL server for {url!r}.\n\n{exc}\n\n"
            "Is it running? Inside the devcontainer: `docker compose up -d postgres`."
        ) from exc
    except ProgrammingError as exc:
        raise pytest.UsageError(
            f"Cannot create the test database {target!r}.\n\n{exc}\n\n"
            "The connecting user needs CREATEDB (or superuser)."
        ) from exc
    finally:
        admin.dispose()


def _migrate(url: str) -> None:
    """Bring the test database to head with the real chain, as a subprocess.

    Not `alembic.command.upgrade`: the repo's own `alembic/` package shadows
    the installed distribution whenever `api/` is on `sys.path`, which it
    always is under pytest. Running the console script from `api/` is the
    pattern the migration tests already use.
    """
    result = subprocess.run(
        [ALEMBIC_BIN, "upgrade", "head"],
        cwd=API_ROOT,
        env={**os.environ, "CAELUS_DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise pytest.UsageError(
            "`alembic upgrade head` failed against the test database.\n\n"
            f"{result.stdout}\n{result.stderr}"
        )


def _snapshot(engine: Engine) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """List what the per-test reset has to empty.

    Restricted to the `public` schema: the migration tests create throwaway
    schemas in this same database and manage them themselves. `alembic_version`
    is excluded so migration state survives between tests.

    Sequences come from `pg_sequences` rather than a hand-written list because
    `deployment_var.id` is GENERATED ALWAYS AS IDENTITY, not a serial, and a
    serial-only list would silently miss it.
    """
    with engine.connect() as conn:
        tables = tuple(
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                    "AND table_name <> 'alembic_version' "
                    "ORDER BY table_name"
                )
            )
        )
        sequences = tuple(
            row[0]
            for row in conn.execute(
                text(
                    "SELECT sequencename FROM pg_sequences "
                    "WHERE schemaname = 'public' ORDER BY sequencename"
                )
            )
        )
    if not tables:
        raise pytest.UsageError(
            "The test database has no tables after migrating -- the Alembic "
            "chain did not apply."
        )
    return tables, sequences


def _assert_not_dev_database() -> None:
    """Fail loudly if anything in this run would reach the dev database.

    Every engine resolves its URL from `CAELUS_DATABASE_URL`, which this module
    pins to the test database at import time. If settings still disagree, some
    other source won -- and CI no longer migrates the dev database, so the
    failure would otherwise surface as an obscure "relation does not exist".
    """
    get_settings.cache_clear()
    resolved = get_settings().database_url
    if make_url(resolved).database != make_url(TEST_DATABASE_URL).database:
        raise pytest.UsageError(
            "Database settings do not resolve to the test database.\n"
            f"  expected: {TEST_DATABASE_URL}\n"
            f"  resolved: {resolved}\n"
            "Something is overriding CAELUS_DATABASE_URL after conftest set it."
        )


def _reset(db: TestDatabase) -> None:
    """Return the database to empty, on its own connection.

    `session_replication_role = replica` suppresses FK triggers for this
    connection, which is what makes the DELETEs order-independent. That is not
    a nicety: the metadata has an unresolvable cycle among plan /
    plan_template_version / product / product_template_version, so no
    topological order exists to sort by.
    """
    with db.engine.connect() as conn:
        conn.execute(text("SET session_replication_role = replica"))
        for table in db.tables:
            conn.execute(text(f'DELETE FROM "{table}"'))
        for sequence in db.sequences:
            conn.execute(text(f'ALTER SEQUENCE "{sequence}" RESTART'))
        conn.execute(text("SET session_replication_role = origin"))
        conn.commit()


@pytest.fixture(scope="session", autouse=True)
def test_database() -> TestDatabase:
    """Create, migrate and snapshot the test database once for the whole run.

    Autouse so that a run with no reachable PostgreSQL fails immediately and
    for the whole session, rather than only when the first database-backed
    test happens to be collected.
    """
    _ensure_database_exists(TEST_DATABASE_URL)
    _migrate(TEST_DATABASE_URL)
    _assert_not_dev_database()
    engine = create_engine(TEST_DATABASE_URL)
    tables, sequences = _snapshot(engine)
    try:
        yield TestDatabase(engine=engine, tables=tables, sequences=sequences)
    finally:
        engine.dispose()


# The current ToS version, used to pre-accept test users so deployment tests
# (which now require prior acceptance) work without threading acceptance through
# every case. Tests that specifically exercise the acceptance flow opt out.
CURRENT_TOS_VERSION = get_settings().current_tos_version


# A keyring for the whole suite. Every process that reads or writes vars needs
# one, and a template that declares vars refuses to start without it, so the
# realistic default is "configured" rather than "empty". Tests that exercise
# the keyring itself override this.
TEST_VAR_ENCRYPTION_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _var_encryption_keyring(monkeypatch):
    from app.config import CaelusSettings
    from app.services import var_crypto

    monkeypatch.setattr(
        "app.services.var_crypto.get_settings",
        lambda: CaelusSettings(
            var_encryption_keys=[TEST_VAR_ENCRYPTION_KEY], _env_file=None
        ),
    )
    var_crypto.get_keyring.cache_clear()
    yield
    var_crypto.get_keyring.cache_clear()


@pytest.fixture(autouse=True)
def _hermetic_hostname_settings(monkeypatch):
    """Isolate the whole suite from ambient DNS configuration.

    Hostname validation calls the real ``get_settings()``, which loads
    ``.env`` / ``.env.local`` / ``CAELUS_*`` vars. A configured ``CAELUS_DOMAIN``
    makes ``_check_cname`` perform real CNAME lookups against arbitrary test
    hostnames (-> ``not_resolving``), which breaks any test that creates a
    deployment. ``monkeypatch.delenv`` is not enough — the value comes from the
    ``.env.local`` *file* — so override ``get_settings`` to a blank-``domain``
    object (DNS check skipped). Tests that exercise DNS override it again.
    """
    from app.config import CaelusSettings

    monkeypatch.setattr(
        "app.services.hostnames.get_settings",
        lambda: CaelusSettings(reserved_hostnames=[], domain="", _env_file=None),
    )


@pytest.fixture
def db_session(test_database):
    """A session on the shared test database, which starts this test empty."""
    _reset(test_database)
    with Session(test_database.engine) as session:
        yield session


@pytest.fixture()
def cli_runner(test_database, monkeypatch):
    """The `caelus` CLI, pointed at the same clean test database.

    No `importlib.reload(app.db)` any more: `CAELUS_DATABASE_URL` is pinned to
    the test database for the whole process at conftest import, and the engine
    is built lazily, so the CLI resolves the right database on its own.
    """
    _reset(test_database)
    monkeypatch.setenv("CAELUS_USER_EMAIL", "cli-test@example.com")

    # Same reason as `_hostname_settings` above, for the other half of the
    # reconcile: it derives the account's name from `CAELUS_DOMAIN`, which comes
    # from the gitignored `.env.local` and so is set on a developer's machine and
    # empty in CI. Pinned here rather than left ambient, so these tests fail or
    # pass for the same reason in both places.
    from app.config import CaelusSettings

    monkeypatch.setattr(
        "app.services.reconcile.get_settings",
        lambda: CaelusSettings(wildcard_domains=[], domain="cli.example.test", _env_file=None),
    )

    import app.cli as cli

    return CliRunner(), cli.app


def make_free_subscription(session: Session, *, user_id: int, product_id: int) -> int:
    """A free plan + subscription to hang a hand-built deployment off.

    `deployment.subscription_id` is NOT NULL -- every deployment is billed
    through a subscription, and `create_deployment` always makes one. Tests
    that hand-build a deployment rarely care *which* subscription, only that
    there is one, so this builds the cheapest valid pair. Flushes rather than
    commits, so the caller keeps control of the transaction.
    """
    plan = PlanORM(
        name=f"free-{uuid4().hex[:8]}", product_id=product_id, created_at=_utcnow()
    )
    session.add(plan)
    session.flush()
    ptv = PlanTemplateVersionORM(
        plan_id=plan.id,
        price_cents=0,
        billing_interval=BillingInterval.MONTHLY,
        storage_bytes=0,
        created_at=_utcnow(),
    )
    session.add(ptv)
    session.flush()
    plan.template_id = ptv.id
    subscription = SubscriptionORM(
        plan_template_id=ptv.id, user_id=user_id, created_at=_utcnow()
    )
    session.add(subscription)
    session.flush()
    return subscription.id


def make_deployment_with_release(session: Session, **kwargs) -> DeploymentORM:
    """Hand-build a deployment together with its first release.

    Every deployment names a desired release -- `desired_release_id` is NOT
    NULL, which is the whole point of the ledger -- so a test that builds a
    `DeploymentORM` directly has to build both. It does so in the order
    production uses: the deployment first, already naming a release that does
    not exist yet, then the release. The reverse FK is DEFERRABLE INITIALLY
    DEFERRED, so Postgres checks it at COMMIT -- which is the whole reason the
    suite runs on Postgres.

    `subscription_id` is NOT NULL too, so one is built here when the caller
    does not name it, deriving the product from `desired_template_id`.

    Tests that go through `deployments.create_deployment` need none of this --
    the service creates the release and the subscription itself.
    """
    if kwargs.get("subscription_id") is None:
        template = session.get(ProductTemplateVersionORM, kwargs["desired_template_id"])
        kwargs["subscription_id"] = make_free_subscription(
            session, user_id=kwargs["user_id"], product_id=template.product_id
        )
    release_id = uuid4()
    deployment = DeploymentORM(desired_release_id=release_id, **kwargs)
    session.add(deployment)
    session.add(
        DeploymentReleaseORM(
            id=release_id,
            number=1,
            deployment_id=deployment.id,
            template_id=deployment.desired_template_id,
            values_json=deployment.user_values_json,
        )
    )
    return deployment


def create_free_plan_template(session: Session, product_id: int) -> int:
    """Create a free Plan + PlanTemplateVersion for a product.

    Returns the plan_template_version ID, suitable for passing as
    ``plan_template_id`` to DeploymentCreate or API deployment payloads.
    """
    plan = PlanORM(name="Free", product_id=product_id, created_at=_utcnow())
    session.add(plan)
    session.flush()
    ptv = PlanTemplateVersionORM(
        plan_id=plan.id,
        price_cents=0,
        billing_interval=BillingInterval.MONTHLY,
        storage_bytes=0,
        created_at=_utcnow(),
    )
    session.add(ptv)
    session.flush()
    plan.template_id = ptv.id
    session.commit()
    session.refresh(ptv)
    return ptv.id


def create_paid_plan_template(
    session: Session, product_id: int, *, price_cents: int = 1000, name: str = "Pro",
) -> int:
    """Create a paid Plan + PlanTemplateVersion for a product.

    Returns the plan_template_version ID.
    """
    plan = PlanORM(name=name, product_id=product_id, created_at=_utcnow())
    session.add(plan)
    session.flush()
    ptv = PlanTemplateVersionORM(
        plan_id=plan.id,
        price_cents=price_cents,
        billing_interval=BillingInterval.MONTHLY,
        storage_bytes=0,
        created_at=_utcnow(),
    )
    session.add(ptv)
    session.flush()
    plan.template_id = ptv.id
    session.commit()
    session.refresh(ptv)
    return ptv.id


ADMIN_EMAIL = "test@example.com"
AUTH_HEADER = {"X-Auth-Request-Email": ADMIN_EMAIL}

USER_EMAIL = "regular@example.com"
USER_AUTH_HEADER = {"X-Auth-Request-Email": USER_EMAIL}

OTHER_EMAIL = "other@example.com"
OTHER_AUTH_HEADER = {"X-Auth-Request-Email": OTHER_EMAIL}


def create_user(client, email: str, accept_tos: bool = True) -> dict:
    """Provision a regular (non-admin) user and return its ``UserRead`` dict.

    Users are created on their first authenticated request, so hitting
    ``GET /api/me`` with the target email auto-provisions the user. Use the
    returned dict's ``["id"]`` for the user id. Replaces the removed
    ``POST /api/users`` endpoint for test setup.

    By default the user is also marked as having accepted the current Terms of
    Service, since deploying now requires prior acceptance. Pass
    ``accept_tos=False`` to leave them unaccepted (for tests of the acceptance
    flow itself).
    """
    resp = client.get("/api/me", headers={"X-Auth-Request-Email": email})
    assert resp.status_code == 200, f"provisioning {email}: {resp.status_code}"
    if accept_tos:
        acc = client.post(
            "/api/me/tos-acceptance",
            json={"version": CURRENT_TOS_VERSION},
            headers={"X-Auth-Request-Email": email},
        )
        assert acc.status_code == 200, f"accepting tos for {email}: {acc.status_code}"
    return resp.json()


class FakeDnsProvider:
    """Records what the reconciler asked DNS to do, and does nothing."""

    def __init__(self) -> None:
        self.ensured: list[str] = []
        self.records: set[str] = set()
        self.fail_with: Exception | None = None

    def wildcard_record_exists(self, name: str) -> bool:
        if self.fail_with is not None:
            raise self.fail_with
        return f"*.{name}" in self.records

    def ensure_wildcard_record(self, name: str) -> None:
        self.ensured.append(name)
        if self.fail_with is not None:
            raise self.fail_with
        self.records.add(f"*.{name}")


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch) -> FakeDnsProvider:
    """No test reaches a DNS provider unless it asks for one by name."""
    provider = FakeDnsProvider()
    monkeypatch.setattr("app.services.dns.from_settings", lambda settings=None: provider)
    return provider


def subdomain_for(email: str) -> str:
    """A label for a test user.

    Every account that can deploy holds one, so a fixture that omits it builds a
    user the reconciler refuses -- see `account-subdomain-claim`.
    """
    return re.sub(r"[^a-z0-9]", "", email.split("@")[0].lower())[:63] or "acct"


def make_accepted_user(session, email: str):
    """Create a user via the service *and* record ToS acceptance; return UserRead.

    For service-level tests that create deployments directly through
    ``create_deployment`` (which now requires the owning user to have accepted
    the current Terms).
    """
    from app.services import users as _users

    user = _users.create_user(session, _users.UserCreate(email=email))
    orm = session.get(UserORM, user.id)
    _users.record_tos_acceptance(session, user=orm, version=CURRENT_TOS_VERSION)
    orm.subdomain = subdomain_for(email)
    session.add(orm)
    session.commit()
    return user


@pytest.fixture
def client(db_session):
    """Test client authenticated as an admin user (no payment provider)."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_session] = override_get_db
    app.dependency_overrides[get_payment_provider] = lambda: None

    # Pre-create the default test user as admin so existing tests pass
    admin_user = UserORM(email=ADMIN_EMAIL, is_admin=True, subdomain=subdomain_for(ADMIN_EMAIL),
                         tos_accepted_version=CURRENT_TOS_VERSION, tos_accepted_at=_utcnow())
    db_session.add(admin_user)
    db_session.commit()

    with TestClient(app, headers=AUTH_HEADER) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def fake_payment_provider():
    """A FakePaymentProvider instance shared across a test."""
    return FakePaymentProvider()


@pytest.fixture
def paid_client(db_session, fake_payment_provider, monkeypatch):
    """Test client with FakePaymentProvider injected via dependency override."""
    from app.config import get_settings

    monkeypatch.setenv("CAELUS_MOLLIE_REDIRECT_URL", "https://test.example.com")
    monkeypatch.setenv("CAELUS_MOLLIE_WEBHOOK_BASE_URL", "https://test.example.com/api")
    get_settings.cache_clear()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_session] = override_get_db
    app.dependency_overrides[get_payment_provider] = lambda: fake_payment_provider

    admin_user = UserORM(email=ADMIN_EMAIL, is_admin=True, subdomain=subdomain_for(ADMIN_EMAIL),
                         tos_accepted_version=CURRENT_TOS_VERSION, tos_accepted_at=_utcnow())
    db_session.add(admin_user)
    db_session.commit()

    with TestClient(app, headers=AUTH_HEADER) as client:
        yield client

    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def user_client(db_session):
    """Test client authenticated as a regular (non-admin) user."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_session] = override_get_db

    # Pre-create admin user (some tests need resources created by admin)
    admin_user = UserORM(email=ADMIN_EMAIL, is_admin=True, subdomain=subdomain_for(ADMIN_EMAIL),
                         tos_accepted_version=CURRENT_TOS_VERSION, tos_accepted_at=_utcnow())
    db_session.add(admin_user)
    # Pre-create the acting regular user as already-accepted so deploy tests
    # under this client don't trip the acceptance precondition.
    regular_user = UserORM(email=USER_EMAIL, subdomain=subdomain_for(USER_EMAIL),
                           tos_accepted_version=CURRENT_TOS_VERSION, tos_accepted_at=_utcnow())
    db_session.add(regular_user)
    db_session.commit()
    db_session.refresh(admin_user)

    with TestClient(app, headers=USER_AUTH_HEADER) as c:
        yield c, admin_user

    app.dependency_overrides.clear()
