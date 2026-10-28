"""The prune: untags exactly what retention does not keep, cheaply."""

from collections import Counter
from datetime import UTC, datetime, timedelta

import httpx

from app.config import CaelusSettings
from app.models import UserORM
from app.services import registry_prune, registry_tokens
from app.services.registry_prune import prune
from tests.conftest import db_session, make_bare_deployment  # noqa: F401
from tests.test_image_retention import _build, _image, _naive, _ship, owner  # noqa: F401

SETTINGS = CaelusSettings()


class FakeRegistry:
    def __init__(self):
        self.repos: dict[str, dict[str, str]] = {}  # repository -> tag -> digest
        self.requests: Counter = Counter()
        self.deleted: list[tuple[str, str]] = []
        self.fail_delete: set[str] = set()
        self.on_list = None

    def push(self, repository, tag, digest):
        self.repos.setdefault(repository, {})[tag] = digest

    def tags(self, repository):
        self.requests["tags"] += 1
        tags = list(self.repos.get(repository, {}))
        if self.on_list:
            self.on_list()
        yield from tags

    def digest(self, repository, tag):
        self.requests["digest"] += 1
        return self.repos[repository][tag]

    def delete_tag(self, repository, tag):
        self.requests["delete"] += 1
        if tag in self.fail_delete:
            raise httpx.ConnectError("boom")
        del self.repos[repository][tag]
        self.deleted.append((repository, tag))


def _digest(owner, n):
    return _image(owner, n).split("@", 1)[1]


def _old():
    return _naive(datetime.now(UTC) - timedelta(days=3))


def _shipped(db_session, registry, owner, count):
    d = make_bare_deployment(db_session, owner)
    builds = []
    for n in range(1, count + 1):
        build = _build(db_session, d, image=_image(owner, n), finished_at=_old())
        _ship(db_session, d, {"image": build.image})
        registry.push(f"u/{owner}", str(build.id), _digest(owner, n))
        builds.append(build)
    return d, builds


def _prune(db_session, registry, owner, *, dry_run=False):
    [report] = prune(db_session, registry, SETTINGS, dry_run=dry_run, owners=[owner])
    return report


def test_tags_outside_retention_are_removed(db_session, owner):
    registry = FakeRegistry()
    _, builds = _shipped(db_session, registry, owner, 5)
    report = _prune(db_session, registry, owner)
    assert sorted(report.removed) == sorted(str(b.id) for b in builds[:2])
    assert set(registry.repos[f"u/{owner}"]) == {str(b.id) for b in builds[2:]}
    assert not report.failed


def test_build_tags_cost_no_request_beyond_listing_and_removal(db_session, owner):
    registry = FakeRegistry()
    _shipped(db_session, registry, owner, 5)
    _prune(db_session, registry, owner)
    assert registry.requests == Counter(tags=1, delete=2)


def test_two_tags_on_one_retained_image_both_survive(db_session, owner):
    registry = FakeRegistry()
    _shipped(db_session, registry, owner, 1)
    registry.push(f"u/{owner}", "rebuild-same-bytes", _digest(owner, 1))
    report = _prune(db_session, registry, owner)
    assert report.removed == []
    assert len(registry.repos[f"u/{owner}"]) == 2


def test_a_tag_with_no_build_row_is_judged_by_its_image(db_session, owner):
    registry = FakeRegistry()
    _shipped(db_session, registry, owner, 1)
    registry.push(f"u/{owner}", "migrated-live", _digest(owner, 1))
    registry.push(f"u/{owner}", "migrated-dead", _digest(owner, 77))
    report = _prune(db_session, registry, owner)
    assert report.removed == ["migrated-dead"]
    assert registry.requests["digest"] == 2


def test_a_tag_whose_build_is_running_is_kept_without_a_request(db_session, owner):
    registry = FakeRegistry()
    d, _ = _shipped(db_session, registry, owner, 1)
    running = _build(db_session, d, status="running")
    registry.push(f"u/{owner}", str(running.id), _digest(owner, 50))
    report = _prune(db_session, registry, owner)
    assert report.removed == []
    assert report.kept[str(running.id)] == "fresh build"
    assert registry.requests["digest"] == 0


def test_a_failed_build_that_pushed_is_judged_by_its_digest(db_session, owner):
    registry = FakeRegistry()
    d, _ = _shipped(db_session, registry, owner, 1)
    failed = _build(db_session, d, status="failed", finished_at=_old())
    registry.push(f"u/{owner}", str(failed.id), _digest(owner, 51))
    report = _prune(db_session, registry, owner)
    assert report.removed == [str(failed.id)]


def test_a_build_finishing_during_the_prune_is_kept(db_session, owner):
    """The tag is listed while the build still runs; the ledger is read after
    the build has succeeded. Either way the tag survives."""
    registry = FakeRegistry()
    d, _ = _shipped(db_session, registry, owner, 1)
    build = _build(db_session, d, status="running")
    registry.push(f"u/{owner}", str(build.id), _digest(owner, 60))

    def finish():
        build.status = "succeeded"
        build.image = _image(owner, 60)
        build.finished_at = _naive(datetime.now(UTC))
        db_session.add(build)
        db_session.commit()

    registry.on_list = finish
    assert _prune(db_session, registry, owner).removed == []


