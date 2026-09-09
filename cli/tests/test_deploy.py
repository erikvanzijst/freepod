"""Deploy preflight, release, and rollout (tasks 10.1 - 10.13)."""

from __future__ import annotations

import io
import json
import re

import httpx
import pytest

from freepod import FreepodError, RolloutFailed, UsageError
from freepod.deploy import (
    describe_conflict,
    deploy,
    follow_rollout,
    preflight,
    release,
    select_free_plan,
    wait_until_settled,
)
from freepod.project import load

from conftest import json_response

IMAGE = "7@sha256:" + "a" * 64
TOS_VERSION = "2026-07-01"

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "hostname": {
            "type": "string",
            "title": "hostname",
            "minLength": 1,
            "maxLength": 253,
            "description": "The fully qualified hostname for the app.",
        },
        "image": {
            "type": "string",
            "pattern": "^$|^[0-9]+@sha256:[a-f0-9]{64}$",
        },
    },
    "required": ["hostname"],
    "additionalProperties": False,
}


def template(id=49, chart_version="0.1.0", schema=None):
    return {
        "id": id,
        "product_id": 12,
        "chart_ref": "oci://registry.home/helm/custom",
        "chart_version": chart_version,
        "values_schema_json": SCHEMA if schema is None else schema,
    }


def product(**kwargs):
    return {
        "id": 12,
        "slug": "custom",
        "name": "Custom user app",
        "template": kwargs.pop("template", template()),
        **kwargs,
    }


def plan(id=9, name="Free", price_cents=0, template_id=11):
    return {
        "id": id,
        "name": name,
        "product_id": 12,
        "template": {"id": template_id, "plan_id": id, "price_cents": price_cents},
    }


def deployment(
    id="40bd8dea-0000-4000-8000-000000000001",
    name="custom-d8dtx4",
    status="ready",
    generation=3,
    hostname="myapp.erik.freepod.eu",
    template_id=49,
    chart_version="0.1.0",
    last_error=None,
):
    return {
        "id": id,
        "name": name,
        "namespace": "u7",
        "status": status,
        "generation": generation,
        "hostname": hostname,
        "last_error": last_error,
        "user_id": 7,
        "desired_template_id": template_id,
        "desired_template": template(id=template_id, chart_version=chart_version),
        "user_values_json": {"hostname": hostname},
    }


# --------------------------------------------------------------------------
# The fake platform
# --------------------------------------------------------------------------


class Store:
    """The object store: accepts the presigned POST and records it."""

    def __init__(self, status=204):
        self.status = status
        self.submissions = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.submissions.append(request)
        return httpx.Response(self.status)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


class Platform:
    """A scripted Freepod API covering everything a deploy touches.

    `reads` is the queue of deployment records successive
    `GET /api/users/{id}/deployments/{id}` calls return, repeating the last
    forever — which is how a test scripts a rollout without a clock.
    """

    def __init__(
        self,
        *,
        user_id=7,
        catalog=None,
        plans=None,
        reads=None,
        deployment_missing=False,
        create=None,
        create_status=201,
        create_detail=None,
        update=None,
        update_status=200,
        update_detail=None,
        hostname_usable=True,
        hostname_reason=None,
        image=IMAGE,
        checkout_url=None,
        tos_version=TOS_VERSION,
        tos_current=TOS_VERSION,
        tos_post_status=200,
        subdomain=None,
    ):
        self.user_id = user_id
        self.catalog = [product()] if catalog is None else catalog
        self.plans = [plan()] if plans is None else plans
        self.reads = list(reads) if reads else [deployment()]
        self.deployment_missing = deployment_missing
        self.create = create
        self.create_status = create_status
        self.create_detail = create_detail
        self.update = update
        self.update_status = update_status
        self.update_detail = update_detail
        self.hostname_usable = hostname_usable
        self.hostname_reason = hostname_reason
        self.image = image
        self.checkout_url = checkout_url
        # Accepted by default: the terms are a first-deploy precondition, not
        # the subject of most of these tests.
        self.tos_version = tos_version
        self.tos_current = tos_current
        self.tos_post_status = tos_post_status
        # Held by default: a domain name is a first-deploy precondition, not the
        # subject of most of these tests.
        self.subdomain = (
            {"subdomain": "erik", "fqdn": "erik.freepod.eu", "domain": "freepod.eu"}
            if subdomain is None
            else subdomain
        )

        self.calls = []
        self.bodies = {}
        self.hostname_checks = []

    # -- routing ----------------------------------------------------------

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        self.calls.append((method, path))

        if path == "/api/me":
            return json_response(200, {"id": self.user_id, "email": "dev@example.com"})

        if path == "/api/me/tos-acceptance":
            if method == "POST":
                self.bodies["tos"] = json.loads(request.content)
                if self.tos_post_status != 200:
                    return json_response(self.tos_post_status, {"detail": "changed"})
                self.tos_version = self.bodies["tos"]["version"]
            return json_response(
                200,
                {
                    "version": self.tos_version,
                    "accepted_at": "2026-08-15T00:00:00Z" if self.tos_version else None,
                    "current_version": self.tos_current,
                },
            )

        if path == "/api/products":
            return json_response(200, self.catalog)

        if re.fullmatch(r"/api/products/\d+/plans", path):
            return json_response(200, self.plans)

        if path == "/api/me/subdomain":
            return json_response(200, self.subdomain)

        if path.startswith("/api/hostnames/"):
            fqdn = path.rsplit("/", 1)[-1]
            self.hostname_checks.append(fqdn)
            return json_response(
                200,
                {"fqdn": fqdn, "usable": self.hostname_usable, "reason": self.hostname_reason},
            )

        if re.fullmatch(r"/api/users/\d+/deployments", path) and method == "POST":
            self.bodies["create"] = json.loads(request.content)
            if self.create_detail is not None:
                return json_response(self.create_status, {"detail": self.create_detail})
            record = self.create or deployment(status="provisioning", generation=1)
            return json_response(
                self.create_status,
                {"deployment": record, "checkout_url": self.checkout_url},
            )

        if re.fullmatch(r"/api/users/\d+/deployments/[^/]+", path):
            if method == "PUT":
                self.bodies["update"] = json.loads(request.content)
                if self.update_detail is not None:
                    return json_response(self.update_status, {"detail": self.update_detail})
                return json_response(
                    self.update_status,
                    self.update or deployment(status="provisioning", generation=4),
                )
            if self.deployment_missing:
                return json_response(404, {"detail": "Deployment not found"})
            record = self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]
            return json_response(200, record)

        # -- the build pipeline, scripted to succeed --------------------
        if path == "/api/artifacts":
            return json_response(
                201,
                {
                    "artifact_id": "3f6c1e9a",
                    "url": "https://blob.freepod.eu/caelus-artifacts",
                    "fields": {"key": "artifacts/3f6c1e9a.tar.gz", "policy": "eyJ"},
                    "max_bytes": 104857600,
                },
            )
        if path == f"/api/users/{self.user_id}/builds" and method == "POST":
            return json_response(201, {"id": "b-1", "status": "queued"})
        if path.endswith("/log"):
            return httpx.Response(
                206, content=b"step 1\n", headers={"X-Build-Status": "succeeded"}
            )
        if path.startswith(f"/api/users/{self.user_id}/builds/"):
            return json_response(200, {"id": "b-1", "status": "succeeded", "image": self.image})

        return json_response(404, {"detail": "Not Found"})

    # -- assertions -------------------------------------------------------

    def paths(self, method=None):
        return [p for m, p in self.calls if method is None or m == method]

    def count_before(self, method, pattern, before_method, before_pattern):
        """How many `method pattern` calls preceded the first `before_*` call."""
        limit = self.index_of(before_method, before_pattern)
        return sum(
            1
            for m, p in self.calls[:limit]
            if m == method and re.fullmatch(pattern, p)
        )

    def index_of(self, method, pattern):
        for position, (m, p) in enumerate(self.calls):
            if m == method and re.fullmatch(pattern, p):
                return position
        # Never -1: an ordering assertion comparing a missing call would read
        # as satisfied (`-1 < anything`) and pass for the wrong reason.
        raise AssertionError(f"no {method} {pattern} in {self.calls}")


