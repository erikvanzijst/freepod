"""`caelus create-deployment` and `update-deployment` carry the identity and
managed fields the REST contract does."""

from __future__ import annotations

import io

import yaml
from PIL import Image

from app.models import ProductORM, ProductTemplateVersionORM
from tests.conftest import create_free_plan_template, make_accepted_user

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "host": {"type": "string", "title": "hostname"},
        "auth": {"type": "object", "properties": {"enabled": {"type": "boolean"}}},
    },
}


def _setup(db_session):
    user = make_accepted_user(db_session, "owner@example.com")
    product = ProductORM(name="Nextcloud")
    db_session.add(product)
    db_session.flush()
    template = ProductTemplateVersionORM(
        product_id=product.id, chart_ref="oci://example/chart", chart_version="1.0.0", values_schema_json=SCHEMA
    )
    db_session.add(template)
    db_session.flush()
    product.template_id = template.id
    db_session.commit()
    return user.id, template.id, create_free_plan_template(db_session, product.id)


def _icon(tmp_path):
    path = tmp_path / "icon.png"
    out = io.BytesIO()
    Image.new("RGB", (32, 32), "blue").save(out, format="PNG")
    path.write_bytes(out.getvalue())
    return path


def test_create_and_update_carry_the_identity(cli_runner, db_session, tmp_path):
    runner, app = cli_runner
    user_id, template_id, plan_id = _setup(db_session)

    created = runner.invoke(
        app,
        [
            "create-deployment", "--user-id", str(user_id), "--desired-template-id", str(template_id),
            "--plan-template-id", str(plan_id), "--user-values-json", '{"host": "a.example.com"}',
            "--name", "Arkanoid", "--description", "Bricks", "--icon", str(_icon(tmp_path)),
            "--managed-fields", "name,auth",
        ],
    )
    assert created.exit_code == 0, created.output
    read = yaml.safe_load(created.stdout)
    assert (read["name"], read["description"], read["managed_fields"]) == ("Arkanoid", "Bricks", ["name", "auth"])
    assert read["icon_url"]

    refused = runner.invoke(
        app, ["update-deployment", "--user-id", str(user_id), "--deployment-id", read["id"], "--name", "Pong"]
    )
    assert refused.exit_code == 1
    assert "managed by the project file" in refused.output

    renamed = runner.invoke(
        app,
        [
            "update-deployment", "--user-id", str(user_id), "--deployment-id", read["id"],
            "--name", "Pong", "--description", "", "--clear-icon", "--managed-fields", "",
        ],
    )
    assert renamed.exit_code == 0, renamed.output
    after = yaml.safe_load(renamed.stdout)
    assert (after["name"], after["description"], after["icon_url"], after["managed_fields"]) == ("Pong", None, None, [])
    assert after["status"] == "provisioning"
    assert after["desired_template_id"] == template_id


def test_icon_and_clear_icon_are_exclusive(cli_runner, db_session, tmp_path):
    runner, app = cli_runner
    result = runner.invoke(
        app,
        [
            "update-deployment", "--user-id", "1", "--deployment-id", "00000000-0000-0000-0000-000000000000",
            "--icon", str(_icon(tmp_path)), "--clear-icon",
        ],
    )
    assert result.exit_code == 1
    assert "only one of --icon or --clear-icon" in result.output
