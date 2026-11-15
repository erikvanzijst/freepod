"""The platform's side of the project file: reserved template keys and the
per-product JSON Schema (deployment-project-file)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from sqlmodel import select

from app.models import ProductORM
from app.services.catalog import CatalogError, load_catalog
from tests.conftest import client, db_session  # noqa: F401
from tests.test_catalog_format import document, write_catalog

API_ROOT = Path(__file__).resolve().parents[1]
REPO_CATALOG = API_ROOT.parent / "products" / "catalog"


def _template(client, schema):
    product_id = client.post("/api/products", json={"name": "Reserved", "description": "d"}).json()["id"]
    return product_id, client.post(
        f"/api/products/{product_id}/templates",
        json={"chart_ref": "oci://example/chart", "chart_version": "1.0.0", "values_schema_json": schema},
    )


def test_a_template_declaring_a_top_level_name_is_refused(client):
    schema = {"type": "object", "additionalProperties": False, "properties": {"name": {"type": "string"}}}
    _, resp = _template(client, schema)
    assert resp.status_code == 400
    assert "name" in resp.json()["detail"]


def test_a_nested_name_is_accepted(client):
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"admin": {"type": "object", "properties": {"name": {"type": "string"}}}},
    }
    _, resp = _template(client, schema)
    assert resp.status_code == 201, resp.text


def test_catalog_lint_refuses_a_reserved_key(tmp_path):
    schema = {"type": "object", "additionalProperties": False, "properties": {"deployment": {"type": "string"}}}
    catalog_dir = write_catalog(tmp_path, {"immich.yaml": document(**{"template.values_schema": schema})})
    with pytest.raises(CatalogError, match="deployment"):
        load_catalog(catalog_dir)


def test_catalog_lint_passes_on_the_current_catalog():
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "catalog", "lint", "--dir", str(REPO_CATALOG)],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


CUSTOM_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "x-caelus-vars-additional": True,
    "additionalProperties": False,
    "required": ["hostname"],
    "properties": {
        "hostname": {"type": "string", "title": "hostname"},
        "image": {"type": "string"},
        "auth": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "enabled": {"type": "boolean"},
                "access": {"type": "string", "enum": ["anyone", "listed"]},
                "public": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}


@pytest.fixture
def custom(client, db_session):
    product_id, resp = _template(client, CUSTOM_SCHEMA)
    template_id = resp.json()["id"]
    client.put(f"/api/products/{product_id}", json={"template_id": template_id, "visibility": "public"})
    product = db_session.get(ProductORM, product_id)
    product.slug = "custom"
    db_session.add(product)
    db_session.commit()
    return product_id


def test_the_custom_schema_validates_a_format_2_file(client, custom):
    resp = client.get("/api/products/custom/project-schema", headers={})
    assert resp.status_code == 200, resp.text
    schema = resp.json()
    Draft202012Validator.check_schema(schema)
    assert set(schema["properties"]["auth"]["properties"]) == {"enabled", "access", "public"}
    sample = {
        "$schema": "https://freepod.eu/api/products/custom/project-schema",
        "version": 2,
        "deployment": "6f1c1b1e-7d3a-4d2c-9a65-1f7d2b0c9e11",
        "name": "Arkanoid",
        "description": "A brick breaker",
        "icon": "icon.png",
        "hostname": "arkanoid",
        "auth": {"enabled": True, "access": "anyone", "public": ["^/$"]},
    }
    assert list(Draft202012Validator(schema).iter_errors(sample)) == []
    assert list(Draft202012Validator(schema).iter_errors({**sample, "auht": {}})) != []


def test_the_schema_needs_no_authentication(client, custom):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anonymous:
        assert anonymous.get("/api/products/custom/project-schema").status_code == 200


def test_an_unknown_product_has_no_schema(client, db_session):
    assert client.get("/api/products/nope/project-schema").status_code == 404


def test_a_hidden_product_has_no_schema(client, db_session, custom):
    product = db_session.exec(select(ProductORM).where(ProductORM.slug == "custom")).one()
    product.visibility = "admin"
    db_session.add(product)
    db_session.commit()
    assert client.get("/api/products/custom/project-schema").status_code == 404