def project_at(tmp_path, *, values=None, pointer=None, env="prod", files=True):
    """Write a `.freepod.json` and a token file to pack."""
    document = {
        "version": 1,
        "env": env,
        "deployment": pointer,
        "user_values": {"hostname": "myapp.erik.freepod.eu"} if values is None else values,
    }
    (tmp_path / ".freepod.json").write_text(json.dumps(document))
    if files:
        (tmp_path / "index.js").write_text("console.log('hi')\n")
    return tmp_path


def run(make_api, platform, tmp_path, **kwargs):
    api, _, _ = make_api(platform)
    store = Store()
    kwargs.setdefault("out", io.BytesIO())
    # `no_sleep` makes the poll free but leaves `time.monotonic` real, so a
    # read queue whose last entry never satisfies the wait would spin for the
    # full default. The bound turns a mis-scripted test into a fast failure.
    kwargs.setdefault("rollout_timeout", 5)
    return deploy(api, "prod", root=tmp_path, store=store.client(), poll=0, **kwargs)


# --------------------------------------------------------------------------
# Preflight order (task 10.1)
# --------------------------------------------------------------------------


def test_preflight_reads_the_credential_before_the_public_reads(make_api, tmp_path):
    """`/api/me` first: products, plans, and hostnames are answered
    anonymously however bad the credential is (design D15)."""
    platform = Platform(reads=[deployment()])
    project_at(tmp_path, pointer={"id": deployment()["id"], "name": "custom-d8dtx4"})
    api, _, _ = make_api(platform)

    preflight(api, "prod", root=tmp_path, echo=lambda _m: None)

    assert platform.paths()[0] == "/api/me"
    assert platform.paths()[1] == "/api/products"
    assert platform.paths()[2].startswith("/api/users/7/deployments/")


def test_a_deleted_deployment_is_reported_before_a_build_is_spent(make_api, tmp_path):
    """Task 10.2. The pointer lives in a committed file, so a deployment
    deleted on the platform is the common way a project goes stale."""
    platform = Platform(deployment_missing=True)
    project_at(tmp_path, pointer={"id": "40bd8dea-dead", "name": "custom-gone"})

    with pytest.raises(FreepodError) as raised:
        run(make_api, platform, tmp_path)

    assert "--recreate" in str(raised.value)
    assert "no longer exists" in str(raised.value)
    # Nothing was packed, uploaded, or built.
    assert "/api/artifacts" not in platform.paths()
    assert f"/api/users/7/builds" not in platform.paths()


