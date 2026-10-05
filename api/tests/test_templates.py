"""Tests for `app.services.templates.create_template` schema meta-validation.

A template's `values_schema_json` is a JSON Schema document that drives the
tenant-facing user values form. It used to be persisted unchecked, so a typo
such as `{"type": "strng"}` was accepted with a 201 and only surfaced later as
an unhandled `jsonschema.SchemaError` (a *sibling* of `ValidationError`, not a
subclass) when a tenant tried to deploy. `create_template` now meta-validates
the document up front and raises `ValidationException` (HTTP 400).
"""

from __future__ import annotations

import pytest
from sqlmodel import Session

from app.models import ProductCreate, ProductTemplateVersionCreate
from app.services.errors import ValidationException
from app.services.products import create_product
from app.services.templates import create_template

# `strng` is a typo for `string`, which makes the document itself invalid.
MALFORMED_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"host": {"type": "strng"}},
}

VALID_2020_12_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"host": {"type": "string", "title": "hostname"}},
    "required": ["host"],
    "additionalProperties": False,
}


def _make_product(session: Session, name: str = "schemaprod") -> int:
    product = create_product(session, ProductCreate(name=name, description="desc"))
    return product.id


def _payload(product_id: int, schema: dict | None, version: str = "1.0.0"):
    return ProductTemplateVersionCreate(
        product_id=product_id,
        chart_ref="oci://example/chart",
        chart_version=version,
        values_schema_json=schema,
    )


def test_create_template_rejects_malformed_values_schema(db_session):
    product_id = _make_product(db_session)
    with pytest.raises(ValidationException) as exc_info:
        create_template(db_session, _payload(product_id, MALFORMED_SCHEMA))
    assert "values_schema_json" in str(exc_info.value)


def test_create_template_accepts_valid_values_schema(db_session):
    product_id = _make_product(db_session)
    template = create_template(db_session, _payload(product_id, VALID_2020_12_SCHEMA))
    assert template.id is not None
    assert template.values_schema_json == VALID_2020_12_SCHEMA


def test_create_template_accepts_none_values_schema(db_session):
    """Regression guard: `values_schema_json` is optional and stays optional."""
    product_id = _make_product(db_session)
    template = create_template(db_session, _payload(product_id, None))
    assert template.id is not None
    assert template.values_schema_json is None


def test_create_template_honors_declared_2020_12_dialect(db_session):
    """`validator_for` must pick the dialect from the document's own `$schema`.

    `prefixItems` is a 2020-12 construct. Under Draft 7 it is just an unknown
    keyword (so this would pass either way), but `$defs`-style 2020-12 checking
    of it as a schema array only happens with the right validator — and the
    negative half of this test, where `prefixItems` holds a broken subschema,
    is only caught when 2020-12 is actually selected.
    """
    product_id = _make_product(db_session)
    good = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {"ports": {"type": "array", "prefixItems": [{"type": "integer"}]}},
    }
    template = create_template(db_session, _payload(product_id, good))
    assert template.values_schema_json == good

    bad = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"ports": {"type": "array", "prefixItems": [{"type": "intger"}]}},
    }
    with pytest.raises(ValidationException):
        create_template(db_session, _payload(product_id, bad, version="2.0.0"))


def test_create_template_rejects_an_illegal_routing_marker(db_session):
    """A bad marker has to fail in front of its author. By the time a tenant
    deploys, the template is the one their deployment already points at."""
    product_id = _make_product(db_session, name="markerprod")
    with pytest.raises(ValidationException) as exc_info:
        create_template(
            db_session,
            _payload(
                product_id,
                {
                    "type": "object",
                    "properties": {
                        "PORT": {"type": "integer", "x-caelus-target": "runtime"}
                    },
                },
            ),
        )
    assert "PORT" in str(exc_info.value)


def test_create_template_accepts_a_legal_routing_marker(db_session):
    product_id = _make_product(db_session, name="markerokprod")
    template = create_template(
        db_session,
        _payload(
            product_id,
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "host": {"type": "string"},
                    "ADMIN_TOKEN": {
                        "type": "string",
                        "x-caelus-target": "runtime",
                        "x-caelus-sensitive": True,
                    },
                },
            },
        ),
    )
    assert template.values_schema_json["properties"]["ADMIN_TOKEN"][
        "x-caelus-sensitive"
    ] is True


def test_create_template_rest_returns_400_for_malformed_schema(client):
    prod_resp = client.post("/api/products", json={"name": "restschema", "description": "d"})
    assert prod_resp.status_code == 201
    prod_id = prod_resp.json()["id"]

    resp = client.post(
        f"/api/products/{prod_id}/templates",
        json={
            "chart_ref": "oci://example/chart",
            "chart_version": "1.0.0",
            "values_schema_json": MALFORMED_SCHEMA,
        },
    )
    assert resp.status_code == 400, resp.text
    assert "values_schema_json" in resp.json()["detail"]


def test_create_template_rest_accepts_valid_schema(client):
    prod_resp = client.post("/api/products", json={"name": "restschemaok", "description": "d"})
    assert prod_resp.status_code == 201
    prod_id = prod_resp.json()["id"]

    resp = client.post(
        f"/api/products/{prod_id}/templates",
        json={
            "chart_ref": "oci://example/chart",
            "chart_version": "1.0.0",
            "values_schema_json": VALID_2020_12_SCHEMA,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["values_schema_json"] == VALID_2020_12_SCHEMA
