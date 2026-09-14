"""Build worker tests, against a faked Kubernetes client.

The fake stands in for the cluster at the `BuildJobClient` seam, so every
decision the worker makes — claiming, log mirroring, outcome adoption,
recovery, the deadline backstop — is exercised without a cluster. The database
is real, because the claim is a database-level atomicity property and faking it
would test nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlmodel import select

from app import build_worker
from app.build_worker import merge_log, run_pass, truncate_log
from app.config import CaelusSettings
from app.models import BuildORM
from app.services import build_jobs
from app.services.build_constants import (
    BUILD_STATUS_FAILED,
    BUILD_STATUS_QUEUED,
    BUILD_STATUS_RUNNING,
    BUILD_STATUS_SUCCEEDED,
)
import jwt

from app.services import registry_tokens
from app.services.build_jobs import (
    BUILD_ID_LABEL,
    CAPABILITY_MARGIN_SECONDS,
    MIRRORED_REPOSITORIES,
    build_job_manifest,
    job_name,
)
from app.services.registry_tokens import RegistryKeyException
from tests.conftest import db_session, make_accepted_user  # noqa: F401

IMAGE = "7@sha256:" + "d" * 64


class FakeCluster:
    """A pretend Kubernetes, honest about the parts the worker depends on."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.logs: dict[str, bytes] = {}
        self.termination: dict[str, str] = {}
        self.created: list[dict] = []
        self.deleted: list[str] = []
        self.create_error: Exception | None = None

    # -- BuildJobClient ---------------------------------------------------
    def create_job(self, manifest: dict) -> None:
        if self.create_error is not None:
            raise self.create_error
        name = manifest["metadata"]["name"]
        self.jobs[name] = {"metadata": {"name": name}, "status": {}}
        self.created.append(manifest)

    def get_job(self, name: str) -> dict | None:
        return self.jobs.get(name)

    def delete_job(self, name: str) -> None:
        self.deleted.append(name)
        self.jobs.pop(name, None)

    def read_log(self, build_id: str) -> bytes | None:
        return self.logs.get(build_id)

    def read_termination_message(self, build_id: str) -> str | None:
        return self.termination.get(build_id)

    # -- test helpers -----------------------------------------------------
    def complete(self, build_id: UUID, *, image: str | None = IMAGE) -> None:
        self.jobs[job_name(build_id)]["status"] = {"succeeded": 1}
        if image is not None:
            self.termination[str(build_id)] = json.dumps({"image": image})

    def fail(self, build_id: UUID, *, error: str = "boom") -> None:
        self.jobs[job_name(build_id)]["status"] = {"failed": 1}
        self.termination[str(build_id)] = json.dumps({"error": error})


@pytest.fixture
def cluster():
    return FakeCluster()


@pytest.fixture(scope="module")
def signing_key():
    return registry_tokens.generate_private_key()


@pytest.fixture
def settings(signing_key):
    return CaelusSettings(
        _env_file=None,
        s3_endpoint_url="https://blob.example.invalid",
        s3_bucket="test",
        s3_access_key_id="k",
        s3_secret_access_key="s",
        build_max_in_flight=1,
        # Terraform supplies these in a real environment; the defaults are
        # empty and `build_job_manifest` refuses to build a Job without them.
        builder_image="registry.invalid/caelus/builder:0.0.0-test",
        registry_host="cr.test.example",
        registry_token_issuer="caelus-test",
        registry_signing_private_key=registry_tokens.private_key_pem(signing_key),
    )


@pytest.fixture(autouse=True)
def _no_presigning(monkeypatch):
    """The artifact URL is minted by the artifacts service; stub the signing."""
    monkeypatch.setattr(
        build_worker.artifact_service,
        "artifact_download_url",
        lambda user_id, artifact_id, settings=None: f"https://store.invalid/{user_id}/{artifact_id}",
    )


def _user(session, email="build-worker@example.com"):
    return make_accepted_user(session, email)