def test_preflight_completes_before_anything_is_packed(make_api, tmp_path):
    platform = Platform(
        reads=[deployment(), deployment(status="ready", generation=4)],
        update=deployment(status="provisioning", generation=4),
    )
    project_at(tmp_path, pointer={"id": deployment()["id"], "name": "custom-d8dtx4"})

    run(make_api, platform, tmp_path)

    # Every preflight read precedes the first artifact slot.
    assert platform.index_of("POST", "/api/artifacts") > platform.index_of(
        "GET", r"/api/users/7/deployments/.+"
    )


def test_an_instance_without_the_custom_product_is_refused(make_api, tmp_path):
    platform = Platform(catalog=[])
    project_at(tmp_path)
    api, _, _ = make_api(platform)

    with pytest.raises(FreepodError) as raised:
        preflight(api, "prod", root=tmp_path, echo=lambda _m: None)

    assert "does not offer user-supplied application deployments" in str(raised.value)


def test_a_template_that_cannot_carry_an_image_is_refused_before_the_build(
    make_api, tmp_path
):
    """`additionalProperties: false` means an invented key is refused at
    release — after the build has been spent."""
    schema = {k: v for k, v in SCHEMA.items()}
    schema["properties"] = {"hostname": SCHEMA["properties"]["hostname"]}
    platform = Platform(catalog=[product(template=template(schema=schema))])
    project_at(tmp_path)
    api, _, _ = make_api(platform)

    with pytest.raises(FreepodError) as raised:
        preflight(api, "prod", root=tmp_path, echo=lambda _m: None)

    assert "'image'" in str(raised.value)


# --------------------------------------------------------------------------
# Newly required values (task 10.3)
# --------------------------------------------------------------------------


def test_a_newly_required_value_is_prompted_for_and_the_pointer_survives(
    make_api, tmp_path, monkeypatch
):
    """Re-initializing would discard the deployment pointer, which is the one
    thing in the file that cannot be reconstructed."""
    schema = json.loads(json.dumps(SCHEMA))
    schema["properties"]["region"] = {"type": "string"}
    schema["required"] = ["hostname", "region"]
    platform = Platform(catalog=[product(template=template(schema=schema))])
    pointer = {"id": deployment()["id"], "name": "custom-d8dtx4"}
    project_at(tmp_path, pointer=pointer)

    monkeypatch.setattr("click.prompt", lambda *a, **k: "eu-west")
    api, _, _ = make_api(platform)

    state = preflight(api, "prod", root=tmp_path, echo=lambda _m: None)

    assert state.values["region"] == "eu-west"
    saved = json.loads((tmp_path / ".freepod.json").read_text())
    assert saved["user_values"]["region"] == "eu-west"
    assert saved["deployment"] == pointer


def test_recreate_keeps_the_old_pointer_until_the_replacement_exists(
    make_api, tmp_path, monkeypatch
):
    """`--recreate` discards the pointer at release, not at preflight. The
    value prompt in between writes the file, and a deploy that failed after
    that write would otherwise leave a deployment nothing can address."""
    schema = json.loads(json.dumps(SCHEMA))
    schema["properties"]["region"] = {"type": "string"}
    schema["required"] = ["hostname", "region"]
    platform = Platform(catalog=[product(template=template(schema=schema))])
    pointer = {"id": deployment()["id"], "name": "custom-d8dtx4"}
    project_at(tmp_path, pointer=pointer)

    monkeypatch.setattr("click.prompt", lambda *a, **k: "eu-west")
    api, _, _ = make_api(platform)

    state = preflight(api, "prod", root=tmp_path, recreate=True, echo=lambda _m: None)

    # Nothing was asked about the abandoned deployment: this deploy creates.
    assert state.deployment is None
    saved = json.loads((tmp_path / ".freepod.json").read_text())
    assert saved["deployment"] == pointer


def test_a_missing_value_without_a_terminal_names_the_field(make_api, tmp_path):
    schema = json.loads(json.dumps(SCHEMA))
    schema["properties"]["region"] = {"type": "string"}
    schema["required"] = ["hostname", "region"]
    platform = Platform(catalog=[product(template=template(schema=schema))])
    project_at(tmp_path)
    api, _, _ = make_api(platform)

    with pytest.raises(FreepodError) as raised:
        preflight(api, "prod", root=tmp_path, interactive=False, echo=lambda _m: None)

    assert "'region'" in str(raised.value)


# --------------------------------------------------------------------------
# The hostname check (task 10.4, design D14)
# --------------------------------------------------------------------------


def test_an_unchanged_hostname_is_not_re_checked(make_api, tmp_path):
    """The platform's check runs without `exclude_deployment_id`, so
    re-checking a name we already hold reports `in_use` against ourselves."""
    platform = Platform(reads=[deployment(hostname="myapp.erik.freepod.eu")])
    project_at(
        tmp_path,
        values={"hostname": "myapp.erik.freepod.eu"},
        pointer={"id": deployment()["id"], "name": "custom-d8dtx4"},
    )
    api, _, _ = make_api(platform)

    preflight(api, "prod", root=tmp_path, echo=lambda _m: None)

    assert platform.hostname_checks == []


def test_a_changed_hostname_is_checked_before_packing(make_api, tmp_path):
    platform = Platform(
        reads=[
            deployment(hostname="old.freepod.eu"),
            deployment(hostname="new.freepod.eu", generation=4),
        ],
        update=deployment(status="provisioning", generation=4, hostname="new.freepod.eu"),
    )
    project_at(
        tmp_path,
        values={"hostname": "new.freepod.eu"},
        pointer={"id": deployment()["id"], "name": "custom-d8dtx4"},
    )

    run(make_api, platform, tmp_path)

    assert platform.hostname_checks == ["new.freepod.eu"]
    assert platform.index_of("GET", "/api/hostnames/.+") < platform.index_of(
        "POST", "/api/artifacts"
    )


