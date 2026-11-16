"""The `.freepod.json` project file."""

from __future__ import annotations

import json

import pytest

from freepod import FreepodError, UsageError
from freepod.project import (
    FORMAT_VERSION,
    PROJECT_FILE,
    Project,
    find_project_root,
    load,
    require_project,
    schema_url,
)

DEPLOYMENT_ID = "40bd8dea-54f3-430d-8ee0-f1689f9629cb"
PROD_SCHEMA = "https://freepod.eu/api/products/custom/project-schema"
DEV_SCHEMA = "https://dev.freepod.eu/api/products/custom/project-schema"


def write_document(root, document):
    (root / PROJECT_FILE).write_text(json.dumps(document, indent=2), encoding="utf-8")
    return root


def write_project(root, **overrides):
    document = {"$schema": PROD_SCHEMA, "version": FORMAT_VERSION, "hostname": "myapp"}
    document.update(overrides)
    return write_document(root, document)


def saved(root):
    return json.loads((root / PROJECT_FILE).read_text())


# --------------------------------------------------------------------------
# Format 2
# --------------------------------------------------------------------------


def test_an_unlinked_project_holds_schema_version_and_its_fields(tmp_path):
    Project(root=tmp_path, schema=PROD_SCHEMA, fields={"name": "Arkanoid"}).save()

    assert saved(tmp_path) == {"$schema": PROD_SCHEMA, "version": 2, "name": "Arkanoid"}


def test_the_file_is_flat(tmp_path):
    Project(
        root=tmp_path,
        deployment_id=DEPLOYMENT_ID,
        fields={"name": "Arkanoid", "auth": {"enabled": True}},
    ).save()

    document = saved(tmp_path)
    assert document["name"] == "Arkanoid"
    assert document["auth"] == {"enabled": True}
    assert "user_values" not in document


def test_the_file_carries_no_credential_material(tmp_path):
    Project(root=tmp_path, deployment_id=DEPLOYMENT_ID, fields={"hostname": "a"}).save()

    text = (tmp_path / PROJECT_FILE).read_text().lower()
    for forbidden in ("token", "secret", "password", "authorization", "bearer"):
        assert forbidden not in text


def test_the_pointer_is_the_id_alone_and_saved_at_once(tmp_path):
    project = Project(root=tmp_path, fields={"hostname": "a"})
    project.record_deployment(DEPLOYMENT_ID, "https://dev.freepod.eu")

    document = saved(tmp_path)
    assert document["deployment"] == DEPLOYMENT_ID
    assert document["$schema"] == DEV_SCHEMA
    assert load(tmp_path).deployment_id == DEPLOYMENT_ID


def test_forgetting_the_pointer_removes_the_key_and_keeps_the_rest(tmp_path):
    project = Project(
        root=tmp_path, deployment_id=DEPLOYMENT_ID, fields={"name": "A", "hostname": "a"}
    )
    project.forget_deployment()

    assert saved(tmp_path) == {"version": 2, "name": "A", "hostname": "a"}


def test_a_null_pointer_is_refused_naming_the_fix(tmp_path):
    write_project(tmp_path, deployment=None)
    with pytest.raises(FreepodError, match="Remove the key"):
        load(tmp_path)


def test_a_pointer_that_is_not_a_string_is_refused(tmp_path):
    write_project(tmp_path, deployment={"id": DEPLOYMENT_ID})
    with pytest.raises(FreepodError, match="'deployment'"):
        load(tmp_path)


def test_an_image_in_the_file_is_refused_as_a_build_output(tmp_path):
    write_project(tmp_path, image="7@sha256:" + "a" * 64)
    with pytest.raises(FreepodError, match="'image' is a build output"):
        load(tmp_path)


def test_an_image_is_never_written(tmp_path):
    project = Project(root=tmp_path, fields={"hostname": "a"})
    project.set_chart_values({"hostname": "a", "image": "7@sha256:" + "a" * 64})
    project.save()

    assert "image" not in saved(tmp_path)


def test_user_values_in_a_format_2_file_is_refused(tmp_path):
    write_project(tmp_path, user_values={"hostname": "a"})
    with pytest.raises(FreepodError, match="format 1"):
        load(tmp_path)


def test_the_accessors_split_identity_chart_values_and_managed_keys(tmp_path):
    write_project(
        tmp_path, deployment=DEPLOYMENT_ID, name="Arkanoid", icon="icon.png", auth={"enabled": True}
    )
    project = load(tmp_path)

    assert project.identity == {"name": "Arkanoid", "icon": "icon.png"}
    assert project.chart_values == {"hostname": "myapp", "auth": {"enabled": True}}
    assert project.managed_fields == ["auth", "hostname", "icon", "name"]


def test_setting_chart_values_keeps_the_identity(tmp_path):
    project = Project(root=tmp_path, fields={"name": "Arkanoid", "hostname": "a"})
    project.set_chart_values({"hostname": "b", "auth": {"enabled": True}})

    assert project.fields == {"name": "Arkanoid", "hostname": "b", "auth": {"enabled": True}}


def test_the_schema_names_the_environment(tmp_path):
    assert schema_url("https://dev.freepod.eu/") == DEV_SCHEMA


