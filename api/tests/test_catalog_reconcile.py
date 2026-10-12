"""CatalogReconciler: matching, insertion, adoption, icons, and uncuration.

The reconciler has exactly two verbs — insert a template and repoint the
canonical pointer — so most of these tests are about what it does *not* do:
touch non-curated products, rewrite template rows, disturb deployments, or
revert an administrator's visibility change.
"""

from __future__ import annotations

import io
import shutil
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


def write_document(catalog_dir: Path, doc: dict, *, icon: str | None = "icon.png") -> Path:
    """Write ``<slug>/<slug>.yaml``; ``icon`` is relative to that folder."""
    slug = doc["product"]["slug"]
    folder = catalog_dir / slug
    folder.mkdir(parents=True, exist_ok=True)
    if icon:
        make_icon(folder / icon)
    (folder / f"{slug}.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    return folder


def remove_product(catalog_dir: Path, slug: str = "immich") -> None:
    shutil.rmtree(catalog_dir / slug)


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


def test_an_unlisted_product_stays_unlisted_through_reconciliation(
    db_session, catalog_dir, static_dir
):
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)
    product = products(db_session)[0]
    product.visibility = ProductVisibility.UNLISTED
    db_session.commit()

    write_document(catalog_dir, document(**{"product.description": "changed"}))
    reconcile(db_session, catalog_dir)

    db_session.refresh(product)
    assert product.visibility == ProductVisibility.UNLISTED
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


def _processed_rel_path(catalog_dir: Path, icon: str = "immich/icon.png") -> str:
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

    make_icon(catalog_dir / "immich/icon.png", color="blue")
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

    remove_product(catalog_dir)
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
    remove_product(catalog_dir)

    reconcile(db_session, catalog_dir)

    assert products(db_session)[0].curated is False


def test_restoring_the_file_re_adopts_by_name(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)
    product = products(db_session)[0]
    remove_product(catalog_dir)
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


# ---------------------------------------------------------------------------
# Listing fields, screenshots, versions and releases (app-store-listings)
# ---------------------------------------------------------------------------


from app.models import ProductReleaseORM, screenshot_thumbnail_path  # noqa: E402
from tests.test_catalog_format import make_screenshot  # noqa: E402

SHOT = {"file": "screenshots/a.webp", "caption": "Timeline", "form": "desktop"}


def with_product(**fields) -> dict:
    doc = document()
    doc["product"].update(fields)
    return doc


def releases(session, product_id: int) -> list[ProductReleaseORM]:
    return list(
        session.exec(
            select(ProductReleaseORM)
            .where(ProductReleaseORM.product_id == product_id)
            .order_by(ProductReleaseORM.position)
        ).all()
    )


def test_listing_fields_are_applied(db_session, catalog_dir, static_dir):
    write_document(
        catalog_dir,
        with_product(
            tagline="Kept private.",
            license="AGPL-3.0",
            features=[{"title": "Sync", "body": "Backup.", "icon": "sync"}],
            links=[{"label": "Site", "href": "https://immich.app", "kind": "website"}],
        ),
    )
    reconcile(db_session, catalog_dir)

    product = products(db_session)[0]
    assert (product.tagline, product.license) == ("Kept private.", "AGPL-3.0")
    assert product.features == [{"title": "Sync", "body": "Backup.", "icon": "sync"}]
    assert product.links == [{"label": "Site", "href": "https://immich.app", "kind": "website"}]


def test_changing_listing_text_inserts_no_template(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, with_product(tagline="First."))
    reconcile(db_session, catalog_dir)
    write_document(catalog_dir, with_product(tagline="Second.", features=[]))

    report = reconcile(db_session, catalog_dir)

    product = products(db_session)[0]
    assert product.tagline == "Second."
    assert report.of_kind("template-inserted") == []
    assert len(templates(db_session, product.id)) == 1


def test_removed_feature_disappears(db_session, catalog_dir, static_dir):
    feature = {"title": "Sync", "body": "Backup.", "icon": "sync"}
    write_document(catalog_dir, with_product(features=[feature]))
    reconcile(db_session, catalog_dir)
    write_document(catalog_dir, with_product(features=[]))

    reconcile(db_session, catalog_dir)

    assert products(db_session)[0].features == []