def test_an_unusable_changed_hostname_stops_the_deploy(make_api, tmp_path):
    platform = Platform(
        reads=[deployment(hostname="old.freepod.eu")],
        hostname_usable=False,
        hostname_reason="in_use",
    )
    project_at(
        tmp_path,
        values={"hostname": "taken.freepod.eu"},
        pointer={"id": deployment()["id"], "name": "custom-d8dtx4"},
    )

    with pytest.raises(FreepodError) as raised:
        run(make_api, platform, tmp_path)

    assert "already taken by another deployment" in str(raised.value)
    assert "/api/artifacts" not in platform.paths()


def test_a_bare_label_is_completed_before_it_is_checked_or_submitted(make_api, tmp_path):
    """A hand-edited file can carry a bare label. Checking it unqualified asks
    the platform about a name that does not exist, and submitting it would
    hand the platform a hostname it never agreed to."""
    platform = Platform(
        create=deployment(status="provisioning", generation=1, hostname="myapp.erik.freepod.eu"),
        reads=[deployment(status="ready", generation=1)],
    )
    project_at(tmp_path, values={"hostname": "MyApp"})

    run(make_api, platform, tmp_path)

    assert platform.hostname_checks == ["myapp.erik.freepod.eu"]
    assert platform.bodies["create"]["user_values_json"]["hostname"] == "myapp.erik.freepod.eu"


def test_a_hostname_is_lowercased_before_it_is_submitted(make_api, tmp_path):
    """The platform lowercases what it stores, so an uppercased value in the
    file would make every subsequent comparison a false difference."""
    platform = Platform(
        reads=[
            deployment(status="ready", generation=3, hostname="myapp.erik.freepod.eu"),
            deployment(status="ready", generation=4, hostname="myapp.erik.freepod.eu"),
        ],
        update=deployment(status="provisioning", generation=4),
    )
    project_at(
        tmp_path,
        values={"hostname": "MyApp.Erik.Freepod.EU"},
        pointer={"id": deployment()["id"], "name": "custom-d8dtx4"},
    )

    run(make_api, platform, tmp_path)

    assert platform.bodies["update"]["user_values_json"]["hostname"] == "myapp.erik.freepod.eu"
    assert platform.hostname_checks == []


def test_a_first_deploy_checks_its_hostname(make_api, tmp_path):
    """No deployment means the name is new, whatever `init` concluded earlier."""
    platform = Platform()
    project_at(tmp_path)
    api, _, _ = make_api(platform)

    preflight(api, "prod", root=tmp_path, echo=lambda _m: None)

    assert platform.hostname_checks == ["myapp.erik.freepod.eu"]


# --------------------------------------------------------------------------
# Cross-environment deploys
# --------------------------------------------------------------------------


def test_a_deploy_to_another_environment_needs_recreate(make_api, tmp_path):
    """The recorded deployment is minted on the file's environment and cannot
    be reached from the target one, so pointing the project elsewhere needs
    the same confirmation as discarding it."""
    platform = Platform()
    project_at(
        tmp_path, env="dev", pointer={"id": "40bd8dea-54f3-430d", "name": "custom-dev123"}
    )
    api, _, _ = make_api(platform)

    with pytest.raises(UsageError) as raised:
        deploy(api, "prod", root=tmp_path, echo=lambda _m: None)

    message = str(raised.value)
    assert "'dev'" in message and "'prod'" in message
    assert "--recreate" in message
    # Nothing was read from the platform: the file already answers.
    assert platform.calls == []


def test_recreate_points_the_project_at_the_target_environment(make_api, tmp_path):
    """The old deployment keeps running; the file follows the new pointer,
    environment and all, in the same write."""
    platform = Platform(
        create=deployment(status="provisioning", generation=1),
        reads=[deployment(status="ready", generation=1)],
    )
    project_at(
        tmp_path, env="dev", pointer={"id": "40bd8dea-54f3-430d", "name": "custom-dev123"}
    )

    run(make_api, platform, tmp_path, recreate=True)

    recorded = load(tmp_path)
    assert recorded.env == "prod"
    assert recorded.deployment_id == deployment()["id"]


def test_a_deploy_to_another_environment_without_a_pointer_starts_fresh(
    make_api, tmp_path
):
    """No recorded deployment means nothing is orphaned: the file simply
    follows the pointer it gains."""
    platform = Platform(
        create=deployment(status="provisioning", generation=1),
        reads=[deployment(status="ready", generation=1)],
    )
    project_at(tmp_path, env="dev")

    run(make_api, platform, tmp_path)

    recorded = load(tmp_path)
    assert recorded.env == "prod"
    assert recorded.deployment_id == deployment()["id"]


# --------------------------------------------------------------------------
# Plans (task 10.5)
# --------------------------------------------------------------------------


def test_the_first_free_plan_is_selected(make_api):
    platform = Platform(
        plans=[
            plan(id=1, name="Starter", price_cents=250, template_id=21),
            plan(id=2, name="Free", price_cents=0, template_id=22),
            plan(id=3, name="Also free", price_cents=0, template_id=23),
        ]
    )
    api, _, _ = make_api(platform)

    assert select_free_plan(api, product())["template"]["id"] == 22


