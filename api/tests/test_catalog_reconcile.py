"""CatalogReconciler: matching, insertion, adoption, icons, and uncuration.

The reconciler has exactly two verbs — insert a template and repoint the
canonical pointer — so most of these tests are about what it does *not* do:
touch non-curated products, rewrite template rows, disturb deployments, or
revert an administrator's visibility change.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
import yaml
from PIL import Image
from sqlmodel import select

from app.models import (
    DeploymentORM,
    ProductORM,
    ProductTemplateVersionORM,
    ProductVisibility,
    UserORM,
)
from app.services.catalog import CatalogError, CatalogReconciler
from app.services.images import generate_icon_filename, process_icon
from tests.conftest import db_session, make_deployment_with_release  # noqa: F401
from tests.test_catalog_format import document, make_icon

COMMIT = "75eccfc"


@pytest.fixture
def static_dir(tmp_path, monkeypatch):
    """Point static storage at a per-test directory, as a fresh volume would."""
    from app.config import get_settings

    path = tmp_path / "static"
    path.mkdir()
    monkeypatch.setenv("CAELUS_STATIC_PATH", str(path))
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


@pytest.fixture
def catalog_dir(tmp_path):
    path = tmp_path / "catalog"
    path.mkdir()
    return path


def write_document(catalog_dir: Path, doc: dict, *, icon: str | None = "icons/immich.png") -> None:
    slug = doc["product"]["slug"]
    if icon:
        make_icon(catalog_dir / icon)
    (catalog_dir / f"{slug}.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))


def reconcile(session, catalog_dir: Path, **kwargs):
    return CatalogReconciler(
        session=session, catalog_dir=catalog_dir, commit_sha=COMMIT
    ).apply(**kwargs)


def products(session) -> list[ProductORM]:
    return list(session.exec(select(ProductORM)).all())


def templates(session, product_id: int) -> list[ProductTemplateVersionORM]:
    return list(
        session.exec(
            select(ProductTemplateVersionORM).where(
                ProductTemplateVersionORM.product_id == product_id
            )
        ).all()
    )


def _snapshot(row) -> dict:
    """Every persisted column of a row, for byte-identity assertions.

    `model_dump()` is empty for SQLModel table instances, which do not track
    assigned fields, so read the mapped columns directly.
    """
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def make_product(session, name: str, **kwargs) -> ProductORM:
    product = ProductORM(name=name, **kwargs)
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def make_template(session, product: ProductORM, **kwargs) -> ProductTemplateVersionORM:
    defaults = dict(
        chart_ref="oci://registry.home:80/helm/immich",
        chart_version="1.0.0",
        chart_digest=None,
        system_values_json={"image": {"tag": "v3.0.3"}},
        values_schema_json={"type": "object", "additionalProperties": False, "properties": {}},
    )
    template = ProductTemplateVersionORM(product_id=product.id, **{**defaults, **kwargs})
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


# ---------------------------------------------------------------------------
# Creation and idempotency
# ---------------------------------------------------------------------------


def test_new_catalog_file_creates_a_product_and_template(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())

    report = reconcile(db_session, catalog_dir)

    product = products(db_session)[0]
    assert (product.slug, product.curated, product.name) == ("immich", True, "Immich")
    assert product.category == "Photos & video"
    template = templates(db_session, product.id)[0]
    assert product.template_id == template.id
    assert template.chart_version == "1.0.0"
    assert template.system_values_json == {"image": {"tag": "v3.0.3"}}
    assert {action.kind for action in report.actions} >= {"product-created", "template-inserted"}


def test_inserted_template_records_the_commit(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)

    product = products(db_session)[0]
    assert templates(db_session, product.id)[0].catalog_commit == COMMIT


def test_reconciliation_is_idempotent(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)
    product = products(db_session)[0]
    before = (product.id, product.template_id, len(templates(db_session, product.id)))

    report = reconcile(db_session, catalog_dir)

    db_session.refresh(product)
    assert (product.id, product.template_id, len(templates(db_session, product.id))) == before
    assert report.actions == []


def test_key_ordering_in_the_source_yaml_inserts_nothing(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document(**{"template.system_values": {"a": 1, "b": 2}}))
    reconcile(db_session, catalog_dir)
    product = products(db_session)[0]

    write_document(catalog_dir, document(**{"template.system_values": {"b": 2, "a": 1}}))
    reconcile(db_session, catalog_dir)

    assert len(templates(db_session, product.id)) == 1


def test_renaming_a_product_updates_the_existing_row(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)
    product_id = products(db_session)[0].id

    write_document(catalog_dir, document(**{"product.name": "Immich Photos"}))
    reconcile(db_session, catalog_dir)

    assert [(p.id, p.name) for p in products(db_session)] == [(product_id, "Immich Photos")]


# ---------------------------------------------------------------------------
# Adoption
# ---------------------------------------------------------------------------


def test_adoption_matches_by_name_and_inserts_no_template(db_session, catalog_dir, static_dir):
    """Graduation: the generated file must match the template it came from."""
    product = make_product(db_session, "Immich", description="Photo library")
    template = make_template(db_session, product)
    product.template_id = template.id
    db_session.commit()

    write_document(catalog_dir, document())
    report = reconcile(db_session, catalog_dir)

    db_session.refresh(product)
    assert (product.id, product.slug, product.curated) == (product.id, "immich", True)
    assert templates(db_session, product.id) == [template]
    assert product.template_id == template.id
    assert report.of_kind("template-inserted") == []
    assert len(report.of_kind("product-adopted")) == 1


def test_adoption_is_case_insensitive(db_session, catalog_dir, static_dir):
    product = make_product(db_session, "immich")
    make_template(db_session, product)

    write_document(catalog_dir, document(**{"product.name": "IMMICH"}))
    reconcile(db_session, catalog_dir)

    db_session.refresh(product)
    assert product.curated is True
    assert len(products(db_session)) == 1


def test_a_hand_authored_template_matches_despite_a_null_commit(
    db_session, catalog_dir, static_dir
):
    product = make_product(db_session, "Immich")
    template = make_template(db_session, product)
    assert template.catalog_commit is None

    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)

    assert templates(db_session, product.id) == [template]
    db_session.refresh(template)
    assert template.catalog_commit is None  # reused rows are not stamped


# ---------------------------------------------------------------------------
# Append-only ledger
# ---------------------------------------------------------------------------


def test_a_new_spec_inserts_and_repoints_without_rewriting(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)
    product = products(db_session)[0]
    original = templates(db_session, product.id)[0]
    original_values = dict(original.system_values_json)

    write_document(catalog_dir, document(**{"template.system_values": {"image": {"tag": "v3.1.0"}}}))
    report = reconcile(db_session, catalog_dir)

    db_session.refresh(product)
    db_session.refresh(original)
    rows = templates(db_session, product.id)
    assert len(rows) == 2
    # The superseded row is untouched history, not an update target.
    assert original.system_values_json == original_values
    assert original.deleted_at is None
    assert product.template_id != original.id
    assert len(report.of_kind("canonical-repointed")) == 1


def test_existing_deployments_keep_their_applied_template(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)
    product = products(db_session)[0]
    template = templates(db_session, product.id)[0]

    user = UserORM(email="owner@example.com")
    db_session.add(user)
    db_session.commit()
    deployment = make_deployment_with_release(
        db_session,
        user_id=user.id,
        desired_template_id=template.id,
        applied_template_id=template.id,
        name="app",
        namespace="tenant",
    )
    db_session.commit()

    write_document(catalog_dir, document(**{"template.system_values": {"image": {"tag": "v3.1.0"}}}))
    reconcile(db_session, catalog_dir)

    db_session.refresh(deployment)
    assert deployment.applied_template_id == template.id
    assert deployment.desired_template_id == template.id


# ---------------------------------------------------------------------------
# Non-curated products are out of scope
# ---------------------------------------------------------------------------


def test_non_curated_products_are_untouched(db_session, catalog_dir, static_dir):
    """The safety property the whole design rests on."""
    scratch = make_product(db_session, "Scratch", description="wip", category="Test")
    scratch_template = make_template(db_session, scratch, chart_version="0.0.1")
    scratch.template_id = scratch_template.id
    scratch.visibility = ProductVisibility.PUBLIC
    db_session.commit()
    before = _snapshot(scratch)

    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)

    db_session.refresh(scratch)
    assert _snapshot(scratch) == before
    assert templates(db_session, scratch.id) == [scratch_template]


def test_an_unreadable_catalog_directory_changes_nothing(db_session, tmp_path, static_dir):
    product = make_product(db_session, "Immich", slug="immich", curated=True)
    make_template(db_session, product)

    with pytest.raises(CatalogError):
        reconcile(db_session, tmp_path / "absent")

    db_session.refresh(product)
    assert (product.curated, product.slug) == (True, "immich")


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------


def test_a_created_product_starts_hidden(db_session, catalog_dir, static_dir):
    """Merging a catalog change can never by itself publish a product."""
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)

    assert products(db_session)[0].visibility == ProductVisibility.ADMIN


def test_an_admins_visibility_change_survives_reconciliation(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)
    product = products(db_session)[0]
    product.visibility = ProductVisibility.PUBLIC
    db_session.commit()

    write_document(catalog_dir, document(**{"product.description": "changed"}))
    reconcile(db_session, catalog_dir)

    db_session.refresh(product)
    assert product.visibility == ProductVisibility.PUBLIC
    assert product.description == "changed"


def test_adoption_leaves_visibility_unchanged(db_session, catalog_dir, static_dir):
    product = make_product(db_session, "Immich", visibility=ProductVisibility.PUBLIC)
    make_template(db_session, product)

    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)

    db_session.refresh(product)
    assert product.visibility == ProductVisibility.PUBLIC


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------


def _processed_rel_path(catalog_dir: Path, icon: str = "icons/immich.png") -> str:
    return generate_icon_filename(process_icon((catalog_dir / icon).read_bytes()))


def test_icon_is_materialized_on_the_first_run(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())

    reconcile(db_session, catalog_dir)

    rel_path = _processed_rel_path(catalog_dir)
    assert products(db_session)[0].rel_icon_path == rel_path
    assert (static_dir / rel_path).is_file()


def test_unchanged_icon_is_not_rewritten(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)
    written = static_dir / _processed_rel_path(catalog_dir)
    stamp = written.stat().st_mtime_ns

    report = reconcile(db_session, catalog_dir)

    assert report.of_kind("icon-materialized") == []
    assert written.stat().st_mtime_ns == stamp


def test_an_empty_volume_is_repopulated(db_session, catalog_dir, static_dir):
    """A correct `rel_icon_path` is not evidence the file exists in this environment."""
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)
    product = products(db_session)[0]
    rel_path = product.rel_icon_path
    (static_dir / rel_path).unlink()

    reconcile(db_session, catalog_dir)

    db_session.refresh(product)
    assert product.rel_icon_path == rel_path
    assert (static_dir / rel_path).is_file()


def test_changing_an_icon_inserts_no_template(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)
    product = products(db_session)[0]
    first_path = product.rel_icon_path

    make_icon(catalog_dir / "icons/immich.png", color="blue")
    reconcile(db_session, catalog_dir)

    db_session.refresh(product)
    assert product.rel_icon_path != first_path
    assert (static_dir / product.rel_icon_path).is_file()
    assert len(templates(db_session, product.id)) == 1


def test_a_missing_icon_fails_the_run(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document(), icon=None)

    with pytest.raises(CatalogError, match="does not exist"):
        reconcile(db_session, catalog_dir)

    assert products(db_session) == []


# ---------------------------------------------------------------------------
# Uncuration
# ---------------------------------------------------------------------------


def test_removing_a_catalog_file_releases_the_product(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)
    product = products(db_session)[0]
    template_ids = [t.id for t in templates(db_session, product.id)]
    canonical = product.template_id
    product.visibility = ProductVisibility.PUBLIC
    db_session.commit()

    (catalog_dir / "immich.yaml").unlink()
    report = reconcile(db_session, catalog_dir)

    db_session.refresh(product)
    assert (product.curated, product.slug) == (False, None)
    # Release is shallow: nothing else moves.
    assert [t.id for t in templates(db_session, product.id)] == template_ids
    assert product.template_id == canonical
    assert product.visibility == ProductVisibility.PUBLIC
    assert product.deleted_at is None
    assert len(report.of_kind("product-released")) == 1


def test_an_empty_directory_uncurates_everything(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)
    (catalog_dir / "immich.yaml").unlink()

    reconcile(db_session, catalog_dir)

    assert products(db_session)[0].curated is False


def test_restoring_the_file_re_adopts_by_name(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)
    product = products(db_session)[0]
    (catalog_dir / "immich.yaml").unlink()
    reconcile(db_session, catalog_dir)

    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)

    db_session.refresh(product)
    assert (product.curated, product.slug) == (True, "immich")
    assert len(products(db_session)) == 1
    assert len(templates(db_session, product.id)) == 1


def test_a_missing_directory_uncurates_nothing(db_session, tmp_path, static_dir, catalog_dir):
    """The systemic case: a mistyped --dir must not release every product."""
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)

    with pytest.raises(CatalogError):
        reconcile(db_session, tmp_path / "typo")

    product = products(db_session)[0]
    db_session.refresh(product)
    assert product.curated is True


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_dry_run_reports_actions_and_writes_nothing(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())

    report = reconcile(db_session, catalog_dir, dry_run=True)

    assert {action.kind for action in report.actions} >= {"product-created", "template-inserted"}
    assert products(db_session) == []
    assert list(static_dir.rglob("*.png")) == []
