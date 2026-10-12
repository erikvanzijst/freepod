"""The Nextcloud chart: admin password handling and the app-install hook.

The admin password reaches the pod from the tenant's vars only. Under Caelus it
is `NEXTCLOUD_ADMIN_PASSWORD`, a required sensitive var, so the chart must
neither carry it in Helm values nor render a copy of its own. A standalone
install has no vars Secret and falls back to a generated password, never a
constant.

The `before-starting` hook `apps.sh` installs Calendar and Contacts. It runs
here against a stub `php` that plays `occ`. Shells out to a real `helm
template`; skipped when helm is unavailable.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PRODUCTS = Path(__file__).resolve().parents[2] / "products"
CHART = PRODUCTS / "nextcloud" / "chart"
CATALOG = PRODUCTS / "catalog" / "nextcloud.yaml"
VAR = "NEXTCLOUD_ADMIN_PASSWORD"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


@pytest.fixture(scope="module", autouse=True)
def _resolved_dependencies():
    result = subprocess.run(
        ["helm", "dependency", "build", str(CHART)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def _render(tmp_path: Path, values: dict) -> list[dict]:
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.safe_dump({"host": "cloud.example.test", **values}))
    result = subprocess.run(
        ["helm", "template", "t", str(CHART), "-f", str(values_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]


def _secrets(docs: list[dict]) -> dict[str, dict[str, str]]:
    out = {}
    for doc in docs:
        if doc["kind"] != "Secret":
            continue
        data = dict(doc.get("stringData") or {})
        data.update(
            {k: base64.b64decode(v).decode() for k, v in (doc.get("data") or {}).items()}
        )
        out[doc["metadata"]["name"]] = data
    return out


def _nextcloud(docs: list[dict]) -> dict:
    for doc in docs:
        if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "t-nextcloud":
            return next(
                c for c in doc["spec"]["template"]["spec"]["containers"] if c["name"] == "nextcloud"
            )
    raise AssertionError("no nextcloud container")


def _secret_sources(container: dict) -> list[str]:
    return [s["secretRef"]["name"] for s in container["envFrom"] if "secretRef" in s]


def test_the_catalog_asks_for_the_password_as_a_required_sensitive_var():
    schema = yaml.safe_load(CATALOG.read_text())["template"]["values_schema"]
    prop = schema["properties"][VAR]
    assert prop["x-caelus-target"] == "runtime"
    assert prop["x-caelus-sensitive"] is True
    assert VAR in schema["required"]


def test_a_platform_supplied_password_suppresses_the_generated_one(tmp_path):
    system_values = yaml.safe_load(CATALOG.read_text())["template"]["system_values"]
    docs = _render(tmp_path, {**system_values, "caelus": {"vars": {"secretName": "t-vars"}}})

    secrets = _secrets(docs)
    assert "t-admin" not in secrets
    assert all(VAR not in data and "admin-password" not in data for data in secrets.values())

    container = _nextcloud(docs)
    assert _secret_sources(container) == ["t-vars", "t-db"]
    assert VAR not in {e["name"] for e in container.get("env", [])}


def test_a_standalone_install_generates_a_password(tmp_path):
    docs = _render(tmp_path, {})

    password = _secrets(docs)["t-admin"][VAR]
    assert len(password) >= 10 and password != "changeme"
    assert _secret_sources(_nextcloud(docs))[0] == "t-admin"


def test_a_standalone_install_honors_an_explicit_password(tmp_path):
    docs = _render(tmp_path, {"admin": {"username": "admin", "password": "pinned-by-hand"}})
    assert _secrets(docs)["t-admin"][VAR] == "pinned-by-hand"


_FAKE_PHP = r"""#!/bin/sh
shift  # the occ path
echo "$*" >> "$CALLS"
case "$1" in
    app:list) [ -z "$LIST_FAILS" ] || exit 1; printf '%s' "$APP_LIST" ;;
    config:app:get)
        case " $INSTALLED " in *" $2 "*) echo 1.0.0 ;; *) exit 1 ;; esac ;;
    app:install) exit "${INSTALL_RC:-0}" ;;
esac
"""


def _hooks(tmp_path: Path) -> dict[str, str]:
    for doc in _render(tmp_path, {}):
        if doc["kind"] == "ConfigMap" and doc["metadata"]["name"] == "t-hooks":
            return doc["data"]
    raise AssertionError("no hooks ConfigMap")


def _run_apps_hook(tmp_path: Path, *, app_list="", installed="", install_rc=0, list_fails=False):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    php = bin_dir / "php"
    php.write_text(_FAKE_PHP)
    php.chmod(0o755)
    hook = tmp_path / "apps.sh"
    hook.write_text(_hooks(tmp_path)["apps.sh"])
    calls = tmp_path / "calls"
    calls.touch()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CALLS": str(calls),
        "APP_LIST": app_list,
        "INSTALLED": installed,
        "INSTALL_RC": str(install_rc),
        "LIST_FAILS": "1" if list_fails else "",
    }
    result = subprocess.run(["sh", str(hook)], env=env, capture_output=True, text=True)
    installs = [c.split()[1] for c in calls.read_text().splitlines() if c.startswith("app:install")]
    return result, installs


def test_the_apps_hook_runs_first_among_the_boot_hooks(tmp_path):
    assert sorted(_hooks(tmp_path))[0] == "apps.sh"


def test_the_apps_hook_installs_calendar_and_contacts_on_a_bare_instance(tmp_path):
    result, installs = _run_apps_hook(tmp_path, app_list="Enabled:\n  - dav: 2.0.0\nDisabled:\n")
    assert result.returncode == 0
    assert installs == ["calendar", "contacts"]


def test_the_apps_hook_leaves_listed_apps_alone_enabled_or_disabled(tmp_path):
    listing = "Enabled:\n  - calendar: 6.6.2\nDisabled:\n  - contacts: 8.9.1 (installed 8.9.1)\n"
    result, installs = _run_apps_hook(tmp_path, app_list=listing)
    assert result.returncode == 0
    assert installs == []


def test_the_apps_hook_does_not_reinstall_a_removed_app(tmp_path):
    result, installs = _run_apps_hook(tmp_path, app_list="Enabled:\n", installed="calendar")
    assert result.returncode == 0
    assert installs == ["contacts"]


def test_a_failed_install_never_fails_the_hook(tmp_path):
    result, installs = _run_apps_hook(tmp_path, install_rc=1)
    assert result.returncode == 0
    assert installs == ["calendar", "contacts"]
    assert "could not install contacts" in result.stdout


def test_a_timed_out_install_skips_the_remaining_apps(tmp_path):
    result, installs = _run_apps_hook(tmp_path, install_rc=124)
    assert result.returncode == 0
    assert installs == ["calendar"]


def test_the_apps_hook_does_nothing_when_occ_cannot_list_apps(tmp_path):
    result, installs = _run_apps_hook(tmp_path, list_fails=True)
    assert result.returncode == 0
    assert installs == []
