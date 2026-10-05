"""The catalog document contract: parsing, validation, and spec hashing.

These tests never touch a database — the same property that lets `catalog lint`
gate a pull request in CI, where neither a database nor the cluster is
reachable.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import yaml
from PIL import Image

from app.services.catalog import (
    CATALOG_SCHEMA_VERSION,
    CatalogError,
    catalog_document_json_schema,
    document_spec_hash,
    dump_document,
    load_catalog,
    load_document,
    spec_hash,
)


def make_icon(path: Path, color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    Image.new("RGBA", (64, 64), color).save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())
    return path


def document(**overrides) -> dict:
    doc = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "product": {
            "slug": "immich",
            "name": "Immich",
            "description": "Photo library",
            "category": "Photos & video",
            "replaces": "Google Photos",
            "icon": "icons/immich.png",
        },
        "upstream": {
            "source": {"type": "github-release", "repo": "immich-app/immich"},
            "match": r"^v(?P<version>\d+\.\d+\.\d+)$",
            "version_path": "template.system_values.image.tag",
        },
        "template": {
            "chart_ref": "oci://registry.home:80/helm/immich",
            "chart_version": "1.0.0",
            "system_values": {"image": {"tag": "v3.0.3"}},
            "values_schema": {"type": "object", "additionalProperties": False, "properties": {}},
        },
    }
    for path, value in overrides.items():
        target = doc
        *parents, leaf = path.split(".")
        for key in parents:
            target = target[key]
        if value is None:
            target.pop(leaf, None)
        else:
            target[leaf] = value
    return doc


def write_catalog(tmp_path: Path, documents: dict[str, dict], *, icons=("icons/immich.png",)):
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    for icon in icons:
        make_icon(catalog_dir / icon)
    for name, doc in documents.items():
        (catalog_dir / name).write_text(yaml.safe_dump(doc, sort_keys=False))
    return catalog_dir


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_document_loads(tmp_path):
    catalog_dir = write_catalog(tmp_path, {"immich.yaml": document()})

    entries = load_catalog(catalog_dir)

    assert [entry.slug for entry in entries] == ["immich"]
    assert entries[0].document.product.name == "Immich"
    assert entries[0].icon_bytes is not None


def test_document_without_an_icon_is_valid(tmp_path):
    catalog_dir = write_catalog(
        tmp_path, {"immich.yaml": document(**{"product.icon": None})}, icons=()
    )

    entries = load_catalog(catalog_dir)
    assert entries[0].icon_bytes is None


def test_empty_directory_is_valid(tmp_path):
    """The state every environment is in before its first product is curated."""
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()

    assert load_catalog(catalog_dir) == []


def test_missing_directory_is_an_error(tmp_path):
    """Failing to read desired state is not the same as it being empty."""
    with pytest.raises(CatalogError, match="does not exist"):
        load_catalog(tmp_path / "absent")


# ---------------------------------------------------------------------------
# Per-document validation
# ---------------------------------------------------------------------------


def _expect_error(tmp_path, doc: dict, match: str, *, name: str = "immich.yaml", **kwargs):
    catalog_dir = write_catalog(tmp_path, {name: doc}, **kwargs)
    with pytest.raises(CatalogError, match=match) as excinfo:
        load_catalog(catalog_dir)
    # Every message names the file the operator has to edit.
    assert name in str(excinfo.value)


def test_unsupported_schema_version_is_rejected(tmp_path):
    _expect_error(tmp_path, document(schema_version=99), "unsupported schema_version 99")


def test_slug_must_match_the_filename(tmp_path):
    _expect_error(tmp_path, document(**{"product.slug": "photos"}), "must equal the filename stem")


def test_unknown_key_is_rejected(tmp_path):
    """A mistyped key is a hard error, not a silently dropped value."""
    doc = document()
    doc["product"]["categories"] = "oops"
    _expect_error(tmp_path, doc, "Extra inputs are not permitted")


def test_declaring_visibility_is_rejected(tmp_path):
    """Visibility is runtime state; the catalog must not appear to own it."""
    doc = document()
    doc["product"]["visibility"] = "public"
    _expect_error(tmp_path, doc, "Extra inputs are not permitted")


def test_unknown_top_level_key_is_rejected(tmp_path):
    doc = document()
    doc["policy"] = {"semver": "~3.0"}
    _expect_error(tmp_path, doc, "Extra inputs are not permitted")


def test_embedded_image_data_is_rejected(tmp_path):
    doc = document()
    doc["product"]["icon_data"] = "iVBORw0KGgo="
    _expect_error(tmp_path, doc, "Extra inputs are not permitted")


def test_icon_escaping_the_catalog_directory_is_rejected(tmp_path):
    _expect_error(tmp_path, document(**{"product.icon": "../secrets.png"}), "must be a relative path")


def test_absolute_icon_path_is_rejected(tmp_path):
    _expect_error(tmp_path, document(**{"product.icon": "/etc/icon.png"}), "must be a relative path")


def test_missing_icon_file_is_rejected(tmp_path):
    _expect_error(tmp_path, document(), "does not exist", icons=())


def test_unprocessable_icon_is_rejected(tmp_path):
    catalog_dir = write_catalog(tmp_path, {"immich.yaml": document()})
    (catalog_dir / "icons/immich.png").write_bytes(b"not an image")

    with pytest.raises(CatalogError, match="cannot be processed as an image"):
        load_catalog(catalog_dir)


def test_invalid_values_schema_is_rejected(tmp_path):
    _expect_error(
        tmp_path,
        document(**{"template.values_schema": {"type": "not-a-type"}}),
        "not a valid JSON Schema",
    )


def test_illegal_routing_marker_is_rejected(tmp_path):
    """Same rules the API applies to a hand-made template, so `catalog lint`
    catches a bad marker in CI rather than on rollout."""
    _expect_error(
        tmp_path,
        document(
            **{
                "template.values_schema": {
                    "type": "object",
                    "properties": {
                        "signups": {
                            "type": "object",
                            "properties": {
                                "allowed": {
                                    "type": "boolean",
                                    "x-caelus-target": "runtime",
                                }
                            },
                        }
                    },
                }
            }
        ),
        "top-level property",
    )


def test_a_legal_routing_marker_loads(tmp_path):
    catalog_dir = write_catalog(
        tmp_path,
        {
            "immich.yaml": document(
                **{
                    "template.values_schema": {
                        "type": "object",
                        "properties": {
                            "ADMIN_TOKEN": {
                                "type": "string",
                                "x-caelus-target": "runtime",
                                "x-caelus-sensitive": True,
                            }
                        },
                    }
                }
            )
        },
    )

    entries = load_catalog(catalog_dir)

    assert entries[0].document.template.values_schema["properties"]["ADMIN_TOKEN"][
        "x-caelus-target"
    ] == "runtime"


def test_values_schema_dialect_comes_from_the_document(tmp_path):
    """`validator_for` honors the document's own `$schema`, not a hardcoded draft."""
    catalog_dir = write_catalog(
        tmp_path,
        {
            "immich.yaml": document(
                **{
                    "template.values_schema": {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "prefixItems": [{"type": "string"}],
                    }
                }
            )
        },
    )

    assert load_catalog(catalog_dir)


