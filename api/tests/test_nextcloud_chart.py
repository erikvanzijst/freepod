"""The Nextcloud admin password reaches the pod from the tenant's vars only.

Under Caelus it is `NEXTCLOUD_ADMIN_PASSWORD`, a required sensitive var, so the
chart must neither carry it in Helm values nor render a copy of its own. A
standalone install has no vars Secret and falls back to a generated password,
never a constant. Shells out to a real `helm template`; skipped when helm is
unavailable.
"""

from __future__ import annotations

import base64
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