def _queued(session, user_id, artifact_id=None, **kwargs) -> BuildORM:
    kwargs.setdefault("status", BUILD_STATUS_QUEUED)
    build = BuildORM(
        user_id=user_id,
        artifact_id=artifact_id or uuid4().hex,
        **kwargs,
    )
    session.add(build)
    session.commit()
    session.refresh(build)
    return build


# ---------------------------------------------------------------------------
# Claiming
# ---------------------------------------------------------------------------


def test_a_queued_build_is_claimed_and_gets_a_job(db_session, cluster, settings):
    user = _user(db_session)
    build = _queued(db_session, user.id)

    result = run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(build)
    assert result.claimed == [build.id]
    assert build.status == BUILD_STATUS_RUNNING
    assert build.started_at is not None
    assert build.job_id == job_name(build.id)
    assert cluster.created[0]["metadata"]["name"] == job_name(build.id)


def test_the_oldest_queued_build_is_claimed_first(db_session, cluster, settings):
    user = _user(db_session)
    base = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
    older = _queued(db_session, user.id, created_at=base)
    _queued(db_session, user.id, created_at=base + timedelta(minutes=5))

    result = run_pass(db_session, client=cluster, settings=settings)

    assert result.claimed == [older.id]


def test_no_claim_while_at_the_in_flight_limit(db_session, cluster, settings):
    user = _user(db_session)
    first = _queued(db_session, user.id)
    assert run_pass(db_session, client=cluster, settings=settings).claimed == [first.id]
    second = _queued(db_session, user.id)

    result = run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(second)
    assert result.claimed == []
    assert second.status == BUILD_STATUS_QUEUED


def test_a_queued_build_is_claimed_once_capacity_frees(db_session, cluster, settings):
    user = _user(db_session)
    first = _queued(db_session, user.id)
    second = _queued(db_session, user.id)
    run_pass(db_session, client=cluster, settings=settings)
    db_session.refresh(first)
    cluster.complete(first.id)

    result = run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(first)
    db_session.refresh(second)
    assert first.status == BUILD_STATUS_SUCCEEDED
    # Advancing runs before claiming, so the freed slot is reused in the *same*
    # pass rather than a whole interval later.
    assert result.claimed == [second.id]
    assert second.status == BUILD_STATUS_RUNNING


def test_the_in_flight_limit_is_honored_above_one(db_session, cluster, settings):
    user = _user(db_session)
    for _ in range(5):
        _queued(db_session, user.id)
    settings.build_max_in_flight = 3

    result = run_pass(db_session, client=cluster, settings=settings)

    assert len(result.claimed) == 3
    running = db_session.exec(select(BuildORM).where(BuildORM.status == BUILD_STATUS_RUNNING)).all()
    assert len(running) == 3


def test_a_claim_is_atomic_under_concurrency(db_session, cluster, settings):
    """Two claims must never hand out the same build.

    Driven directly at the claim rather than through a thread pool: what
    matters here is that the statement selects and updates in one shot, which
    repeated calls expose. Genuine concurrency against the claim is covered by
    the parallel-worker test in test_jobs_service.py.
    """
    user = _user(db_session)
    builds = {_queued(db_session, user.id).id for _ in range(4)}
    now = datetime.now(UTC)

    claimed = []
    while True:
        build = build_worker._claim_next_build(db_session, now=now)
        if build is None:
            break
        claimed.append(build.id)

    assert len(claimed) == len(set(claimed)) == 4
    assert set(claimed) == builds


def test_the_job_is_created_after_the_status_transition(db_session, cluster, settings):
    """If the Job were created first, a crash in between would leave a Job with
    no build row pointing at it."""
    user = _user(db_session)
    build = _queued(db_session, user.id)
    seen: list[str] = []

    original = cluster.create_job

    def _spy(manifest):
        db_session.refresh(build)
        seen.append(build.status)
        return original(manifest)

    cluster.create_job = _spy
    run_pass(db_session, client=cluster, settings=settings)

    assert seen == [BUILD_STATUS_RUNNING]


def test_a_failure_to_create_the_job_leaves_a_recoverable_null(db_session, cluster, settings):
    user = _user(db_session)
    build = _queued(db_session, user.id)
    cluster.create_error = RuntimeError("apiserver unavailable")

    run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(build)
    assert build.status == BUILD_STATUS_RUNNING
    assert build.job_id is None


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