def test_an_instance_with_no_free_plan_is_refused(make_api):
    platform = Platform(plans=[plan(name="Pro", price_cents=900)])
    api, _, _ = make_api(platform)

    with pytest.raises(FreepodError) as raised:
        select_free_plan(api, product())

    assert "no free plan" in str(raised.value)
    assert "Pro" in str(raised.value)


def test_a_product_with_no_plans_at_all_is_reported_as_a_platform_problem(make_api):
    platform = Platform(plans=[])
    api, _, _ = make_api(platform)

    with pytest.raises(FreepodError) as raised:
        select_free_plan(api, product())

    assert "publishes no plans" in str(raised.value)


def test_nothing_is_created_when_no_free_plan_exists(make_api, tmp_path):
    platform = Platform(plans=[plan(name="Pro", price_cents=900)])
    project_at(tmp_path)

    with pytest.raises(FreepodError):
        run(make_api, platform, tmp_path)

    assert "POST" not in [m for m, p in platform.calls if p == "/api/users/7/deployments"]


def test_no_free_plan_is_refused_before_a_build_is_spent(make_api, tmp_path):
    """An instance with no free plan refuses every time, so discovering it
    after the build is a four-minute wait for a foregone conclusion. Read at
    preflight, and only when a deployment has to be created."""
    platform = Platform(plans=[])
    project_at(tmp_path)

    with pytest.raises(FreepodError) as raised:
        run(make_api, platform, tmp_path)

    assert "publishes no plans" in str(raised.value)
    assert "/api/artifacts" not in platform.paths()
    assert f"/api/users/7/builds" not in platform.paths()


def test_plans_are_not_read_when_a_deployment_already_exists(make_api, tmp_path):
    """An update reuses the deployment's subscription; the plan is settled."""
    platform = Platform(
        reads=[
            deployment(status="ready", generation=3),
            deployment(status="ready", generation=4),
        ],
        update=deployment(status="provisioning", generation=4),
    )
    project_at(tmp_path, pointer={"id": deployment()["id"], "name": "custom-d8dtx4"})

    run(make_api, platform, tmp_path)

    assert not any(p.endswith("/plans") for p in platform.paths())


# --------------------------------------------------------------------------
# First deploy (tasks 10.5, 10.6)
# --------------------------------------------------------------------------


def test_a_first_deploy_performs_a_single_rollout(make_api, tmp_path):
    """Creating first would roll out the placeholder and then the real image."""
    platform = Platform(
        create=deployment(status="provisioning", generation=1),
        reads=[deployment(status="ready", generation=1)],
    )
    project_at(tmp_path)

    run(make_api, platform, tmp_path)

    creates = [c for c in platform.calls if c == ("POST", "/api/users/7/deployments")]
    updates = [c for c in platform.calls if c[0] == "PUT"]
    assert len(creates) == 1
    assert updates == []


def test_the_build_completes_before_the_deployment_is_created(make_api, tmp_path):
    platform = Platform(
        create=deployment(status="provisioning", generation=1),
        reads=[deployment(status="ready", generation=1)],
    )
    project_at(tmp_path)

    run(make_api, platform, tmp_path)

    assert platform.index_of("GET", "/api/users/7/builds/b-1") < platform.index_of(
        "POST", "/api/users/7/deployments"
    )


def test_the_creation_carries_the_built_image(make_api, tmp_path):
    platform = Platform(
        create=deployment(status="provisioning", generation=1),
        reads=[deployment(status="ready", generation=1)],
    )
    project_at(tmp_path)

    run(make_api, platform, tmp_path)

    body = platform.bodies["create"]
    assert body["desired_template_id"] == 49
    assert body["plan_template_id"] == 11
    assert body["user_values_json"] == {"hostname": "myapp.erik.freepod.eu", "image": IMAGE}


def test_the_pointer_is_written_before_the_rollout_is_awaited(make_api, tmp_path):
    """Task 10.6. A deployment that exists but is not recorded is one the
    project can never address again."""
    created = deployment(id="new-id-1", name="custom-fresh", status="provisioning", generation=1)
    seen = {}

    class Watcher(Platform):
        def __call__(self, request):
            path = request.url.path
            if request.method == "GET" and re.fullmatch(r"/api/users/\d+/deployments/.+", path):
                seen.setdefault(
                    "file", json.loads((tmp_path / ".freepod.json").read_text())
                )
            return super().__call__(request)

    platform = Watcher(create=created, reads=[deployment(id="new-id-1", generation=1)])
    project_at(tmp_path)

    run(make_api, platform, tmp_path)

    assert seen["file"]["deployment"] == {"id": "new-id-1", "name": "custom-fresh"}


def test_a_checkout_url_is_refused(make_api, tmp_path):
    platform = Platform(
        create=deployment(status="pending", generation=1),
        checkout_url="https://pay.example/abc",
    )
    project_at(tmp_path)

    with pytest.raises(FreepodError) as raised:
        run(make_api, platform, tmp_path)

    assert "only supports free plans" in str(raised.value)


# --------------------------------------------------------------------------
# Subsequent deploys (tasks 10.7, 10.8, design D8)
# --------------------------------------------------------------------------


def test_an_in_progress_rollout_is_waited_out_with_its_status_shown(make_api):
    platform = Platform(
        reads=[
            deployment(status="provisioning"),
            deployment(status="provisioning"),
            deployment(status="ready"),
        ]
    )
    api, _, _ = make_api(platform)
    said = []

    settled = wait_until_settled(
        api, 7, deployment(status="provisioning"), poll=0, echo=said.append
    )

    assert settled["status"] == "ready"
    assert any("provisioning" in line for line in said)