def test_uncompilable_match_is_rejected(tmp_path):
    _expect_error(
        tmp_path, document(**{"upstream.match": "^v(?P<version>["}), "not a valid regular expression"
    )


def test_match_without_a_version_group_is_rejected(tmp_path):
    _expect_error(
        tmp_path, document(**{"upstream.match": r"^v\d+$"}), "must define a named capture group"
    )


def test_unknown_upstream_source_type_is_rejected(tmp_path):
    _expect_error(
        tmp_path,
        document(**{"upstream.source": {"type": "rss", "url": "https://example.com"}}),
        "union_tag_invalid|does not match any",
    )


def test_missing_upstream_block_is_rejected(tmp_path):
    _expect_error(tmp_path, document(upstream=None), "Field required")


# ---------------------------------------------------------------------------
# Directory-level validation
# ---------------------------------------------------------------------------


def test_duplicate_slugs_identify_both_files(tmp_path):
    catalog_dir = write_catalog(
        tmp_path,
        {"immich.yaml": document(), "immich.yml": document()},
    )

    with pytest.raises(CatalogError, match="duplicate product.slug") as excinfo:
        load_catalog(catalog_dir)
    assert "immich.yaml" in str(excinfo.value)
    assert "immich.yml" in str(excinfo.value)


def test_one_invalid_file_fails_the_whole_directory(tmp_path):
    catalog_dir = write_catalog(
        tmp_path,
        {"immich.yaml": document(), "broken.yaml": document(**{"product.slug": "broken"})},
    )
    # `broken.yaml` declares slug `broken` but references immich's icon, which
    # exists; make it invalid another way.
    (catalog_dir / "broken.yaml").write_text("schema_version: 1\n")

    with pytest.raises(CatalogError, match="broken.yaml"):
        load_catalog(catalog_dir)