def test_a_dry_run_removes_nothing_and_reports_what_it_would(db_session, owner):
    registry = FakeRegistry()
    _, builds = _shipped(db_session, registry, owner, 4)
    report = _prune(db_session, registry, owner, dry_run=True)
    assert report.removed == [str(builds[0].id)]
    assert registry.deleted == []
    assert report.as_dict()["kept"] == {"applied": 1, "earlier": 2}


def test_one_failed_removal_does_not_stop_the_rest(db_session, owner):
    registry = FakeRegistry()
    _, builds = _shipped(db_session, registry, owner, 5)
    registry.fail_delete = {str(builds[0].id)}
    report = _prune(db_session, registry, owner)
    assert report.removed == [str(builds[1].id)]
    assert report.failed == [str(builds[0].id)]


def test_the_cache_repository_is_never_touched(db_session, owner):
    registry = FakeRegistry()
    _shipped(db_session, registry, owner, 4)
    registry.push(f"cache/{owner}", "latest", "sha256:" + "c" * 64)
    _prune(db_session, registry, owner)
    assert all(repo == f"u/{owner}" for repo, _ in registry.deleted)
    assert "latest" in registry.repos[f"cache/{owner}"]


def test_owners_are_streamed_together_and_never_mixed(db_session, owner):
    other = UserORM(email="other-owner@example.com")
    db_session.add(other)
    db_session.commit()
    registry = FakeRegistry()
    _, mine = _shipped(db_session, registry, owner, 4)
    _shipped(db_session, registry, other.id, 1)
    reports = {r.owner: r for r in prune(db_session, registry, SETTINGS, dry_run=True)}
    assert reports[owner].removed == [str(mine[0].id)]
    assert reports[other.id].removed == []
    assert registry.requests == Counter(tags=2)


def test_an_owner_whose_listing_fails_is_reported_and_the_rest_continue(db_session, owner):
    class Flaky(FakeRegistry):
        def tags(self, repository):
            if repository == "u/999999":
                raise httpx.ConnectError("down")
            return super().tags(repository)

    registry = Flaky()
    _shipped(db_session, registry, owner, 4)
    reports = list(prune(db_session, registry, SETTINGS, dry_run=False, owners=[999999, owner]))
    assert reports[0].failed == ["*"]
    assert reports[1].removed


def test_an_owner_with_tags_but_no_ledger_loses_them(db_session, owner):
    registry = FakeRegistry()
    registry.push(f"u/{owner}", "orphan", "sha256:" + "d" * 64)
    assert _prune(db_session, registry, owner).removed == ["orphan"]


def _signing_settings():
    return CaelusSettings(
        _env_file=None,
        registry_host="cr.test.example",
        registry_token_issuer="t",
        registry_signing_private_key=registry_tokens.private_key_pem(
            registry_tokens.generate_private_key()
        ),
    )


def test_the_http_registry_pages_tags_and_resolves_with_a_head():
    seen = []
    pages = {
        "/v2/u/7/tags/list?n=1000": ({"tags": ["a"]}, '</v2/u/7/tags/list?last=a&n=1000>; rel="next"'),
        "/v2/u/7/tags/list?last=a&n=1000": ({"tags": ["b"]}, None),
    }

    def handler(request: httpx.Request):
        path = request.url.raw_path.decode()
        seen.append(request.method)
        assert request.headers["authorization"].startswith("Bearer ")
        if path in pages:
            body, link = pages[path]
            return httpx.Response(200, json=body, headers={"Link": link} if link else {})
        if request.method == "HEAD" and path == "/v2/u/7/manifests/a":
            return httpx.Response(200, headers={"docker-content-digest": "sha256:idx"})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    registry = registry_prune.HttpRegistry(_signing_settings(), client=client)
    assert list(registry.tags("u/7")) == ["a", "b"]
    assert registry.digest("u/7", "a") == "sha256:idx"
    assert seen == ["GET", "GET", "HEAD"]


def _cli_prune(cli_runner, monkeypatch, registry, *args):
    runner, app = cli_runner
    monkeypatch.setattr(registry_prune, "HttpRegistry", lambda settings: registry)
    return runner.invoke(app, ["registry-prune", *args])


def test_the_command_reports_per_owner_and_exits_zero(cli_runner, db_session, owner, monkeypatch):
    registry = FakeRegistry()
    _, builds = _shipped(db_session, registry, owner, 4)
    result = _cli_prune(cli_runner, monkeypatch, registry, "--dry-run", "--owner", str(owner))
    assert result.exit_code == 0, result.output
    assert str(builds[0].id) in result.stdout
    assert registry.deleted == []


def test_the_command_exits_non_zero_when_a_removal_failed(cli_runner, db_session, owner, monkeypatch):
    registry = FakeRegistry()
    _, builds = _shipped(db_session, registry, owner, 5)
    registry.fail_delete = {str(builds[0].id)}
    result = _cli_prune(cli_runner, monkeypatch, registry, "--owner", str(owner))
    assert result.exit_code == 1, result.output
    assert (f"u/{owner}", str(builds[1].id)) in registry.deleted