def test_uncurating_keeps_listing_data(db_session, catalog_dir, static_dir):
    folder = write_document(
        catalog_dir, with_product(tagline="Kept private.", screenshots=[SHOT])
    )
    make_screenshot(folder / SHOT["file"])
    (folder / "releases.yaml").write_text(yaml.safe_dump([{"version": "3.0.3", "notes": "Hi."}]))
    reconcile(db_session, catalog_dir)
    product = products(db_session)[0]

    remove_product(catalog_dir)
    reconcile(db_session, catalog_dir)

    db_session.refresh(product)
    assert product.curated is False
    assert product.tagline == "Kept private."
    assert len(product.screenshots) == 1
    assert [r.version for r in releases(db_session, product.id)] == ["3.0.3"]


def test_screenshots_are_materialized_in_declared_order(db_session, catalog_dir, static_dir):
    second = {"file": "screenshots/b.webp", "caption": "Phone", "form": "mobile",
              "credit": {"text": "Immich · MIT", "href": "https://immich.app"}}
    folder = write_document(catalog_dir, with_product(screenshots=[SHOT, second]))
    make_screenshot(folder / SHOT["file"])
    make_screenshot(folder / second["file"], size=(390, 844))

    report = reconcile(db_session, catalog_dir)

    stored = products(db_session)[0].screenshots
    assert [s["caption"] for s in stored] == ["Timeline", "Phone"]
    assert stored[1]["form"] == "mobile"
    assert stored[1]["credit"] == {"text": "Immich · MIT", "href": "https://immich.app"}
    for entry in stored:
        assert (static_dir / entry["path"]).is_file()
        assert (static_dir / screenshot_thumbnail_path(entry["path"])).is_file()
    assert len(report.of_kind("screenshot-materialized")) == 2


def test_unchanged_screenshots_are_not_rerendered(db_session, catalog_dir, static_dir):
    folder = write_document(catalog_dir, with_product(screenshots=[SHOT]))
    make_screenshot(folder / SHOT["file"])
    reconcile(db_session, catalog_dir)
    written = static_dir / products(db_session)[0].screenshots[0]["path"]
    stamp = written.stat().st_mtime_ns

    report = reconcile(db_session, catalog_dir)

    assert report.of_kind("screenshot-materialized") == []
    assert written.stat().st_mtime_ns == stamp


def test_a_missing_thumbnail_is_repopulated(db_session, catalog_dir, static_dir):
    folder = write_document(catalog_dir, with_product(screenshots=[SHOT]))
    make_screenshot(folder / SHOT["file"])
    reconcile(db_session, catalog_dir)
    thumb = static_dir / screenshot_thumbnail_path(products(db_session)[0].screenshots[0]["path"])
    thumb.unlink()

    report = reconcile(db_session, catalog_dir)

    assert thumb.is_file()
    assert len(report.of_kind("screenshot-materialized")) == 1


def test_an_unreadable_screenshot_fails_the_run(db_session, catalog_dir, static_dir):
    folder = write_document(catalog_dir, with_product(screenshots=[SHOT]))
    (folder / "screenshots").mkdir()
    (folder / SHOT["file"]).write_bytes(b"not an image")

    with pytest.raises(CatalogError, match="not a readable image"):
        reconcile(db_session, catalog_dir)

    assert products(db_session) == []


def test_inserted_template_is_stamped_with_its_version(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())

    reconcile(db_session, catalog_dir)

    (template,) = templates(db_session, products(db_session)[0].id)
    assert template.version == "3.0.3"


def test_chart_version_paths_are_stamped(db_session, catalog_dir, static_dir):
    doc = document(
        **{"upstream.version_path": "template.chart_version", "upstream.match": r"^(?P<version>.+)$"}
    )
    write_document(catalog_dir, doc)

    reconcile(db_session, catalog_dir)

    (template,) = templates(db_session, products(db_session)[0].id)
    assert template.version == "1.0.0"