def test_non_yaml_files_are_ignored(tmp_path):
    """The generated JSON Schema lives in the directory and is not a document."""
    catalog_dir = write_catalog(tmp_path, {"immich.yaml": document()})
    (catalog_dir / "catalog.schema.json").write_text("{}")
    (catalog_dir / "README.md").write_text("notes")

    assert [entry.slug for entry in load_catalog(catalog_dir)] == ["immich"]


# ---------------------------------------------------------------------------
# Spec hashing
# ---------------------------------------------------------------------------


def test_key_ordering_does_not_change_the_hash(tmp_path):
    ordered = document(**{"template.system_values": {"a": 1, "b": {"x": 1, "y": 2}}})
    shuffled = document(**{"template.system_values": {"b": {"y": 2, "x": 1}, "a": 1}})

    first = load_document(
        write_catalog(tmp_path / "one", {"immich.yaml": ordered}) / "immich.yaml",
        catalog_dir=tmp_path / "one" / "catalog",
    )
    second = load_document(
        write_catalog(tmp_path / "two", {"immich.yaml": shuffled}) / "immich.yaml",
        catalog_dir=tmp_path / "two" / "catalog",
    )

    assert document_spec_hash(first.document) == document_spec_hash(second.document)


def test_hash_covers_each_spec_field():
    base = dict(
        chart_ref="oci://registry/immich",
        chart_version="1.0.0",
        chart_digest=None,
        system_values={"image": {"tag": "v3.0.3"}},
        values_schema={"type": "object"},
    )
    baseline = spec_hash(**base)

    assert spec_hash(**{**base, "chart_ref": "oci://other/immich"}) != baseline
    assert spec_hash(**{**base, "chart_version": "1.0.1"}) != baseline
    assert spec_hash(**{**base, "chart_digest": "sha256:abc"}) != baseline
    assert spec_hash(**{**base, "system_values": {"image": {"tag": "v3.1.0"}}}) != baseline
    assert spec_hash(**{**base, "values_schema": None}) != baseline


def test_absent_system_values_hash_like_an_empty_mapping():
    """A template row stores null where a document defaults to `{}`."""
    assert spec_hash(
        chart_ref="c", chart_version="1", chart_digest=None, system_values=None, values_schema=None
    ) == spec_hash(
        chart_ref="c", chart_version="1", chart_digest=None, system_values={}, values_schema=None
    )


# ---------------------------------------------------------------------------
# Generated JSON Schema
# ---------------------------------------------------------------------------


def test_json_schema_is_emitted_for_editor_completion():
    schema = catalog_document_json_schema()

    assert set(schema["required"]) == {"schema_version", "product", "upstream", "template"}
    assert json.dumps(schema)  # serializable, so it can be written next to the files


def test_dumped_document_round_trips(tmp_path):
    entries = load_catalog(write_catalog(tmp_path, {"immich.yaml": document()}))
    text = dump_document(entries[0].document)

    assert text.startswith("# yaml-language-server: $schema=./catalog.schema.json")
    assert yaml.safe_load(text) == entries[0].document.model_dump(mode="json", exclude_none=True)
