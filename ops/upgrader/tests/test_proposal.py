"""The service's checks of a session's proposed pull request (D4, product-upgrade-runs)."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from upgrader import proposal
from upgrader.proposal import Clone, Proposal, check_text
from upgrader.result import ResultError

GIT = shutil.which("git", path="/usr/local/bin:/usr/bin")
SCHEMA = Path(__file__).resolve().parents[3] / "products" / "UPGRADING" / "result.schema.json"


def make(**fields):
    base = dict(slug="immich", branch="upgrade/immich-v3.2.1", title="Immich: Upgrade to v3.2.1",
                body="## Summary\nUpgrade.\n", patch=b"From x\n", draft=False)
    return Proposal(**{**base, **fields})


@pytest.mark.parametrize("fields", [
    {},
    {"body": "Release notes: https://github.com/immich-app/immich/releases/tag/v3.2.1"},
    {"body": "Fixed the invite flow (`#123`) and bumped `@nextcloud/dialogs`."},
    {"body": "```\nthanks @someone\n```\nmail ops@example.com"},
    {"body": "See #160 in this repository."},
], ids=["plain", "release-link", "code-spans", "fence-and-email", "own-pr"])
def test_accepts(fields):
    check_text(make(**fields), "v3.2.1")


@pytest.mark.parametrize("fields, reason", [
    ({"branch": "upgrade/immich-v3.2.0"}, "branch must be upgrade/immich-v3.2.1"),
    ({"branch": "nextcloud-34"}, "branch must be"),
    ({"title": "Bump immich"}, "title must be one line"),
    ({"title": "Immich: Upgrade to v3.2.1\nand more"}, "title must be one line"),
    ({"title": "Immich: Upgrade to v3.2.10"}, "title must be one line"),
    ({"body": "x" * 65537}, "65537 characters"),
    ({"body": "Fixes https://github.com/immich-app/immich/pull/123"}, "links an issue or pull request"),
    ({"body": "see `https://github.com/immich-app/immich/issues/9`"}, "links an issue or pull request"),
    ({"body": "Thanks @alice!"}, "@ outside backticks"),
    ({"body": "`code` then @bob"}, "@ outside backticks"),
    ({"patch": b"  \n"}, "change.patch is empty"),
], ids=["old-target", "other-branch", "free-title", "two-line-title", "longer-target", "long-body",
        "pr-link", "linked-in-code", "mention", "mention-after-code", "empty-patch"])
def test_refuses(fields, reason):
    with pytest.raises(ResultError, match=reason):
        check_text(make(**fields), "v3.2.1")


@pytest.fixture
def origin(tmp_path):
    work = tmp_path / "work"
    (work / "products" / "catalog").mkdir(parents=True)
    (work / "products" / "immich").mkdir()
    (work / "products" / "catalog" / "immich.yaml").write_text("tag: v3.2.0\n")
    (work / "products" / "catalog" / "nextcloud.yaml").write_text("tag: 34\n")
    (work / "products" / "immich" / "README.md").write_text("# Immich\n")
    git(work, "init", "-q", "-b", "master")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "catalog")
    git(tmp_path, "clone", "-q", "--bare", str(work), str(tmp_path / "origin.git"))
    return work, f"file://{tmp_path / 'origin.git'}"


def git(cwd, *args):
    return subprocess.run([GIT, "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          check=True, capture_output=True).stdout


def patch_of(work, edit):
    """A patch made the way a session makes one: commits on a branch, then format-patch."""
    git(work, "checkout", "-q", "-B", "upgrade/immich-v3.2.1", "master")
    edit(work)
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "Immich: Upgrade to v3.2.1")
    return git(work, "format-patch", "--stdout", "master..HEAD")


def service_clone(tmp_path, url):
    git(tmp_path, "clone", "-q", "--depth", "1", url, str(tmp_path / "service"))
    return Clone(tmp_path / "service", GIT, os.environ)


def tag_bump(work):
    (work / "products/catalog/immich.yaml").write_text("tag: v3.2.1\n")


def test_a_tag_bump_applies_on_top_of_master(tmp_path, origin):
    work, url = origin
    clone = service_clone(tmp_path, url)
    base = clone.apply(make(patch=patch_of(work, tag_bump)))
    assert base == git(work, "rev-parse", "master").decode().strip()
    assert (clone.path / "products/catalog/immich.yaml").read_text() == "tag: v3.2.1\n"


@pytest.mark.parametrize("edit, reason", [
    (lambda w: (w / "products/catalog/nextcloud.yaml").write_text("tag: 35\n"),
     "changes products/catalog/nextcloud.yaml, outside"),
    (lambda w: ((w / ".github").mkdir(), (w / ".github/ci.yml").write_text("on: push\n")),
     "changes .github/ci.yml, outside"),
    (lambda w: (w / "products/immich/link").symlink_to("/etc/passwd"), "makes products/immich/link a symbolic link"),
    (lambda w: (w / "products/immichx").mkdir() or (w / "products/immichx/a").write_text("x"),
     "changes products/immichx/a, outside"),
], ids=["other-product", "outside-products", "symlink", "prefix-lookalike"])
def test_a_patch_outside_the_products_files_is_refused(tmp_path, origin, edit, reason):
    work, url = origin
    clone = service_clone(tmp_path, url)
    with pytest.raises(ResultError, match=reason):
        clone.apply(make(patch=patch_of(work, edit)))


def test_a_patch_that_does_not_apply_is_refused(tmp_path, origin):
    work, url = origin
    patch = patch_of(work, tag_bump)
    git(work, "checkout", "-q", "master")
    (work / "products/catalog/immich.yaml").write_text("tag: v3.3.0\n")
    git(work, "commit", "-q", "-am", "someone else moved master")
    git(work, "push", "-q", url, "master")
    with pytest.raises(ResultError, match="does not apply to master"):
        service_clone(tmp_path, url).apply(make(patch=patch))


def test_an_invalid_branch_name_is_refused(tmp_path, origin):
    _, url = origin
    with pytest.raises(ResultError, match="not a valid branch name"):
        service_clone(tmp_path, url).apply(make(branch="upgrade/immich-v3..2"))


def test_the_local_runners_check(tmp_path, origin, capsys):
    work, url = origin
    out = tmp_path / "out" / "immich"
    out.mkdir(parents=True)
    (out / "change.patch").write_bytes(patch_of(work, tag_bump))
    (out / "body.md").write_text("## Summary\nUpgrade.\n")
    (out / "meta.json").write_text(json.dumps({"title": "Immich: Upgrade to v3.2.1"}))
    result = {"schema_version": 2, "product": "immich", "dry_run": True, "status": "would_open",
              "current_version": "v3.2.0", "target_version": "v3.2.1", "draft": False,
              "branch": "upgrade/immich-v3.2.1", "skip_reason": None, "needs_human": [], "error": None}
    (out / "result.json").write_text(json.dumps(result))
    args = [str(SCHEMA), str(tmp_path / "out"), "immich", url]
    assert proposal.main(args) == 0
    assert capsys.readouterr().out.startswith("immich: would_open v3.2.0 -> v3.2.1")
    (out / "body.md").write_text("Thanks @alice\n")
    assert proposal.main(args) == 1
    assert "immich: failed: body.md has an @ outside backticks" in capsys.readouterr().out