def test_the_release_waits_for_a_deployment_that_is_not_ready_to_update(make_api, tmp_path):
    """The platform's update is guarded by an atomic
    `WHERE status IN ('ready','error')`, so releasing into a rollout already in
    flight is refused outright rather than queued. Testing `wait_until_settled`
    on its own does not establish that `release` calls it — a deploy that
    skipped the wait passed every other test here."""
    platform = Platform(
        reads=[
            deployment(status="provisioning", generation=3),
            deployment(status="provisioning", generation=3),
            deployment(status="ready", generation=3),
            deployment(status="ready", generation=4),
        ],
        update=deployment(status="provisioning", generation=4),
    )
    project_at(tmp_path, pointer={"id": deployment()["id"], "name": "custom-d8dtx4"})
    said = []

    run(make_api, platform, tmp_path, echo=said.append)

    # One read in preflight, then polls until it settles — all before the PUT.
    reads = platform.count_before(
        "GET", r"/api/users/7/deployments/.+", "PUT", r"/api/users/7/deployments/.+"
    )
    assert reads >= 3
    assert any("settle" in line and "provisioning" in line for line in said)


def test_a_settled_deployment_is_not_re_read(make_api):
    platform = Platform()
    api, _, _ = make_api(platform)

    wait_until_settled(api, 7, deployment(status="ready"), poll=0, echo=lambda _m: None)

    assert platform.calls == []


def test_partial_user_values_are_never_sent(make_api, tmp_path):
    """The platform replaces stored values wholesale; a partial object does
    not merge, so `{"image": …}` alone fails on the missing hostname."""
    platform = Platform(
        reads=[deployment(status="ready", generation=3), deployment(status="ready", generation=4)],
        update=deployment(status="provisioning", generation=4),
    )
    project_at(
        tmp_path,
        values={"hostname": "myapp.erik.freepod.eu"},
        pointer={"id": deployment()["id"], "name": "custom-d8dtx4"},
    )

    run(make_api, platform, tmp_path)

    assert platform.bodies["update"]["user_values_json"] == {
        "hostname": "myapp.erik.freepod.eu",
        "image": IMAGE,
    }


def test_an_edited_value_is_applied_by_the_next_deploy(make_api, tmp_path):
    platform = Platform(
        reads=[
            deployment(status="ready", generation=3, hostname="old.freepod.eu"),
            deployment(status="ready", generation=4, hostname="new.freepod.eu"),
        ],
        update=deployment(status="provisioning", generation=4, hostname="new.freepod.eu"),
    )
    project_at(
        tmp_path,
        values={"hostname": "new.freepod.eu"},
        pointer={"id": deployment()["id"], "name": "custom-d8dtx4"},
    )

    live = run(make_api, platform, tmp_path)

    assert platform.bodies["update"]["user_values_json"]["hostname"] == "new.freepod.eu"
    assert live == "https://new.freepod.eu"


def test_the_update_targets_the_products_canonical_template(make_api, tmp_path):
    """Not the template the deployment was created against — pinning would
    freeze it on whatever version it started on (design D7)."""
    platform = Platform(
        catalog=[product(template=template(id=51, chart_version="0.2.0"))],
        reads=[
            deployment(status="ready", generation=3, template_id=49),
            deployment(status="ready", generation=4, template_id=51),
        ],
        update=deployment(status="provisioning", generation=4, template_id=51),
    )
    project_at(tmp_path, pointer={"id": deployment()["id"], "name": "custom-d8dtx4"})

    run(make_api, platform, tmp_path)

    assert platform.bodies["update"]["desired_template_id"] == 51


def test_a_template_move_is_announced(make_api, tmp_path):
    platform = Platform(
        catalog=[product(template=template(id=51, chart_version="0.2.0"))],
        reads=[
            deployment(status="ready", generation=3, template_id=49, chart_version="0.1.0"),
            deployment(status="ready", generation=4, template_id=51),
        ],
        update=deployment(status="provisioning", generation=4, template_id=51),
    )
    project_at(tmp_path, pointer={"id": deployment()["id"], "name": "custom-d8dtx4"})
    said = []

    run(make_api, platform, tmp_path, echo=said.append)

    assert any("Product template 49 → 51" in line for line in said)
    assert any("chart custom 0.1.0 → 0.2.0" in line for line in said)


def test_an_unchanged_template_is_not_announced(make_api, tmp_path):
    platform = Platform(
        reads=[
            deployment(status="ready", generation=3, template_id=49),
            deployment(status="ready", generation=4, template_id=49),
        ],
        update=deployment(status="provisioning", generation=4),
    )
    project_at(tmp_path, pointer={"id": deployment()["id"], "name": "custom-d8dtx4"})
    said = []

    run(make_api, platform, tmp_path, echo=said.append)

    assert not any("Product template" in line for line in said)


# --------------------------------------------------------------------------
# The release 409 (tasks 10.9, 10.11)
# --------------------------------------------------------------------------


