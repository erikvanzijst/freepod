from sqlalchemy import inspect, select

from upgrader import db


def test_migrations_create_the_schema(Session):
    tables = set(inspect(Session.kw["bind"]).get_table_names())
    assert {"runs", "product_results", "alembic_version"} <= tables


def test_database_url_takes_the_platform_form():
    env = {"DATABASE_URL": "postgresql://role:pw@pooler:6432/db"}
    assert db.database_url(env) == "postgresql+psycopg://role:pw@pooler:6432/db"


def test_round_trip(Session):
    with Session.begin() as s:
        run = db.Run(trigger="manual", scope="immich", dry_run=True, pi_version="0.85.1")
        run.products.append(db.ProductResult(slug="immich", needs_human=["x86-64-v2"]))
        s.add(run)
    with Session() as s:
        stored = s.scalars(select(db.Run)).one()
        assert stored.state == "running"
        assert stored.products[0].outcome == "running"
        assert stored.products[0].needs_human == ["x86-64-v2"]
        assert stored.products[0].files == []