def test_success_adopts_the_reported_image(db_session, cluster, settings):
    user = _user(db_session)
    build = _queued(db_session, user.id)
    run_pass(db_session, client=cluster, settings=settings)
    db_session.refresh(build)
    cluster.complete(build.id, image=IMAGE)

    result = run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(build)
    assert result.succeeded == [build.id]
    assert build.status == BUILD_STATUS_SUCCEEDED
    assert build.image == IMAGE
    assert build.finished_at is not None


def test_an_unsuccessful_job_fails_the_build(db_session, cluster, settings):
    user = _user(db_session)
    build = _queued(db_session, user.id)
    run_pass(db_session, client=cluster, settings=settings)
    db_session.refresh(build)
    cluster.fail(build.id)

    result = run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(build)
    assert result.failed == [build.id]
    assert build.status == BUILD_STATUS_FAILED
    assert build.image is None


def test_success_reporting_no_image_fails_the_build(db_session, cluster, settings):
    """There is nothing a deployment could run, so it is not a usable build."""
    user = _user(db_session)
    build = _queued(db_session, user.id)
    run_pass(db_session, client=cluster, settings=settings)
    db_session.refresh(build)
    cluster.complete(build.id, image=None)

    run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(build)
    assert build.status == BUILD_STATUS_FAILED
    assert build.image is None


def test_a_success_reporting_an_error_payload_fails_the_build(db_session, cluster, settings):
    """The builder writes {"error": ...} on failure; it must not read as success."""
    user = _user(db_session)
    build = _queued(db_session, user.id)
    run_pass(db_session, client=cluster, settings=settings)
    db_session.refresh(build)
    cluster.jobs[job_name(build.id)]["status"] = {"succeeded": 1}
    cluster.termination[str(build.id)] = json.dumps({"error": "stack detection failed"})

    run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(build)
    assert build.status == BUILD_STATUS_FAILED


def test_a_missing_job_fails_the_build(db_session, cluster, settings):
    user = _user(db_session)
    build = _queued(db_session, user.id)
    run_pass(db_session, client=cluster, settings=settings)
    db_session.refresh(build)
    cluster.jobs.clear()

    run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(build)
    assert build.status == BUILD_STATUS_FAILED


def test_a_null_job_id_fails_the_build_and_deletes_any_orphan(db_session, cluster, settings):
    """The worker died between claiming and recording the Job. The Job may
    exist under its deterministic name, so it is deleted rather than left to
    consume the node."""
    user = _user(db_session)
    build = _queued(db_session, user.id, status=BUILD_STATUS_RUNNING, started_at=datetime.now(UTC))

    run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(build)
    assert build.status == BUILD_STATUS_FAILED
    assert job_name(build.id) in cluster.deleted


def test_a_finished_job_is_adopted_after_a_worker_restart(db_session, cluster, settings):
    """The whole point of visiting every running build on every pass: a build
    that succeeded while no worker was alive must not be failed."""
    user = _user(db_session)
    build = _queued(db_session, user.id)
    run_pass(db_session, client=cluster, settings=settings)
    db_session.refresh(build)
    cluster.complete(build.id)

    # A "new" worker: nothing carried over but the database and the cluster.
    fresh_result = run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(build)
    assert build.status == BUILD_STATUS_SUCCEEDED
    assert build.image == IMAGE
    assert fresh_result.failed == []


def test_a_still_running_job_is_left_alone(db_session, cluster, settings):
    user = _user(db_session)
    build = _queued(db_session, user.id)
    run_pass(db_session, client=cluster, settings=settings)

    result = run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(build)
    assert build.status == BUILD_STATUS_RUNNING
    assert result.advanced == 1
    assert cluster.deleted == []


# ---------------------------------------------------------------------------
# Deadline backstop
# ---------------------------------------------------------------------------