CONFLICTS = [
    ("Deployment is not in ready state", "not in a state that accepts an update", True),
    ("A deployment job is already queued or running", "already queued or running", True),
    (
        "Can only upgrade to newer versions, not downgrade",
        "templates only move forward",
        False,
    ),
    (
        "Upgrade template must belong to the same product",
        "belongs to a different product",
        False,
    ),
    ("in_use", "already taken by another deployment", False),
    ("user_values_json is invalid: 'region' is a required property", "no longer satisfy", False),
    (
        "product template has an invalid values_schema_json: 'x' is not valid",
        "platform defect",
        False,
    ),
]


@pytest.mark.parametrize("detail,expected,retryable", CONFLICTS)
def test_each_release_conflict_maps_to_its_own_message(detail, expected, retryable):
    """The status cannot carry the distinction: `HostnameException`,
    `IntegrityException`, and `DeploymentInProgressException` all map to 409."""
    message, worth_retrying = describe_conflict(detail)

    assert expected in message
    assert worth_retrying is retryable


def test_the_seven_conflicts_produce_seven_distinct_messages():
    messages = {describe_conflict(detail)[0] for detail, _, _ in CONFLICTS}
    assert len(messages) == len(CONFLICTS)


def test_the_values_conflict_names_the_template_move():
    """Task 10.9. Preflight catches only an *added* required key; a tightened
    pattern reaches here, after the build is spent."""
    message, retryable = describe_conflict(
        "user_values_json is invalid: 'x' does not match '^[a-z]+$'", move="49 → 51"
    )

    assert "49 → 51" in message
    assert "does not match" in message
    assert retryable is False
    assert "Retrying cannot help" in message


def test_a_broken_template_schema_is_not_blamed_on_the_user():
    message, retryable = describe_conflict(
        "product template has an invalid values_schema_json: 'foo' is not of type 'object'"
    )

    assert "platform defect" in message
    assert "not at fault" in message
    assert retryable is False


def test_an_unrecognized_conflict_is_quoted_verbatim():
    """Prefix matching on a human-readable string is fragile; a message
    invented for an unknown detail would be wrong exactly when it mattered."""
    message, retryable = describe_conflict("Something entirely new happened")

    assert "Something entirely new happened" in message
    assert retryable is False


def test_an_empty_conflict_is_reported_without_invention():
    message, _ = describe_conflict(None)
    assert "no explanation" in message


def test_only_the_transient_conflicts_suggest_a_retry():
    retryable = {detail for detail, _, worth in CONFLICTS if worth}
    assert retryable == {
        "Deployment is not in ready state",
        "A deployment job is already queued or running",
    }


def test_a_release_conflict_surfaces_through_the_update(make_api, tmp_path):
    platform = Platform(
        catalog=[product(template=template(id=51, chart_version="0.2.0"))],
        reads=[deployment(status="ready", generation=3, template_id=49)],
        update_status=409,
        update_detail="user_values_json is invalid: 'region' is a required property",
    )
    project_at(tmp_path, pointer={"id": deployment()["id"], "name": "custom-d8dtx4"})

    with pytest.raises(FreepodError) as raised:
        run(make_api, platform, tmp_path)

    assert "49 → 51" in str(raised.value)
    assert "is a required property" in str(raised.value)


def test_a_creation_conflict_is_read_the_same_way(make_api, tmp_path):
    platform = Platform(
        create_status=409, create_detail="Template is not the current canonical for this product"
    )
    project_at(tmp_path)

    with pytest.raises(FreepodError) as raised:
        run(make_api, platform, tmp_path)

    assert "moved while this deploy was running" in str(raised.value)


# --------------------------------------------------------------------------
# The rollout (task 10.10)
# --------------------------------------------------------------------------


def test_a_stale_ready_is_not_mistaken_for_success(make_api):
    """`generation` is incremented atomically by the update; a `ready` at an
    older generation is the previous rollout's, serving the old image."""
    platform = Platform(
        reads=[
            deployment(status="ready", generation=3),
            deployment(status="provisioning", generation=4),
            deployment(status="ready", generation=4),
        ]
    )
    api, _, _ = make_api(platform)

    final = follow_rollout(api, 7, deployment()["id"], 4, poll=0, echo=lambda _m: None)

    assert final["generation"] == 4
    assert final["status"] == "ready"
    assert len(platform.calls) == 3


def test_a_successful_deploy_reports_the_live_address(make_api, tmp_path):
    platform = Platform(
        create=deployment(status="provisioning", generation=1),
        reads=[deployment(status="ready", generation=1, hostname="myapp.erik.freepod.eu")],
    )
    project_at(tmp_path)

    assert run(make_api, platform, tmp_path) == "https://myapp.erik.freepod.eu"


def test_a_failed_rollout_reports_the_platform_error_with_exit_5(make_api, tmp_path):
    platform = Platform(
        create=deployment(status="provisioning", generation=1),
        reads=[
            deployment(status="error", generation=1, last_error="helm upgrade timed out")
        ],
    )
    project_at(tmp_path)

    with pytest.raises(RolloutFailed) as raised:
        run(make_api, platform, tmp_path)

    assert "helm upgrade timed out" in str(raised.value)
    assert raised.value.exit_code == 5


def test_a_rollout_timeout_says_the_platform_continues(make_api):
    platform = Platform(reads=[deployment(status="provisioning", generation=4)])
    api, _, _ = make_api(platform)

    with pytest.raises(FreepodError) as raised:
        follow_rollout(
            api, 7, deployment()["id"], 4, timeout=0, poll=0, echo=lambda _m: None
        )

    assert "was not canceled" in str(raised.value)
    assert "still rolling out" in str(raised.value)


