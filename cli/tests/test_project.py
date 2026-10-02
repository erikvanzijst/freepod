"""The `.freepod.json` project file."""

from __future__ import annotations

import json
import os

import pytest

from freepod import FreepodError, UsageError
from freepod.project import (
    FORMAT_VERSION,
    PROJECT_FILE,
    Project,
    find_project_root,
    load,
    require_project,
)


def write_project(root, **overrides):
    document = {
        "version": FORMAT_VERSION,
        "env": "prod",
        "deployment": None,
        "user_values": {"hostname": "myapp.freepod.eu"},
    }
    document.update(overrides)
    (root / PROJECT_FILE).write_text(json.dumps(document, indent=2), encoding="utf-8")
    return root


# --------------------------------------------------------------------------
# Format (task 5.2)
# --------------------------------------------------------------------------


def test_a_project_before_its_first_deploy_has_an_empty_pointer(tmp_path):
    project = Project(root=tmp_path, env="prod", user_values={"hostname": "a.freepod.eu"})
    project.save()

    document = json.loads((tmp_path / PROJECT_FILE).read_text())
    assert document["version"] == FORMAT_VERSION
    assert document["env"] == "prod"
    assert document["deployment"] is None
    assert document["user_values"] == {"hostname": "a.freepod.eu"}


def test_the_file_carries_no_credential_material(tmp_path):
    project = Project(root=tmp_path, env="prod", user_values={"hostname": "a.freepod.eu"})
    project.save()

    text = (tmp_path / PROJECT_FILE).read_text().lower()
    for forbidden in ("token", "secret", "password", "authorization", "bearer"):
        assert forbidden not in text


def test_the_pointer_records_identifier_and_name(tmp_path):
    project = Project(root=tmp_path, env="prod", user_values={"hostname": "a.freepod.eu"})
    project.record_deployment("40bd8dea-54f3-430d-8ee0-f1689f9629cb", "custom-d8dtx4")

    document = json.loads((tmp_path / PROJECT_FILE).read_text())
    assert document["deployment"] == {
        "id": "40bd8dea-54f3-430d-8ee0-f1689f9629cb",
        "name": "custom-d8dtx4",
    }
    # Persisted immediately: a deployment that exists but is unrecorded is one
    # the user cannot see, address, or delete.
    assert load(tmp_path).deployment_name == "custom-d8dtx4"


def test_the_file_ends_with_a_newline(tmp_path):
    Project(root=tmp_path, env="prod").save()
    assert (tmp_path / PROJECT_FILE).read_text().endswith("\n")


# --------------------------------------------------------------------------
# image is never written (task 5.4)
# --------------------------------------------------------------------------


def test_an_image_is_never_written_as_a_value(tmp_path):
    project = Project(
        root=tmp_path,
        env="prod",
        user_values={"hostname": "a.freepod.eu", "image": "5@sha256:" + "a" * 64},
    )
    project.save()

    document = json.loads((tmp_path / PROJECT_FILE).read_text())
    assert "image" not in document["user_values"]
    assert document["user_values"] == {"hostname": "a.freepod.eu"}


def test_an_image_is_never_written_as_null(tmp_path):
    """The schema declares image as a string, so a null fails validation."""
    project = Project(root=tmp_path, env="prod", user_values={"hostname": "a.freepod.eu"})
    project.user_values["image"] = None
    project.save()

    raw = (tmp_path / PROJECT_FILE).read_text()
    assert "image" not in raw
    assert "null" in raw  # the deployment pointer, which legitimately is null


def test_a_successful_deploy_leaves_user_values_unchanged(tmp_path):
    """The release composes image + values for the API; the file keeps intent."""
    write_project(tmp_path)
    project = load(tmp_path)
    before = dict(project.user_values)

    # What a release does: build a submission document, then record the pointer.
    submitted = dict(project.user_values)
    submitted["image"] = "5@sha256:" + "b" * 64
    project.record_deployment("id-1", "custom-abc123")

    assert load(tmp_path).user_values == before
    assert "image" not in load(tmp_path).user_values
    assert submitted["image"]  # the image did travel, just not to disk


# --------------------------------------------------------------------------
# Discovery (task 5.1)
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
    assert project.hostname == "myapp.freepod.eu"


# --------------------------------------------------------------------------
# Not initialized (task 5.5)
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
# The declared environment (task 5.3)
# --------------------------------------------------------------------------


def test_the_declared_environment_is_not_refused(tmp_path):
    """The file's environment is the default target of every command run from
    this directory, not a check: a command that disagrees with it is the
    caller's to reconcile, and it alone knows what the recorded deployment is
    for."""
    write_project(tmp_path, env="dev")
    assert require_project(start=tmp_path).env == "dev"


# --------------------------------------------------------------------------
# Malformed files
# --------------------------------------------------------------------------


def test_invalid_json_is_reported_with_the_path(tmp_path):
    (tmp_path / PROJECT_FILE).write_text("{not json", encoding="utf-8")
    with pytest.raises(FreepodError, match="not valid JSON"):
        load(tmp_path)


def test_a_missing_environment_means_prod_and_stays_missing(tmp_path):
    (tmp_path / PROJECT_FILE).write_text(json.dumps({"version": 1}), encoding="utf-8")
    project = load(tmp_path)
    assert project.env == "prod"

    project.record_deployment("40bd8dea", "custom-d8dtx4")
    assert "env" not in json.loads((tmp_path / PROJECT_FILE).read_text())


def test_an_explicit_prod_environment_is_kept(tmp_path):
    (tmp_path / PROJECT_FILE).write_text(
        json.dumps({"version": 1, "env": "prod"}), encoding="utf-8"
    )
    project = load(tmp_path)
    assert project.env == "prod"

    project.record_deployment("40bd8dea", "custom-d8dtx4")
    assert json.loads((tmp_path / PROJECT_FILE).read_text())["env"] == "prod"


def test_an_empty_environment_is_rejected(tmp_path):
    (tmp_path / PROJECT_FILE).write_text(
        json.dumps({"version": 1, "env": ""}), encoding="utf-8"
    )
    with pytest.raises(FreepodError, match="'env'"):
        load(tmp_path)


def test_a_future_format_version_asks_for_an_upgrade(tmp_path):
    write_project(tmp_path, version=FORMAT_VERSION + 1)
    with pytest.raises(FreepodError, match="upgrade freepod"):
        load(tmp_path)


def test_a_deployment_without_an_id_is_rejected(tmp_path):
    write_project(tmp_path, deployment={"name": "custom-abc"})
    with pytest.raises(FreepodError, match="'id'"):
        load(tmp_path)


def test_a_missing_user_values_block_reads_as_empty(tmp_path):
    (tmp_path / PROJECT_FILE).write_text(
        json.dumps({"version": 1, "env": "prod"}), encoding="utf-8"
    )
    assert load(tmp_path).user_values == {}


def test_a_failed_save_leaves_no_temporary_behind(tmp_path):
    project = Project(root=tmp_path, env="prod", user_values={"hostname": "a"})
    project.save()
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_saving_is_atomic_over_an_existing_file(tmp_path):
    write_project(tmp_path)
    original = (tmp_path / PROJECT_FILE).read_text()

    project = load(tmp_path)
    project.user_values["hostname"] = "changed.freepod.eu"
    project.save()

    assert (tmp_path / PROJECT_FILE).read_text() != original
    assert load(tmp_path).hostname == "changed.freepod.eu"