def test_an_over_deadline_job_is_deleted_and_failed(db_session, cluster, settings):
    user = _user(db_session)
    build = _queued(db_session, user.id)
    run_pass(db_session, client=cluster, settings=settings)
    db_session.refresh(build)
    later = datetime.now(UTC) + timedelta(
        seconds=settings.build_deadline_seconds + settings.build_deadline_grace_seconds + 60
    )

    run_pass(db_session, client=cluster, settings=settings, now=later)

    db_session.refresh(build)
    assert build.status == BUILD_STATUS_FAILED
    assert build.job_id in cluster.deleted


def test_a_build_inside_the_grace_period_is_not_touched(db_session, cluster, settings):
    """Kubernetes owns the deadline; the worker only acts if it failed to."""
    user = _user(db_session)
    build = _queued(db_session, user.id)
    run_pass(db_session, client=cluster, settings=settings)
    db_session.refresh(build)
    just_past = datetime.now(UTC) + timedelta(seconds=settings.build_deadline_seconds + 5)

    run_pass(db_session, client=cluster, settings=settings, now=just_past)

    db_session.refresh(build)
    assert build.status == BUILD_STATUS_RUNNING
    assert cluster.deleted == []


# ---------------------------------------------------------------------------
# Log mirroring
# ---------------------------------------------------------------------------


def test_the_log_is_mirrored_across_passes(db_session, cluster, settings):
    user = _user(db_session)
    build = _queued(db_session, user.id)
    run_pass(db_session, client=cluster, settings=settings)
    db_session.refresh(build)

    for chunk in (b"step 1\n", b"step 1\nstep 2\n", b"step 1\nstep 2\nstep 3\n"):
        cluster.logs[str(build.id)] = chunk
        run_pass(db_session, client=cluster, settings=settings)
        db_session.refresh(build)
        assert bytes(build.log) == chunk


def test_a_shorter_read_never_shortens_the_stored_log(db_session, cluster, settings):
    """A container runtime may rotate output away; clients have already read
    the longer version at offsets that must stay meaningful."""
    user = _user(db_session)
    build = _queued(db_session, user.id)
    run_pass(db_session, client=cluster, settings=settings)
    db_session.refresh(build)
    cluster.logs[str(build.id)] = b"a full and complete log\n"
    run_pass(db_session, client=cluster, settings=settings)

    cluster.logs[str(build.id)] = b"rotated\n"
    run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(build)
    assert bytes(build.log) == b"a full and complete log\n"


def test_an_empty_read_does_not_clear_the_log(db_session, cluster, settings):
    user = _user(db_session)
    build = _queued(db_session, user.id)
    run_pass(db_session, client=cluster, settings=settings)
    db_session.refresh(build)
    cluster.logs[str(build.id)] = b"output\n"
    run_pass(db_session, client=cluster, settings=settings)

    cluster.logs[str(build.id)] = None  # pod gone, nothing to read
    run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(build)
    assert bytes(build.log) == b"output\n"


def test_the_log_is_truncated_at_the_cap_with_a_marker(db_session, cluster, settings):
    user = _user(db_session)
    build = _queued(db_session, user.id)
    settings.build_log_max_bytes = 200
    run_pass(db_session, client=cluster, settings=settings)
    db_session.refresh(build)
    cluster.logs[str(build.id)] = b"x" * 5000

    run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(build)
    stored = bytes(build.log)
    assert len(stored) <= 200
    assert b"truncated" in stored


def test_the_log_is_captured_before_the_outcome_is_recorded(db_session, cluster, settings):
    """A failed build's log is what explains the failure, so it must be stored
    even on the pass that fails the build."""
    user = _user(db_session)
    build = _queued(db_session, user.id)
    run_pass(db_session, client=cluster, settings=settings)
    db_session.refresh(build)
    cluster.logs[str(build.id)] = b"ERROR: stack detection failed\n"
    cluster.fail(build.id)

    run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(build)
    assert build.status == BUILD_STATUS_FAILED
    assert b"stack detection failed" in bytes(build.log)


