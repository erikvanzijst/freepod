"""Render the `custom` chart and assert the object-storage contract it exposes.

Shells out to a real `helm template`, so these assert what Helm actually
produces — including schema validation, which is the half a Go-template unit
test would miss. Skipped when helm is unavailable; CI runs inside the dev
container, which has it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

from app.services.template_values import merge_values_scoped

CHART = Path(__file__).resolve().parents[2] / "products" / "custom" / "chart"
DIGEST = "sha256:" + "a" * 64

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


@pytest.fixture(scope="module", autouse=True)
def _resolved_dependencies():
    """Vendor the chart's `ssh-sidecar` dependency before anything renders.

    `charts/` is a build artifact -- `products/.gitignore` ignores `**/*.tgz`,
    so a clean checkout has none and `helm template` refuses the chart outright
    with "found in Chart.yaml, but missing in charts/". This chart had no
    dependencies until it adopted the `dev` access profile, which is why the
    fixture arrives later than the tests it serves.

    `build` rather than `update`, so the tracked `Chart.lock` decides what is
    vendored and is not rewritten.
    """
    result = subprocess.run(
        ["helm", "dependency", "build", str(CHART)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _render(**values: str) -> list[dict]:
    args = ["helm", "template", "t", str(CHART)]
    for key, value in values.items():
        args += ["--set", f"{key.replace('__', '.')}={value}"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _app_container(docs: list[dict]) -> dict:
    deployment = next(d for d in docs if d["kind"] == "Deployment")
    return deployment["spec"]["template"]["spec"]["containers"][0]


def _pod_spec(docs: list[dict]) -> dict:
    deployment = next(d for d in docs if d["kind"] == "Deployment")
    return deployment["spec"]["template"]["spec"]


BASE = {
    "hostname": "app.example.test",
    "caelus__owner__id": "1",
}
VARS = {"caelus__vars__secretName": "custom-user-app-abc123-vars"}
STORAGE = {
    "objectStorage__enabled": "true",
    "caelus__objectStorage__bucket": "dep-11115310-fc46-4ef4-8808-654a6b7a68f6",
    "caelus__objectStorage__endpoint": "https://blob.example.invalid",
    "caelus__objectStorage__region": "garage",
    "caelus__objectStorage__secretName": "custom-user-app-abc123-object-storage",
}


DATABASE = {
    "relationalStorage__enabled": "true",
    "caelus__database__host": "caelus-tenant-pooler.caelus-dev.svc.cluster.local",
    "caelus__database__port": "6432",
    "caelus__database__name": "dpl_11115310fc464ef48808654a6b7a68f6",
    "caelus__database__user": "dpl_11115310fc464ef48808654a6b7a68f6",
    "caelus__database__secretName": "custom-user-app-abc123-database",
}


def test_renders_without_storage_and_projects_nothing():
    """A product that has not opted in renders exactly as it did before."""
    container = _app_container(_render(**BASE))
    assert "envFrom" not in container
    # PORT is still injected; the storage block is additive, not a replacement.
    assert {"name": "PORT", "value": "8080"} in container["env"]


def test_renders_with_storage_and_projects_the_secret():
    container = _app_container(_render(**BASE, **STORAGE, image=f"1@{DIGEST}"))
    assert container["envFrom"] == [
        {"secretRef": {"name": "custom-user-app-abc123-object-storage"}}
    ]


def test_storage_enabled_without_a_secret_name_fails_loudly():
    """A reconciler bug must surface as a deployment error naming the missing
    value, not as a pod that silently starts with no credentials."""
    args = ["helm", "template", "t", str(CHART)]
    for key, value in {**BASE, "objectStorage__enabled": "true"}.items():
        args += ["--set", f"{key.replace('__', '.')}={value}"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode != 0
    assert "caelus.objectStorage.secretName is required" in result.stderr


def test_renders_with_a_database_and_projects_the_secret():
    container = _app_container(_render(**BASE, **DATABASE, image=f"1@{DIGEST}"))
    assert container["envFrom"] == [
        {"secretRef": {"name": "custom-user-app-abc123-database"}}
    ]


def test_renders_without_a_database_and_projects_nothing():
    assert "envFrom" not in _app_container(_render(**BASE))


def test_a_database_without_a_secret_name_fails_loudly():
    args = ["helm", "template", "t", str(CHART)]
    for key, value in {**BASE, "relationalStorage__enabled": "true"}.items():
        args += ["--set", f"{key.replace('__', '.')}={value}"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode != 0
    assert "caelus.database.secretName is required" in result.stderr


def test_both_storages_project_in_a_stable_order():
    """Vars first, then the platform's own sources: a tenant var named like an
    injected credential cannot displace it."""
    container = _app_container(
        _render(**BASE, **VARS, **STORAGE, **DATABASE, image=f"1@{DIGEST}")
    )
    assert [next(iter(e["secretRef"]["name"].rsplit("-", 1)[1:])) for e in container["envFrom"]] == [
        "vars",
        "storage",
        "database",
    ]


def test_the_schema_rejects_an_unknown_sibling_of_the_opt_in():
    """`relationalStorage` is closed, so a typo is a rollout error rather than
    a flag that silently does nothing."""
    args = ["helm", "template", "t", str(CHART)]
    for key, value in {**BASE, "relationalStorage__enabledd": "true"}.items():
        args += ["--set", f"{key.replace('__', '.')}={value}"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode != 0
    assert "relationalStorage" in result.stderr


def test_renders_without_vars_and_projects_nothing():
    """No vars, no `envFrom` source: a chart that needs them fails visibly
    rather than rendering an environment that silently provides nothing."""
    assert "envFrom" not in _app_container(_render(**BASE))


def test_renders_with_vars_and_projects_the_secret():
    container = _app_container(_render(**BASE, **VARS))
    assert container["envFrom"] == [
        {"secretRef": {"name": "custom-user-app-abc123-vars"}}
    ]


def test_a_var_cannot_displace_a_platform_injected_variable():
    """Ordering, not trust: a later `envFrom` source overrides an earlier one,
    and an explicit `env` entry beats every `envFrom`. So the tenant's vars go
    first and the platform's sources after them.

    Defense in depth beside the API's reserved-name rejection. Neither is a
    privilege boundary -- a tenant shadowing their own pod's variables harms
    only their own pod -- but the failure it prevents is hard to diagnose.
    """
    container = _app_container(_render(**BASE, **VARS, **STORAGE, image=f"1@{DIGEST}"))

    assert container["envFrom"] == [
        {"secretRef": {"name": "custom-user-app-abc123-vars"}},
        {"secretRef": {"name": "custom-user-app-abc123-object-storage"}},
    ]
    # PORT is set explicitly, which outranks every envFrom source whatever
    # order they are in.
    assert {"name": "PORT", "value": "8080"} in container["env"]


def test_no_service_account_token_is_mounted():
    """Defense in depth: the tenant image is untrusted code and has no business
    talking to the Kubernetes API."""
    assert _pod_spec(_render(**BASE))["automountServiceAccountToken"] is False
    assert _pod_spec(_render(**BASE, **STORAGE))["automountServiceAccountToken"] is False


def test_catalog_system_values_are_valid_values_for_this_chart():
    """`system_values` ARE the chart's default Helm values — the catalog's are
    handed to `helm upgrade` verbatim — so anything the catalog declares must
    satisfy the chart's own `values.schema.json`.

    This is the check that was missing when a platform-only flag was put at the
    top level of `system_values`: every unit test passed, and the first thing to
    notice was `helm upgrade` on a real deployment, rejecting it with
    `additional properties 'object_storage' not allowed`.
    """
    catalog = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "products" / "catalog" / "custom.yaml").read_text()
    )

    # Exactly what the reconciler hands to `helm upgrade`: catalog system values
    # as defaults, then the tenant's values, then the system overrides last.
    merged = merge_values_scoped(
        catalog["template"]["system_values"],
        {"hostname": "app.example.test", "image": f"1@{DIGEST}"},
        {
            "caelus": {
                "owner": {"id": 1, "email": "t@example.test"},
                "plan": {"storageBytes": 1073741824, "storageSize": "1Gi"},
                "ingress": {
                    "enabled": True,
                    "host": "app.example.test",
                    "tls": {"wildcard": True},
                },
                "objectStorage": {
                    "bucket": "dep-11115310-fc46-4ef4-8808-654a6b7a68f6",
                    "endpoint": "https://blob.example.invalid",
                    "region": "garage",
                    "secretName": "custom-user-app-abc123-object-storage",
                },
                "database": {
                    "host": "caelus-tenant-pooler.caelus-dev.svc.cluster.local",
                    "port": 6432,
                    "name": "dpl_11115310fc464ef48808654a6b7a68f6",
                    "user": "dpl_11115310fc464ef48808654a6b7a68f6",
                    "secretName": "custom-user-app-abc123-database",
                },
            }
        },
    )

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(merged, f)
        values_path = f.name
    try:
        result = subprocess.run(
            ["helm", "template", "t", str(CHART), "-f", values_path],
            capture_output=True,
            text=True,
        )
    finally:
        Path(values_path).unlink()

    assert result.returncode == 0, (
        "the catalog's system_values are not valid values for this chart:\n" + result.stderr
    )
    assert "additional properties" not in result.stderr


def test_schema_declares_both_halves_and_requires_neither():
    """`additionalProperties: false` at the top level means the schema has to
    admit these explicitly, and must not require them.

    Two halves, deliberately: the top-level toggle is a static product
    declaration the chart reads, and `caelus.objectStorage` carries the
    per-deployment references the reconciler injects. The toggle must NOT appear
    in the injected half, or there would be two places to set the same thing.
    """
    schema = json.loads((CHART / "values.schema.json").read_text())

    toggle = schema["properties"]["objectStorage"]
    assert set(toggle["properties"]) == {"enabled"}
    assert "objectStorage" not in schema.get("required", [])

    injected = schema["properties"]["caelus"]["properties"]["objectStorage"]
    assert set(injected["properties"]) >= {"bucket", "endpoint", "region", "secretName"}
    assert "enabled" not in injected["properties"]
    assert "required" not in injected
    assert "objectStorage" not in schema["properties"]["caelus"].get("required", [])


def test_the_toggle_is_absent_from_the_tenant_facing_schema():
    """A tenant must not be able to switch object storage on for themselves.

    `user.schema.json` is the tenant-facing contract; the toggle is a system
    value and belongs only in `values.schema.json`.
    """
    user_schema = json.loads((CHART / "user.schema.json").read_text())
    assert "objectStorage" not in user_schema["properties"]
    assert user_schema.get("additionalProperties") is False


def test_the_ownership_assertion_still_holds_with_storage_enabled():
    """Storage must not become a way around the image ownership check."""
    args = ["helm", "template", "t", str(CHART)]
    for key, value in {**BASE, **STORAGE, "image": f"999@{DIGEST}"}.items():
        args += ["--set", f"{key.replace('__', '.')}={value}"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode != 0
    assert "does not match deployment owner" in result.stderr


# ---------------------------------------------------------------------------
# Release labelling
# ---------------------------------------------------------------------------

RELEASE_ID = "3f2a9c14-0b6d-4e18-9a77-5c1e8d4b2f60"


def _pod_template_labels(docs: list[dict]) -> dict:
    deployment = next(d for d in docs if d["kind"] == "Deployment")
    return deployment["spec"]["template"]["metadata"]["labels"]


def _match_labels(docs: list[dict]) -> dict:
    deployment = next(d for d in docs if d["kind"] == "Deployment")
    return deployment["spec"]["selector"]["matchLabels"]


def _service_selector(docs: list[dict]) -> dict:
    return next(d for d in docs if d["kind"] == "Service")["spec"]["selector"]


def test_the_release_id_is_rendered_onto_the_pod_template():
    docs = _render(**BASE, caelus__releaseId=RELEASE_ID)
    assert _pod_template_labels(docs)["caelus.dev/release-id"] == RELEASE_ID


def test_the_release_id_never_reaches_a_selector():
    """The regression that would otherwise surface as `field is immutable` on
    the second apply, and as dropped traffic mid-rollout on the Service."""
    docs = _render(**BASE, caelus__releaseId=RELEASE_ID)
    assert "caelus.dev/release-id" not in _match_labels(docs)
    assert "caelus.dev/release-id" not in _service_selector(docs)
    # The selector must be byte-identical whatever the release is.
    other = _render(**BASE, caelus__releaseId="00000000-0000-0000-0000-000000000000")
    assert _match_labels(docs) == _match_labels(other)
    assert _service_selector(docs) == _service_selector(other)


def test_a_second_apply_with_a_new_release_id_changes_only_the_pod_template():
    """A Deployment's `spec.selector` is immutable, so the second apply of a
    deployment that already exists fails outright if the id leaked into it.
    Rendering both and diffing is what a real second apply would hit."""
    first = _render(**BASE, caelus__releaseId=RELEASE_ID)
    second = _render(**BASE, caelus__releaseId="9c8b7a65-4321-4def-8abc-0123456789ab")

    assert _match_labels(first) == _match_labels(second)
    assert _service_selector(first) == _service_selector(second)
    # ...and the pod template genuinely differs, which is what cycles the pods.
    assert _pod_template_labels(first) != _pod_template_labels(second)


def test_a_redeploy_with_identical_values_is_no_longer_a_helm_no_op():
    """The accepted consequence: a fresh id changes the pod template hash on
    every apply, so an otherwise byte-identical redeploy cycles pods. Matches
    Heroku, Railway and Fly; at `replicas: 1` it costs a brief interruption."""
    first = _render(**BASE, caelus__releaseId=RELEASE_ID)
    second = _render(**BASE, caelus__releaseId="9c8b7a65-4321-4def-8abc-0123456789ab")
    assert first != second


def test_the_chart_still_renders_with_no_release_id():
    """Standalone renders, and any apply that predates the reconciler supplying
    the value, must emit no label at all rather than an empty one."""
    docs = _render(**BASE)
    assert "caelus.dev/release-id" not in _pod_template_labels(docs)
    # And the surrounding labels are untouched.
    assert _pod_template_labels(docs) == _match_labels(docs)


def test_an_empty_release_id_emits_no_label():
    docs = _render(**BASE, caelus__releaseId="")
    assert "caelus.dev/release-id" not in _pod_template_labels(docs)


def test_the_release_id_is_declared_in_values_and_schema():
    values = yaml.safe_load((CHART / "values.yaml").read_text())
    assert values["caelus"]["releaseId"] == ""
    schema = json.loads((CHART / "values.schema.json").read_text())
    assert schema["properties"]["caelus"]["properties"]["releaseId"]["type"] == "string"


def test_the_release_number_is_declared_in_values_and_schema():
    """A *string*, and empty by default. As an integer the standalone default
    would render `0`, which the sidecar cannot tell from release 0 -- it refuses
    to start on an empty value precisely so a missing projection is a pod that
    does not run rather than a banner naming a release nobody made.
    """
    values = yaml.safe_load((CHART / "values.yaml").read_text())
    assert values["caelus"]["releaseNumber"] == ""
    schema = json.loads((CHART / "values.schema.json").read_text())
    assert schema["properties"]["caelus"]["properties"]["releaseNumber"]["type"] == "string"


# ---------------------------------------------------------------------------
# Detecting a startup that fails
# ---------------------------------------------------------------------------


def test_the_pod_must_stay_ready_before_counting_as_available():
    """`helm upgrade --wait` otherwise accepts a container that dies on startup.

    This chart declares no readiness probe, so a container is Ready the instant
    it runs. An application crashing on startup was briefly Ready, Helm saw an
    available ReplicaSet and reported success, `--atomic` rolled nothing back,
    and the platform recorded a crash-looping deployment as `ready`. Observed
    on dev before this was added.
    """
    deployment = next(d for d in _render(**BASE) if d["kind"] == "Deployment")
    assert deployment["spec"]["minReadySeconds"] == 10


def test_no_readiness_probe_is_declared():
    """Deliberate, and worth asserting so it is not added casually.

    Binding `$PORT` is a convention most applications follow, not a
    requirement, and a headless workload would have nothing to probe. A real
    readiness contract needs designing on its own terms rather than being
    inferred from the HTTP case.
    """
    container = _app_container(_render(**BASE))
    assert "readinessProbe" not in container
    assert "livenessProbe" not in container
    assert "startupProbe" not in container