def test_a_deployment_deleted_mid_rollout_is_reported(make_api):
    platform = Platform(reads=[deployment(status="deleting", generation=4)])
    api, _, _ = make_api(platform)

    with pytest.raises(FreepodError) as raised:
        follow_rollout(api, 7, deployment()["id"], 4, poll=0, echo=lambda _m: None)

    assert "deleted from elsewhere" in str(raised.value)


def test_a_ready_deployment_without_a_hostname_is_a_platform_condition(make_api, tmp_path):
    platform = Platform(
        create=deployment(status="provisioning", generation=1),
        reads=[deployment(status="ready", generation=1, hostname=None)],
    )
    project_at(tmp_path)
    api, _, _ = make_api(platform)
    state = preflight(api, "prod", root=tmp_path, echo=lambda _m: None)

    with pytest.raises(FreepodError) as raised:
        release(api, state, IMAGE, poll=0, echo=lambda _m: None)

    assert "carries no hostname" in str(raised.value)


# --------------------------------------------------------------------------
# --recreate (task 10.12)
# --------------------------------------------------------------------------


def test_recreate_discards_the_pointer_and_creates_a_new_deployment(make_api, tmp_path):
    platform = Platform(
        create=deployment(id="new-id-2", name="custom-second", status="provisioning", generation=1),
        reads=[deployment(id="new-id-2", status="ready", generation=1)],
    )
    project_at(tmp_path, pointer={"id": "40bd8dea-old", "name": "custom-old"})

    run(make_api, platform, tmp_path, recreate=True)

    assert "create" in platform.bodies
    assert not any(method == "PUT" for method, _ in platform.calls)
    saved = json.loads((tmp_path / ".freepod.json").read_text())
    assert saved["deployment"] == {"id": "new-id-2", "name": "custom-second"}


def test_recreate_never_reads_the_discarded_deployment(make_api, tmp_path):
    """The pointer is gone before preflight looks it up, so a deployment
    already deleted cannot make `--recreate` — the fix for exactly that — fail."""
    platform = Platform(deployment_missing=True)
    project_at(tmp_path, pointer={"id": "40bd8dea-old", "name": "custom-old"})
    api, _, _ = make_api(platform)

    state = preflight(api, "prod", root=tmp_path, recreate=True, echo=lambda _m: None)

    assert state.deployment is None
    assert not any(p.startswith("/api/users/7/deployments/") for p in platform.paths())


def test_recreate_does_not_persist_the_discard_until_the_new_deployment_exists(
    make_api, tmp_path
):
    """A create that fails must not leave the file pointing at nothing."""
    platform = Platform(create_status=409, create_detail="Deployment already exists")
    project_at(tmp_path, pointer={"id": "40bd8dea-old", "name": "custom-old"})

    with pytest.raises(FreepodError):
        run(make_api, platform, tmp_path, recreate=True)

    saved = json.loads((tmp_path / ".freepod.json").read_text())
    assert saved["deployment"] == {"id": "40bd8dea-old", "name": "custom-old"}


# --------------------------------------------------------------------------
# Stream discipline
# --------------------------------------------------------------------------


def test_the_build_log_and_the_address_are_kept_apart(make_api, tmp_path):
    platform = Platform(
        create=deployment(status="provisioning", generation=1),
        reads=[deployment(status="ready", generation=1)],
    )
    project_at(tmp_path)
    log = io.BytesIO()
    said = []

    live = run(make_api, platform, tmp_path, out=log, echo=said.append)

    assert log.getvalue() == b"step 1\n"
    assert live not in "\n".join(said).replace("Deployed", "")


# --------------------------------------------------------------------------
# Build provenance (task 8.0)
# --------------------------------------------------------------------------


def test_a_created_deployment_names_the_build_that_produced_its_image(make_api, tmp_path):
    """Without this every release records a null build and the chain from
    source archive through build to running pod is broken at its last link.

    The platform stores it on the *release*, never on the deployment, so it
    rides as a plain request field beside `plan_template_id`.
    """
    platform = Platform()
    project_at(tmp_path, values={"hostname": "myapp.erik.freepod.eu"})

    run(make_api, platform, tmp_path)

    assert platform.bodies["create"]["build_id"] == "b-1"
    # And the image it names is the one that build produced.
    assert platform.bodies["create"]["user_values_json"]["image"] == IMAGE


def test_an_updated_deployment_names_the_build_too(make_api, tmp_path):
    platform = Platform(
        reads=[deployment(status="ready", generation=3), deployment(status="ready", generation=4)],
        update=deployment(status="provisioning", generation=4),
    )
    project_at(
        tmp_path,
        values={"hostname": "myapp.erik.freepod.eu"},
        pointer={"id": deployment()["id"], "name": "custom-d8dtx4"},
    )

    run(make_api, platform, tmp_path)

    assert platform.bodies["update"]["build_id"] == "b-1"


def test_releasing_without_a_build_sends_no_build_reference(make_api, tmp_path):
    """`release` is reachable with an image the caller did not just build, and
    a null `build_id` is a legitimate record rather than an error -- so the key
    is omitted entirely rather than sent as null."""
    from freepod.deploy import preflight

    platform = Platform()
    project_at(tmp_path, values={"hostname": "myapp.erik.freepod.eu"})
    api, _, _ = make_api(platform)
    state = preflight(api, "prod", root=tmp_path, echo=lambda _m: None)

    release(api, state, IMAGE, poll=0, echo=lambda _m: None)

    assert "build_id" not in platform.bodies["create"]