def test_hostile_log_bytes_survive_the_round_trip(db_session, cluster, settings):
    user = _user(db_session)
    build = _queued(db_session, user.id)
    run_pass(db_session, client=cluster, settings=settings)
    db_session.refresh(build)
    hostile = b"compiling\x00\xff\xfe raw \x80 bytes\n"
    cluster.logs[str(build.id)] = hostile

    run_pass(db_session, client=cluster, settings=settings)

    db_session.refresh(build)
    assert bytes(build.log) == hostile


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_truncate_keeps_the_total_within_the_cap():
    out = truncate_log(b"y" * 10_000, cap=500)

    assert len(out) == 500
    assert out.endswith(b"\n") or b"truncated" in out


def test_truncate_leaves_a_short_log_untouched():
    assert truncate_log(b"short", cap=500) == b"short"


@pytest.mark.parametrize(
    "stored,fresh,expected",
    [
        (b"", b"new", b"new"),
        (b"abc", b"abcdef", b"abcdef"),
        (b"abcdef", b"abc", b"abcdef"),  # shorter read discarded
        (b"abc", None, b"abc"),
        (b"abc", b"", b"abc"),
    ],
)
def test_merge_log_never_goes_backwards(stored, fresh, expected):
    assert merge_log(stored, fresh, cap=1000) == expected


# ---------------------------------------------------------------------------
# The Job manifest
# ---------------------------------------------------------------------------


def test_the_job_manifest_carries_the_security_posture(settings):
    build_id = uuid4()
    manifest = build_job_manifest(
        build_id=build_id, user_id=7, artifact_url="https://x/y", settings=settings
    )
    spec = manifest["spec"]
    pod = spec["template"]["spec"]

    assert manifest["metadata"]["name"] == f"build-{build_id}"
    assert manifest["metadata"]["labels"][BUILD_ID_LABEL] == str(build_id)
    assert spec["backoffLimit"] == 0
    assert spec["activeDeadlineSeconds"] == settings.build_deadline_seconds
    assert spec["ttlSecondsAfterFinished"] > 0
    assert pod["restartPolicy"] == "Never"
    assert pod["automountServiceAccountToken"] is False
    assert pod["serviceAccountName"] == "caelus-builder"
    assert pod["securityContext"]["runAsUser"] == 1000
    assert pod["securityContext"]["seccompProfile"]["type"] == "Unconfined"
    assert pod["securityContext"]["appArmorProfile"]["type"] == "Unconfined"


def test_the_job_manifest_bounds_its_resources(settings):
    manifest = build_job_manifest(
        build_id=uuid4(), user_id=7, artifact_url="https://x/y", settings=settings
    )
    pod = manifest["spec"]["template"]["spec"]
    limits = pod["containers"][0]["resources"]["limits"]

    assert limits["cpu"] and limits["memory"] and limits["ephemeral-storage"]
    for volume in pod["volumes"]:
        assert volume["emptyDir"]["sizeLimit"], f"{volume['name']} is unbounded"


def _env(manifest) -> dict[str, str]:
    return {e["name"]: e["value"] for e in manifest["spec"]["template"]["spec"]["containers"][0]["env"]}


def test_the_job_manifest_carries_only_expiring_credentials(settings):
    """The artifact URL and the build's capability; no database URL, no
    registry key, nothing long-lived."""
    manifest = build_job_manifest(
        build_id=uuid4(), user_id=7, artifact_url="https://store/one-object", settings=settings
    )
    env = _env(manifest)

    assert env["CAELUS_ARTIFACT_URL"] == "https://store/one-object"
    assert env["CAELUS_USER_ID"] == "7"
    assert env["CAELUS_REGISTRY"] == settings.registry_host
    assert env["CAELUS_REGISTRY_TOKEN"]
    assert "CAELUS_CACHE_SCOPE" not in env
    blob = json.dumps(manifest).lower()
    for forbidden in ("database_url", "postgres", "secret_access_key", "s3_access", "private key"):
        assert forbidden not in blob, f"{forbidden} leaked into the build Job"


def _capability(manifest, settings, key) -> dict:
    return jwt.decode(
        _env(manifest)["CAELUS_REGISTRY_TOKEN"], key.public_key(), algorithms=["ES256"],
        audience=settings.registry_host, issuer=settings.registry_token_issuer,
    )


