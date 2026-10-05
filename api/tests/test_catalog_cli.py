"""The `caelus catalog` command group: apply, curate, and lint.

The round-trip test is the most valuable one here. `catalog curate` emits YAML
from tuned database state, and the first pull request for a product must be a
verified no-op: the reconciler matches the existing template by spec equality,
inserts nothing, and leaves the canonical pointer where it was.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from sqlmodel import select

from app.models import ProductORM, ProductTemplateVersionORM
from tests.test_catalog_format import document, make_icon

VALUES_SCHEMA = '{"type": "object", "additionalProperties": false, "properties": {"host": {"type": "string"}}}'
SYSTEM_VALUES = '{"image": {"tag": "v3.0.3"}}'


@pytest.fixture
def catalog_cli(cli_runner, tmp_path, monkeypatch):
    """A CLI runner whose static storage and catalog directory are per-test."""
    from app.config import get_settings

    static_path = tmp_path / "static"
    static_path.mkdir()
    monkeypatch.setenv("CAELUS_STATIC_PATH", str(static_path))
    get_settings.cache_clear()

    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()

    runner, app = cli_runner
    yield runner, app, catalog_dir, static_path
    get_settings.cache_clear()


def _yaml(result):
    return yaml.safe_load(getattr(result, "stdout", result.output))


def seed_product(runner, app, tmp_path, *, name: str = "Immich") -> tuple[int, int]:
    """A hand-authored product with an icon and a canonical template."""
    icon = make_icon(tmp_path / "source-icon.png")
    product = _yaml(
        runner.invoke(app, ["create-product", name, "Photo library", "--icon", str(icon)])
    )
    template = _yaml(
        runner.invoke(
            app,
            [
                "create-template",
                "--product-id",
                str(product["id"]),
                "--chart-ref",
                "oci://registry.home:80/helm/immich",
                "--chart-version",
                "1.0.0",
                "--system-values-json",
                SYSTEM_VALUES,
                "--values-schema-json",
                VALUES_SCHEMA,
            ],
        )
    )
    result = runner.invoke(
        app, ["update-product", str(product["id"]), "--template-id", str(template["id"])]
    )
    assert result.exit_code == 0, result.output
    return product["id"], template["id"]


def db_state(product_id: int) -> tuple:
    from app.db import session_scope

    with session_scope() as session:
        product = session.get(ProductORM, product_id)
        rows = session.exec(
            select(ProductTemplateVersionORM).where(
                ProductTemplateVersionORM.product_id == product_id
            )
        ).all()
        return product.curated, product.slug, product.template_id, len(rows)


# ---------------------------------------------------------------------------
# curate
# ---------------------------------------------------------------------------


def test_curate_writes_the_document_and_icon(catalog_cli, tmp_path):
    runner, app, catalog_dir, _ = catalog_cli
    product_id, _ = seed_product(runner, app, tmp_path)

    result = runner.invoke(app, ["catalog", "curate", "Immich", "--dir", str(catalog_dir)])

    assert result.exit_code == 0, result.output
    assert (catalog_dir / "immich.yaml").is_file()
    assert (catalog_dir / "icons/immich.png").is_file()
    # The command reports what it wrote and what remains to be done.
    assert "immich.yaml" in result.output
    assert "commit" in result.output and "merge" in result.output

    doc = yaml.safe_load((catalog_dir / "immich.yaml").read_text())
    assert doc["product"]["slug"] == "immich"
    assert doc["product"]["name"] == "Immich"
    assert doc["template"]["system_values"] == {"image": {"tag": "v3.0.3"}}
    # Release-detection metadata is not derivable from the database, so the
    # block is emitted for the operator to complete rather than omitted.
    assert doc["upstream"]["source"]["type"] == "github-release"


def test_curate_does_not_curate_the_product(catalog_cli, tmp_path):
    """Curation follows from a rolled-out file, never from running a command."""
    runner, app, catalog_dir, _ = catalog_cli
    product_id, template_id = seed_product(runner, app, tmp_path)

    runner.invoke(app, ["catalog", "curate", "Immich", "--dir", str(catalog_dir)])

    assert db_state(product_id) == (False, None, template_id, 1)


def test_curate_targets_a_single_product(catalog_cli, tmp_path):
    runner, app, catalog_dir, _ = catalog_cli
    seed_product(runner, app, tmp_path)
    seed_product(runner, app, tmp_path, name="Nextcloud")

    runner.invoke(app, ["catalog", "curate", "Immich", "--dir", str(catalog_dir)])

    assert sorted(p.name for p in catalog_dir.glob("*.yaml")) == ["immich.yaml"]


def test_curate_round_trips_without_churn(catalog_cli, tmp_path):
    """The single most valuable test in this change."""
    runner, app, catalog_dir, _ = catalog_cli
    product_id, template_id = seed_product(runner, app, tmp_path)

    assert (
        runner.invoke(app, ["catalog", "curate", "Immich", "--dir", str(catalog_dir)]).exit_code
        == 0
    )
    result = runner.invoke(app, ["catalog", "apply", "--dir", str(catalog_dir)])

    assert result.exit_code == 0, result.output
    curated, slug, canonical, template_count = db_state(product_id)
    assert (curated, slug) == (True, "immich")
    # Adoption only: no new template row, and the canonical pointer stays put.
    assert (canonical, template_count) == (template_id, 1)
    assert "template-inserted" not in result.output


def test_curate_of_an_unknown_product_fails(catalog_cli, tmp_path):
    runner, app, catalog_dir, _ = catalog_cli

    result = runner.invoke(app, ["catalog", "curate", "ghost", "--dir", str(catalog_dir)])

    assert result.exit_code == 1
    assert "no product found" in result.output


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def test_apply_creates_a_product_from_a_catalog_file(catalog_cli):
    runner, app, catalog_dir, static_path = catalog_cli
    make_icon(catalog_dir / "icons/immich.png")
    (catalog_dir / "immich.yaml").write_text(yaml.safe_dump(document()))

    result = runner.invoke(app, ["catalog", "apply", "--dir", str(catalog_dir)])

    assert result.exit_code == 0, result.output
    from app.db import session_scope

    with session_scope() as session:
        product = session.exec(select(ProductORM)).one()
        assert (product.slug, product.curated) == ("immich", True)


def test_dry_run_writes_nothing(catalog_cli):
    runner, app, catalog_dir, static_path = catalog_cli
    make_icon(catalog_dir / "icons/immich.png")
    (catalog_dir / "immich.yaml").write_text(yaml.safe_dump(document()))

    result = runner.invoke(app, ["catalog", "apply", "--dir", str(catalog_dir), "--dry-run"])

    assert result.exit_code == 0, result.output
    # The plan is reported, and the summary distinguishes it from a real run.
    assert "product-created immich" in result.output
    assert "Catalog planned" in result.output
    from app.db import session_scope

    with session_scope() as session:
        assert session.exec(select(ProductORM)).all() == []
    assert list(static_path.rglob("*.png")) == []


def test_one_invalid_file_aborts_the_whole_run(catalog_cli):
    runner, app, catalog_dir, _ = catalog_cli
    make_icon(catalog_dir / "icons/immich.png")
    (catalog_dir / "immich.yaml").write_text(yaml.safe_dump(document()))
    (catalog_dir / "broken.yaml").write_text("schema_version: 1\n")

    result = runner.invoke(app, ["catalog", "apply", "--dir", str(catalog_dir)])

    assert result.exit_code == 1
    assert "broken.yaml" in result.output
    from app.db import session_scope

    with session_scope() as session:
        assert session.exec(select(ProductORM)).all() == []


def test_apply_of_a_missing_directory_fails(catalog_cli, tmp_path):
    runner, app, _, _ = catalog_cli

    result = runner.invoke(app, ["catalog", "apply", "--dir", str(tmp_path / "absent")])

    assert result.exit_code == 1
    assert "does not exist" in result.output


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------


def test_lint_passes_on_a_valid_catalog(catalog_cli):
    runner, app, catalog_dir, _ = catalog_cli
    make_icon(catalog_dir / "icons/immich.png")
    (catalog_dir / "immich.yaml").write_text(yaml.safe_dump(document()))

    result = runner.invoke(app, ["catalog", "lint", "--dir", str(catalog_dir)])

    assert result.exit_code == 0, result.output
    assert "Validated 1 catalog document" in result.output


def test_lint_requires_no_database(catalog_cli, monkeypatch):
    """CI has no database, so lint must never open a session."""
    runner, app, catalog_dir, _ = catalog_cli
    make_icon(catalog_dir / "icons/immich.png")
    (catalog_dir / "immich.yaml").write_text(yaml.safe_dump(document()))

    import app.cli as cli

    def fail(*args, **kwargs):
        raise AssertionError("lint opened a database session")

    monkeypatch.setattr(cli, "session_scope", fail)

    assert runner.invoke(app, ["catalog", "lint", "--dir", str(catalog_dir)]).exit_code == 0


def test_lint_rejects_a_document_declaring_visibility(catalog_cli):
    runner, app, catalog_dir, _ = catalog_cli
    make_icon(catalog_dir / "icons/immich.png")
    doc = document()
    doc["product"]["visibility"] = "public"
    (catalog_dir / "immich.yaml").write_text(yaml.safe_dump(doc))

    result = runner.invoke(app, ["catalog", "lint", "--dir", str(catalog_dir)])

    assert result.exit_code == 1
    assert "immich.yaml" in result.output


def test_lint_rejects_a_missing_icon(catalog_cli):
    runner, app, catalog_dir, _ = catalog_cli
    (catalog_dir / "immich.yaml").write_text(yaml.safe_dump(document()))

    result = runner.invoke(app, ["catalog", "lint", "--dir", str(catalog_dir)])

    assert result.exit_code == 1
    assert "icons/immich.png" in result.output


def test_lint_rejects_an_invalid_values_schema(catalog_cli):
    runner, app, catalog_dir, _ = catalog_cli
    make_icon(catalog_dir / "icons/immich.png")
    (catalog_dir / "immich.yaml").write_text(
        yaml.safe_dump(document(**{"template.values_schema": {"type": "not-a-type"}}))
    )

    result = runner.invoke(app, ["catalog", "lint", "--dir", str(catalog_dir)])

    assert result.exit_code == 1
    assert "not a valid JSON Schema" in result.output


def test_lint_rejects_a_stale_generated_schema(catalog_cli):
    """The committed JSON Schema is derived, and lint proves it still is."""
    runner, app, catalog_dir, _ = catalog_cli
    make_icon(catalog_dir / "icons/immich.png")
    (catalog_dir / "immich.yaml").write_text(yaml.safe_dump(document()))
    (catalog_dir / "catalog.schema.json").write_text('{"title": "from an older model"}')

    result = runner.invoke(app, ["catalog", "lint", "--dir", str(catalog_dir)])

    assert result.exit_code == 1
    assert "out of date" in result.output

    # Regenerating from the models makes it pass again.
    assert (
        runner.invoke(
            app, ["catalog", "lint", "--dir", str(catalog_dir), "--write-schema"]
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["catalog", "lint", "--dir", str(catalog_dir)]).exit_code == 0


def test_lint_accepts_a_catalog_without_a_generated_schema(catalog_cli):
    """The schema is an editor convenience, not part of the document contract."""
    runner, app, catalog_dir, _ = catalog_cli
    make_icon(catalog_dir / "icons/immich.png")
    (catalog_dir / "immich.yaml").write_text(yaml.safe_dump(document()))

    assert runner.invoke(app, ["catalog", "lint", "--dir", str(catalog_dir)]).exit_code == 0


def test_curate_keeps_the_generated_schema_current(catalog_cli, tmp_path):
    runner, app, catalog_dir, _ = catalog_cli
    seed_product(runner, app, tmp_path)

    runner.invoke(app, ["catalog", "curate", "Immich", "--dir", str(catalog_dir)])

    assert runner.invoke(app, ["catalog", "lint", "--dir", str(catalog_dir)]).exit_code == 0


def test_catalog_group_is_listed_in_help(catalog_cli):
    runner, app, _, _ = catalog_cli

    result = runner.invoke(app, ["catalog", "--help"])

    assert result.exit_code == 0
    for command in ("apply", "curate", "lint"):
        assert command in result.output
    # There is no command to release a product: that is a catalog file removal.
    assert "uncurate" not in result.output