def test_unquoted_numeric_tags_are_stamped(db_session, catalog_dir, static_dir):
    doc = document(
        **{"template.system_values": {"image": {"tag": 261007}}, "upstream.match": r"^(?P<version>\d+)$"}
    )
    write_document(catalog_dir, doc)

    reconcile(db_session, catalog_dir)

    assert templates(db_session, products(db_session)[0].id)[0].version == "261007"


def test_non_matching_values_stay_unversioned(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document(**{"upstream.match": r"^release-(?P<version>.+)$"}))

    report = reconcile(db_session, catalog_dir)

    assert templates(db_session, products(db_session)[0].id)[0].version is None
    assert report.of_kind("version-stamped") == []


def test_existing_rows_are_backfilled(db_session, catalog_dir, static_dir):
    product = make_product(db_session, "Immich")
    older = make_template(db_session, product, system_values_json={"image": {"tag": "v3.0.1"}})
    make_template(db_session, product)  # matches the document's spec: v3.0.3
    write_document(catalog_dir, document())

    report = reconcile(db_session, catalog_dir)

    db_session.refresh(older)
    assert older.version == "3.0.1"
    assert sorted(t.version for t in templates(db_session, product.id)) == ["3.0.1", "3.0.3"]
    assert len(report.of_kind("version-stamped")) == 2


def test_a_set_version_is_never_overwritten(db_session, catalog_dir, static_dir):
    product = make_product(db_session, "Immich")
    template = make_template(db_session, product, version="hand-set")
    write_document(catalog_dir, document())

    reconcile(db_session, catalog_dir)

    db_session.refresh(template)
    assert template.version == "hand-set"


def write_releases(catalog_dir: Path, entries: list[dict]) -> None:
    (catalog_dir / "immich" / "releases.yaml").write_text(yaml.safe_dump(entries, sort_keys=False))


def test_releases_are_inserted_newest_first(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    write_releases(catalog_dir, [{"version": "3.0.3", "notes": "B"}, {"version": "3.0.1", "notes": "A"}])

    report = reconcile(db_session, catalog_dir)

    rows = releases(db_session, products(db_session)[0].id)
    assert [(r.version, r.position) for r in rows] == [("3.0.3", 0), ("3.0.1", 1)]
    assert len(report.of_kind("release-inserted")) == 2


def test_a_new_release_on_top_shifts_the_others(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    write_releases(catalog_dir, [{"version": "3.0.1", "notes": "A"}])
    reconcile(db_session, catalog_dir)
    write_releases(catalog_dir, [{"version": "3.0.3", "notes": "B"}, {"version": "3.0.1", "notes": "A"}])

    report = reconcile(db_session, catalog_dir)

    rows = releases(db_session, products(db_session)[0].id)
    assert [r.version for r in rows] == ["3.0.3", "3.0.1"]
    assert [a.detail for a in report.of_kind("release-inserted")] == ["3.0.3"]


def test_corrected_notes_update_the_row(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    write_releases(catalog_dir, [{"version": "3.0.3", "notes": "Typo"}])
    reconcile(db_session, catalog_dir)
    write_releases(catalog_dir, [{"version": "3.0.3", "notes": "Fixed"}])

    report = reconcile(db_session, catalog_dir)

    (row,) = releases(db_session, products(db_session)[0].id)
    assert row.notes == "Fixed"
    assert len(report.of_kind("release-updated")) == 1


def test_a_removed_version_is_deleted(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    write_releases(catalog_dir, [{"version": "3.0.3", "notes": "B"}, {"version": "3.0.1", "notes": "A"}])
    reconcile(db_session, catalog_dir)
    (catalog_dir / "immich" / "releases.yaml").unlink()

    report = reconcile(db_session, catalog_dir)

    assert releases(db_session, products(db_session)[0].id) == []
    assert len(report.of_kind("release-deleted")) == 2


def test_dry_run_reports_releases_without_writing(db_session, catalog_dir, static_dir):
    write_document(catalog_dir, document())
    reconcile(db_session, catalog_dir)
    write_releases(catalog_dir, [{"version": "3.0.3", "notes": "B"}])

    report = reconcile(db_session, catalog_dir, dry_run=True)

    assert [a.detail for a in report.of_kind("release-inserted")] == ["3.0.3"]
    assert releases(db_session, products(db_session)[0].id) == []