def test_the_build_capability_names_exactly_six_repositories(settings, signing_key):
    build_id = uuid4()
    manifest = build_job_manifest(
        build_id=build_id, user_id=7, artifact_url="https://x/y", settings=settings
    )
    claims = _capability(manifest, settings, signing_key)

    assert claims["access"] == [
        {"type": "repository", "name": "u/7", "actions": ["pull", "push"]},
        {"type": "repository", "name": "cache/7", "actions": ["pull", "push"]},
        {"type": "repository", "name": "railwayapp/railpack-frontend", "actions": ["pull"]},
        {"type": "repository", "name": "railwayapp/railpack-builder", "actions": ["pull"]},
        {"type": "repository", "name": "railwayapp/railpack-runtime", "actions": ["pull"]},
        {"type": "repository", "name": "docker/dockerfile", "actions": ["pull"]},
    ]
    assert claims["sub"] == f"build:{build_id}"


def test_the_build_capability_holds_no_pattern_delete_or_catalog(settings, signing_key):
    manifest = build_job_manifest(
        build_id=uuid4(), user_id=7, artifact_url="https://x/y", settings=settings
    )
    for entry in _capability(manifest, settings, signing_key)["access"]:
        assert entry["type"] == "repository"
        assert "*" not in entry["name"] and not entry["name"].endswith("/")
        assert set(entry["actions"]) <= {"pull", "push"}


def test_the_build_capability_outlives_the_deadline_by_the_margin(settings, signing_key):
    manifest = build_job_manifest(
        build_id=uuid4(), user_id=7, artifact_url="https://x/y", settings=settings
    )
    claims = _capability(manifest, settings, signing_key)

    assert claims["exp"] - claims["iat"] == settings.build_deadline_seconds + CAPABILITY_MARGIN_SECONDS


def test_the_capability_names_the_repositories_the_builder_uses(settings, signing_key):
    """build.py derives the push and cache targets on its own; the two sides
    must agree or every push is refused."""
    from tests.test_builder_script import build

    manifest = build_job_manifest(
        build_id=uuid4(), user_id=7, artifact_url="https://x/y", settings=settings
    )
    names = {e["name"] for e in _capability(manifest, settings, signing_key)["access"]}
    cache_repo = build.cache_ref("registry", "7").split("/", 1)[1].split(":")[0]

    assert {build.image_repository("7"), cache_repo} <= names
    assert build.FRONTEND_IMAGE.split("/", 1)[1].split("@")[0] in MIRRORED_REPOSITORIES
    assert build.DOCKERFILE_FRONTEND_REPO in MIRRORED_REPOSITORIES


def test_a_job_is_refused_when_the_registry_is_not_configured(settings):
    settings.registry_signing_private_key = ""

    with pytest.raises(RegistryKeyException):
        build_job_manifest(
            build_id=uuid4(), user_id=7, artifact_url="https://x/y", settings=settings
        )


def test_the_job_uses_the_configured_builder_image(settings):
    manifest = build_job_manifest(
        build_id=uuid4(), user_id=7, artifact_url="https://x/y", settings=settings
    )

    assert manifest["spec"]["template"]["spec"]["containers"][0]["image"] == settings.builder_image


def test_a_job_is_refused_when_no_builder_image_is_configured(settings):
    """The setting defaults to empty so that alembic, the tests and the local
    CLI can construct settings at all. Building is the one path that cannot,
    and it should say so rather than submit a Job with an empty image."""
    settings.builder_image = ""

    with pytest.raises(ValueError, match="CAELUS_BUILDER_IMAGE"):
        build_job_manifest(
            build_id=uuid4(), user_id=7, artifact_url="https://x/y", settings=settings
        )


@pytest.mark.parametrize(
    "message,expected",
    [
        (json.dumps({"image": IMAGE}), IMAGE),
        (json.dumps({"error": "nope"}), None),
        (json.dumps({"image": ""}), None),
        (json.dumps({"image": 42}), None),
        (json.dumps(["not", "an", "object"]), None),
        ("not json at all", None),
        ("", None),
        (None, None),
    ],
)
def test_termination_message_parsing(message, expected):
    assert build_jobs.parse_image_from_termination_message(message) == expected
