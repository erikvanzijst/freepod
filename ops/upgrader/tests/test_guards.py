"""The gh and git guards, the pre-push hook and the credential helper (product-upgrade-guardrails)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GH = ROOT / "bin" / "gh"
GIT = ROOT / "bin" / "git"
HOOKS = ROOT / "hooks"
HELPER = ROOT / "bin" / "git-credential-upgrader"
REAL_GIT = shutil.which("git", path=os.defpath + ":/usr/local/bin")


@pytest.fixture
def fake(tmp_path):
    """A stand-in for the real binary that reports how it was called."""
    script = tmp_path / "real"
    script.write_text('#!/usr/bin/env bash\necho "REAL $* token=${GH_TOKEN:-}"\n')
    script.chmod(0o755)
    return script


def call(guard, args, fake, **env):
    return subprocess.run(
        [str(guard), *args],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "UPGRADER_REAL_GH": str(fake),
            "UPGRADER_REAL_GIT": str(fake),
            **env,
        },
    )


ALLOWED = [
    ["pr", "list", "--state", "open"],
    ["pr", "view", "12"],
    ["pr", "diff", "12"],
    ["pr", "checks", "12", "--watch"],
    ["api", "--paginate", "repos/immich-app/immich/releases"],
    ["api", "-X", "GET", "repos/o/r/tags", "-f", "per_page=100"],
    ["api", "--method=get", "repos/o/r/tags", "-F", "per_page=100"],
    ["auth", "status"],
    ["label", "list"],
    ["release", "view", "v1.0.0"],
    ["run", "view", "42"],
    ["search", "prs", "upgrade"],
    ["--version"],
]

REFUSED = [
    ["pr", "merge", "123"],
    ["pr", "close", "1"],
    ["pr", "reopen", "1"],
    ["pr", "edit", "1", "--title", "x"],
    ["pr", "comment", "1", "-b", "x"],
    ["pr", "review", "1", "--approve"],
    ["pr", "ready", "1"],
    ["issue", "create", "-t", "x"],
    ["issue", "comment", "1", "-b", "x"],
    ["issue", "close", "1"],
    ["auth", "token"],
    ["auth", "login"],
    ["auth", "logout"],
    ["auth", "git-credential", "get"],
    ["repo", "create", "x"],
    ["repo", "delete", "o/r"],
    ["repo", "edit", "--visibility", "private"],
    ["repo", "fork"],
    ["label", "delete", "x"],
    ["label", "edit", "x"],
    ["release", "create", "v1"],
    ["workflow", "run", "ci.yml"],
    ["secret", "set", "X"],
    ["api", "-X", "POST", "repos/erikvanzijst/freepod/issues/1/comments"],
    ["api", "-XPOST", "repos/o/r/labels"],
    ["api", "--method", "PATCH", "repos/o/r/pulls/1"],
    ["api", "--method=DELETE", "repos/o/r/git/refs/heads/x"],
    ["api", "repos/erikvanzijst/freepod/labels", "-f", "name=x"],
    ["api", "repos/o/r/labels", "--raw-field=name=x"],
    ["api", "graphql", "-f", "query=mutation { x }"],
    ["api", "--input", "body.json", "repos/o/r/pulls"],
    [],
]


@pytest.mark.parametrize("dry", ["1", "0"])
@pytest.mark.parametrize("args", ALLOWED, ids=" ".join)
def test_gh_allows(args, dry, fake):
    out = call(GH, args, fake, UPGRADE_DRY_RUN=dry)
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("REAL " + " ".join(args))


@pytest.mark.parametrize("dry", ["1", "0"])
@pytest.mark.parametrize("args", REFUSED, ids=lambda a: " ".join(a) or "<none>")
def test_gh_refuses(args, dry, fake):
    out = call(GH, args, fake, UPGRADE_DRY_RUN=dry)
    assert out.returncode != 0
    assert "refused" in out.stderr
    assert "REAL" not in out.stdout


@pytest.mark.parametrize(
    "args",
    [["pr", "create", "--base", "master", "--draft"], ["label", "create", "product-upgrade"]],
    ids=" ".join,
)
def test_gh_opens_only_in_real_runs(args, fake):
    assert call(GH, args, fake, UPGRADE_DRY_RUN="0").returncode == 0
    refused = call(GH, args, fake, UPGRADE_DRY_RUN="1")
    assert refused.returncode != 0 and "refused" in refused.stderr
    assert call(GH, args, fake).returncode != 0


def test_gh_auth_setup_git_is_a_no_op(fake):
    out = call(GH, ["auth", "setup-git"], fake)
    assert out.returncode == 0
    assert out.stdout == ""


def test_gh_auth_token_prints_no_token(fake, tmp_path):
    token = tmp_path / "token"
    token.write_text("ghs_secret")
    out = call(GH, ["auth", "token"], fake, UPGRADER_TOKEN_FILE=str(token))
    assert out.returncode != 0
    assert "ghs_secret" not in out.stdout + out.stderr


def test_gh_takes_the_current_token_from_the_file(fake, tmp_path):
    token = tmp_path / "token"
    token.write_text("ghs_current")
    out = call(GH, ["pr", "list"], fake, UPGRADER_TOKEN_FILE=str(token), GH_TOKEN="stale")
    assert out.stdout.strip().endswith("token=ghs_current")


GIT_REFUSED = [
    ["grep", "-c", "foo", "v3.2.1"],
    ["log", "-p", "a..b"],
    ["log", "--patch", "a..b"],
    ["log", "-S", "x", "a..b"],
    ["log", "-Sx", "a..b"],
    ["log", "-G", "x", "a..b"],
    ["log", "--pickaxe-regex", "-S", "x", "a..b"],
    ["-C", "repo", "grep", "foo"],
    ["-c", "core.pager=cat", "log", "-p", "a..b"],
    ["grep", "-l", "IMMICH_CONFIG_FILE", "v3.2.1", "--"],
    ["log", "-S", "x", "a..b", "--", "."],
    ["log", "-p", "a..b", "--", ":/"],
    ["grep", "foo", "v1", "--", "*"],
    ["grep", "foo", "v1", "--", ":(top)", ""],
]
GIT_PASSED = [
    ["log", "-S", "x", "a..b", "--", "docker/"],
    ["-C", "repo", "grep", "foo", "--", "src/"],
    ["log", "--oneline", "a..b"],
    ["diff", "a", "b"],
    ["show", "a"],
    ["log", "-3", "--", "Dockerfile"],
    ["grep", "foo", "v1", "--", ".", "server/"],
]


@pytest.mark.parametrize("args", GIT_REFUSED, ids=" ".join)
def test_git_refuses_pathless_searches(args, fake):
    out = call(GIT, args, fake)
    assert out.returncode != 0
    assert "-- <path>" in out.stderr
    assert "REAL" not in out.stdout


@pytest.mark.parametrize("args", GIT_PASSED, ids=" ".join)
def test_git_passes(args, fake):
    out = call(GIT, args, fake)
    assert out.returncode == 0
    assert out.stdout.startswith("REAL " + " ".join(args))


def test_docker_is_not_available_to_the_agent():
    out = subprocess.run([str(ROOT / "bin" / "docker"), "run", "--rm", "valkey/valkey:9.0-alpine"],
                         capture_output=True, text=True)
    assert out.returncode == 127
    assert "not available" in out.stderr


@pytest.fixture
def clone(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    git = lambda *a, cwd=tmp_path: subprocess.run(  # noqa: E731
        [REAL_GIT, *a], cwd=cwd, check=True, capture_output=True
    )
    git("init", "-q", "--bare", "-b", "master", str(remote))
    git("clone", "-q", str(remote), str(work))
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x", cwd=work)
    return remote, work


def push(work, refspec, dry):
    return subprocess.run(
        [REAL_GIT, "-c", f"core.hooksPath={HOOKS}", "push", "-q", "origin", refspec],
        cwd=work,
        capture_output=True,
        text=True,
        env={**os.environ, "UPGRADE_DRY_RUN": dry},
    )


def remote_refs(remote):
    out = subprocess.run([REAL_GIT, "for-each-ref", "--format=%(refname)"], cwd=remote,
                         capture_output=True, text=True, check=True)
    return set(out.stdout.split())


def test_hook_lets_a_real_run_push_an_upgrade_branch(clone):
    remote, work = clone
    assert push(work, "HEAD:refs/heads/upgrade/immich-v3.2.1", "0").returncode == 0
    assert "refs/heads/upgrade/immich-v3.2.1" in remote_refs(remote)


@pytest.mark.parametrize("ref", ["refs/heads/master", "refs/heads/nextcloud-34.0.4", "refs/tags/v1"])
def test_hook_refuses_other_refs(clone, ref):
    remote, work = clone
    out = push(work, f"HEAD:{ref}", "0")
    assert out.returncode != 0 and "refused" in out.stderr
    assert ref not in remote_refs(remote)


@pytest.mark.parametrize("dry", ["1", "", "false"])
def test_hook_refuses_every_push_in_a_dry_run(clone, dry):
    remote, work = clone
    out = push(work, "HEAD:refs/heads/upgrade/vaultwarden-1.37.3", dry)
    assert out.returncode != 0 and "dry run" in out.stderr
    assert remote_refs(remote) == set()


def helper(stdin, **env):
    return subprocess.run([str(HELPER), "get"], input=stdin, capture_output=True, text=True,
                          env={"PATH": os.environ["PATH"], **env})


def test_credential_helper_answers_github_with_the_token_file(tmp_path):
    token = tmp_path / "token"
    token.write_text("ghs_now")
    out = helper("protocol=https\nhost=github.com\n\n", UPGRADER_TOKEN_FILE=str(token))
    assert out.stdout == "username=x-access-token\npassword=ghs_now\n"


def test_credential_helper_ignores_other_hosts(tmp_path):
    token = tmp_path / "token"
    token.write_text("ghs_now")
    out = helper("protocol=https\nhost=gitlab.com\n\n", UPGRADER_TOKEN_FILE=str(token))
    assert out.stdout == ""