def test_the_file_ends_with_a_newline(tmp_path):
    Project(root=tmp_path).save()
    assert (tmp_path / PROJECT_FILE).read_text().endswith("\n")


# --------------------------------------------------------------------------
# Format 1 migration (design D8)
# --------------------------------------------------------------------------


def _v1(root, deployment, values, **extra):
    return write_document(
        root, {"version": 1, **extra, "deployment": deployment, "user_values": values}
    )


def test_a_never_deployed_format_1_project_is_unlinked(tmp_path, capsys):
    _v1(tmp_path, None, {"hostname": "arkanoid"})

    project = load(tmp_path)

    assert project.deployment_id is None
    assert saved(tmp_path) == {"$schema": PROD_SCHEMA, "version": 2}
    assert "freepod init" in capsys.readouterr().err


def test_a_linked_format_1_project_is_rewritten_at_once_without_its_hostname(tmp_path, capsys):
    _v1(
        tmp_path,
        {"id": DEPLOYMENT_ID, "name": "custom-d8dtx4"},
        {"hostname": "arkanoid", "auth": {"enabled": True}, "image": "x"},
        env="dev",
    )

    load(tmp_path)

    assert saved(tmp_path) == {
        "$schema": DEV_SCHEMA,
        "version": 2,
        "env": "dev",
        "deployment": DEPLOYMENT_ID,
        "auth": {"enabled": True},
    }
    assert "Migrated" in capsys.readouterr().err


def test_a_format_1_pointer_without_an_id_is_refused(tmp_path):
    _v1(tmp_path, {"name": "custom-abc"}, {})
    with pytest.raises(FreepodError, match="'id'"):
        load(tmp_path)


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def test_the_project_root_is_found_from_a_subdirectory(tmp_path):
    write_project(tmp_path)
    nested = tmp_path / "src" / "deep" / "deeper"
    nested.mkdir(parents=True)

    assert find_project_root(nested) == tmp_path.resolve()


def test_the_nearest_project_file_wins(tmp_path):
    write_project(tmp_path)
    inner = tmp_path / "packages" / "api"
    inner.mkdir(parents=True)
    write_project(inner)

    assert find_project_root(inner / "src") == inner.resolve()


def test_no_project_file_yields_no_root(tmp_path):
    assert find_project_root(tmp_path) is None


def test_a_command_from_a_subdirectory_loads_the_root_project(tmp_path):
    write_project(tmp_path)
    nested = tmp_path / "src"
    nested.mkdir()

    project = require_project(start=nested)
    assert project.root == tmp_path.resolve()
    assert project.hostname == "myapp"


# --------------------------------------------------------------------------
# Not initialized
# --------------------------------------------------------------------------


def test_an_uninitialized_directory_names_the_init_command(tmp_path):
    with pytest.raises(UsageError) as raised:
        require_project(start=tmp_path)

    message = str(raised.value)
    assert "not initialized" in message
    assert "freepod init" in message
    assert PROJECT_FILE in message


def test_an_uninitialized_directory_is_a_usage_error(tmp_path):
    from freepod import EXIT_USAGE

    with pytest.raises(UsageError) as raised:
        require_project(start=tmp_path)
    assert raised.value.exit_code == EXIT_USAGE


# --------------------------------------------------------------------------
# The declared environment
# --------------------------------------------------------------------------


def test_the_declared_environment_is_not_refused(tmp_path):
    write_project(tmp_path, env="dev")
    assert require_project(start=tmp_path).env == "dev"


def test_a_missing_environment_means_prod_and_stays_missing(tmp_path):
    write_project(tmp_path)
    project = load(tmp_path)
    assert project.env == "prod"

    project.record_deployment(DEPLOYMENT_ID)
    assert "env" not in saved(tmp_path)


def test_an_explicit_prod_environment_is_kept(tmp_path):
    write_project(tmp_path, env="prod")
    project = load(tmp_path)
    assert project.env == "prod"

    project.record_deployment(DEPLOYMENT_ID)
    assert saved(tmp_path)["env"] == "prod"


def test_an_empty_environment_is_rejected(tmp_path):
    write_project(tmp_path, env="")
    with pytest.raises(FreepodError, match="'env'"):
        load(tmp_path)


# --------------------------------------------------------------------------
# Malformed files and saving
# --------------------------------------------------------------------------


def test_invalid_json_is_reported_with_the_path(tmp_path):
    (tmp_path / PROJECT_FILE).write_text("{not json", encoding="utf-8")
    with pytest.raises(FreepodError, match="not valid JSON"):
        load(tmp_path)


def test_a_future_format_version_asks_for_an_upgrade(tmp_path):
    write_project(tmp_path, version=FORMAT_VERSION + 1)
    with pytest.raises(FreepodError, match="upgrade freepod"):
        load(tmp_path)


def test_a_failed_save_leaves_no_temporary_behind(tmp_path):
    Project(root=tmp_path, fields={"hostname": "a"}).save()
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_saving_is_atomic_over_an_existing_file(tmp_path):
    write_project(tmp_path)
    original = (tmp_path / PROJECT_FILE).read_text()

    project = load(tmp_path)
    project.fields["hostname"] = "changed"
    project.save()

    assert (tmp_path / PROJECT_FILE).read_text() != original
    assert load(tmp_path).hostname == "changed"
