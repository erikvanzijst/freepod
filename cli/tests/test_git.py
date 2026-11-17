"""`freepod git`: the GitHub connection, repository creation, and git's credential helper."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest

from freepod import EXIT_ERROR, EXIT_OK, EXIT_USAGE
from freepod import git as git_module
from freepod.cli import main
from freepod.config import ENVIRONMENTS

from conftest import json_response

DEPLOYMENT = "0f6d3c1e-3a54-4a9b-9a1b-6b2a7f1e9c11"
USER = {"id": 7, "email": "dev@example.com", "is_admin": False, "created_at": "2026-01-01T00:00:00"}
CONNECTION = {
    "provider": "github",
    "host": "github.com",
    "account_id": "1001",
    "login": "alice",
    "connected_at": "2026-11-17T10:00:00",
    "expires_at": "2027-05-17T10:00:00",
}
INSTALLATIONS = [
    {"id": 77, "account": "alice", "account_type": "User", "repository_selection": "selected",
     "html_url": "https://github.com/settings/installations/77"},
    {"id": 88, "account": "acme", "account_type": "Organization", "repository_selection": "all",
     "html_url": "https://github.com/organizations/acme/settings/installations/88"},
]


class Platform:
    """A scripted Freepod API for the git endpoints."""

    def __init__(self, *, connected: bool = True, connect_after: Optional[int] = None):
        self.connected = connected
        self.connect_after = connect_after
        self.polls = 0
        self.requests: List[httpx.Request] = []
        self.forbid_write = False
        self.source: Optional[dict] = None
        self.refuse_link = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        path = request.url.path
        if path == "/api/me":
            return json_response(200, USER)
        if path == "/api/users/7/git":
            self.polls += 1
            if self.connect_after is not None and self.polls > self.connect_after:
                self.connected = True
            return json_response(200, [CONNECTION] if self.connected else [])
        if path == "/api/users/7/git/github/installations":
            if not self.connected:
                return json_response(409, {"detail": "not connected", "code": "git_not_connected"})
            return json_response(200, INSTALLATIONS)
        if path == "/api/users/7/git/github/repositories" and request.method == "POST":
            body = json.loads(request.content)
            if body["name"] == "taken":
                return json_response(409, {"detail": "alice/taken already exists on GitHub.",
                                           "code": "github_repo_exists"})
            owner = body.get("owner", "alice")
            return json_response(201, {
                "id": 5001,
                "full_name": f"{owner}/{body['name']}",
                "html_url": f"https://github.com/{owner}/{body['name']}",
                "clone_url": f"https://github.com/{owner}/{body['name']}.git",
                "private": body["private"],
                "default_branch": None,
            })
        if path == f"/api/users/7/deployments/{DEPLOYMENT}/source":
            if request.method == "GET":
                if self.source is None:
                    return json_response(404, {"detail": "not linked", "code": "source_not_linked"})
                return json_response(200, self.source)
            if request.method == "DELETE":
                if self.source is None:
                    return json_response(404, {"detail": "not linked", "code": "source_not_linked"})
                self.source = None
                return httpx.Response(204)
            if self.refuse_link:
                return json_response(404, {"detail": "GitHub repository x/y does not exist.",
                                           "code": "github_repo_not_found"})
            body = json.loads(request.content)
            self.source = {
                "provider": "github", "host": "github.com", "repository_id": "5001",
                "full_name": body["repository"], "html_url": f"https://github.com/{body['repository']}",
                "branch": body.get("branch") or "main", "root_dir": body.get("root_dir", ""),
                "linked_at": "2026-11-17T10:00:00",
            }
            return json_response(200, self.source)
        if path == "/api/users/7/git/github/repositories" and request.method == "GET":
            return json_response(200, [
                {"id": 5001, "full_name": "alice/recipes", "private": True, "default_branch": "main",
                 "html_url": "https://github.com/alice/recipes", "pushed_at": None},
                {"id": 5002, "full_name": "acme/site", "private": False, "default_branch": "main",
                 "html_url": "https://github.com/acme/site", "pushed_at": None},
            ])
        if path == "/api/users/7/git/github/credentials":
            body = json.loads(request.content)
            if body["access"] == "write" and self.forbid_write:
                return json_response(403, {"detail": "cannot push", "code": "github_repo_forbidden"})
            return json_response(200, {
                "repository": body["repository"],
                "username": "x-access-token",
                "password": f"ghs_{body['access']}",
                "expires_at": "2026-11-17T16:00:00Z",
            })
        return json_response(404, {"detail": "unexpected"})

    def bodies(self, path: str) -> List[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path == path]


class _StubSession:
    access_token = "token"
    credential_source = "stub"

    def authenticate(self, force_login: bool = False, interactive: bool = True) -> None:
        pass


@pytest.fixture
def run(monkeypatch):
    def go(platform: Platform, argv: List[str], stdin: str = "") -> int:
        from freepod.api import ApiClient

        monkeypatch.setattr("freepod.cli.Context.session", lambda self, force_flow=None: _StubSession())
        monkeypatch.setattr(
            "freepod.cli.Context.client",
            lambda self, session: ApiClient(
                self.env,
                session,
                client=httpx.Client(transport=httpx.MockTransport(platform)),
                backoff_base=0,
            ),
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        return main(argv)

    return go


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A git repository on `main` with one commit, as the working directory."""
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)
    root = tmp_path / "recipes"
    root.mkdir()
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "start"]):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
            cwd=root, check=True,
        )
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def project(repo):
    """A Freepod project in `web/` of the repository, whose origin is on GitHub."""
    from freepod.project import Project

    web = repo / "web"
    web.mkdir()
    Project(web, deployment_id=DEPLOYMENT).save()
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:alice/recipes.git"], cwd=repo, check=True)
    return web


def git_config(root: Path, *args: str) -> str:
    return subprocess.run(["git", "config", *args], cwd=root, capture_output=True, text=True).stdout


# --- The helper protocol ---------------------------------------------------


def test_a_request_ends_at_the_blank_line():
    stream = io.StringIO("protocol=https\nhost=github.com\npath=alice/recipes.git\n\nignored=1\n")
    assert git_module.read_request(stream) == {
        "protocol": "https", "host": "github.com", "path": "alice/recipes.git"
    }


@pytest.mark.parametrize(
    "path, expected",
    [
        ("alice/recipes.git", "alice/recipes"),
        ("/alice/recipes", "alice/recipes"),
        ("alice/recipes/info/refs", None),
        ("", None),
        ("../etc/passwd", None),
    ],
)
def test_the_repository_comes_from_the_path(path, expected):
    assert git_module.repository_of({"path": path}) == expected


def test_the_response_carries_the_expiry_as_epoch_seconds():
    issued = {"username": "x-access-token", "password": "p", "expires_at": "2026-11-17T16:00:00Z"}
    assert git_module.format_response(issued) == (
        "username=x-access-token\npassword=p\npassword_expiry_utc=1794931200\n"
    )


def test_the_helper_names_a_non_default_environment():
    assert git_module.helper_command(ENVIRONMENTS["prod"]) == "!freepod git credential"
    assert git_module.helper_command(ENVIRONMENTS["dev"]) == "!freepod --env dev git credential"


# --- git credential --------------------------------------------------------


def test_the_helper_answers_get_for_a_github_repository(run, capsys):
    platform = Platform()
    code = run(platform, ["git", "credential", "get"],
               stdin="protocol=https\nhost=github.com\npath=alice/recipes.git\n\n")
    assert code == EXIT_OK
    assert capsys.readouterr().out == (
        "username=x-access-token\npassword=ghs_write\npassword_expiry_utc=1794931200\n"
    )
    assert platform.bodies("/api/users/7/git/github/credentials") == [
        {"repository": "alice/recipes", "access": "write"}
    ]


def test_the_helper_falls_back_to_read_access(run, capsys):
    platform = Platform()
    platform.forbid_write = True
    run(platform, ["git", "credential", "get"],
        stdin="protocol=https\nhost=github.com\npath=acme/tools.git\n\n")
    assert "password=ghs_read" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv, stdin",
    [
        (["git", "credential", "get"], "protocol=https\nhost=gitlab.com\npath=a/b.git\n\n"),
        (["git", "credential", "store"], "protocol=https\nhost=github.com\npath=a/b.git\npassword=x\n\n"),
        (["git", "credential", "erase"], "protocol=https\nhost=github.com\n\n"),
    ],
)
def test_the_helper_stays_silent_for_anything_else(run, capsys, argv, stdin):
    platform = Platform()
    assert run(platform, argv, stdin=stdin) == EXIT_OK
    assert capsys.readouterr().out == ""
    assert platform.requests == []


def test_the_helper_needs_the_path(run, capsys):
    platform = Platform()
    code = run(platform, ["git", "credential", "get"], stdin="protocol=https\nhost=github.com\n\n")
    assert code == EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "useHttpPath" in captured.err


def test_the_helper_explains_a_missing_connection(run, capsys, monkeypatch):
    platform = Platform()
    original = platform.__call__

    def refuse(request):
        if request.url.path.endswith("/credentials"):
            request.read()
            return json_response(409, {"detail": "not connected", "code": "git_not_connected"})
        return original(request)

    code = run(refuse, ["git", "credential", "get"],
               stdin="protocol=https\nhost=github.com\npath=alice/recipes\n\n")
    assert code == EXIT_ERROR
    assert "freepod git connect" in capsys.readouterr().err


def test_the_helper_explains_itself_at_a_terminal(run, capsys, monkeypatch):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    platform = Platform()
    monkeypatch.setattr("freepod.cli.sys.stdin", Terminal(""))
    from freepod.cli import main as entry

    assert entry(["git", "credential", "get"]) == EXIT_USAGE
    assert "printf 'protocol=https" in capsys.readouterr().err
    assert platform.requests == []


def test_the_helper_does_no_housekeeping(run, monkeypatch):
    synced = []
    monkeypatch.setattr("freepod.cli.sync_skill", lambda ctx, context: synced.append(True))
    run(Platform(), ["git", "credential", "get"],
        stdin="protocol=https\nhost=github.com\npath=alice/recipes\n\n")
    assert synced == []


# --- status and connect ----------------------------------------------------


def test_status_names_the_account_and_its_installations(run, capsys):
    assert run(Platform(), ["git", "status"]) == EXIT_OK
    assert capsys.readouterr().out == (
        "github: alice\n"
        "  alice (personal account, selected repositories)\n"
        "  acme (organization, all repositories)\n"
    )


def test_status_fails_when_not_connected(run, capsys):
    assert run(Platform(connected=False), ["git", "status"]) == EXIT_ERROR
    assert "freepod git connect" in capsys.readouterr().err


def test_connect_prints_a_sign_in_link_and_waits(run, capsys):
    platform = Platform(connected=False, connect_after=2)
    assert run(platform, ["git", "connect"]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == "alice\n"
    link = next(line.strip() for line in captured.err.splitlines() if "oauth2/start" in line)
    parsed = urlparse(link)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://freepod.eu/oauth2/start"
    assert unquote(parse_qs(parsed.query)["rd"][0]) == "/settings/git?connect=github"
    assert platform.polls == 3


def test_connect_opens_no_browser_where_there_is_none(run, capsys, monkeypatch):
    opened = []
    monkeypatch.setattr("freepod.cli._at_terminal", lambda: True)
    monkeypatch.setattr("freepod.cli.detect_browser", lambda: (False, "running in a container"))
    monkeypatch.setattr("freepod.cli.webbrowser.open", lambda url: opened.append(url) or True)
    assert run(Platform(connected=False, connect_after=1), ["git", "connect"]) == EXIT_OK
    assert opened == []


def test_connect_opens_the_browser_where_there_is_one(run, capsys, monkeypatch):
    opened = []
    monkeypatch.setattr("freepod.cli._at_terminal", lambda: True)
    monkeypatch.setattr("freepod.cli.detect_browser", lambda: (True, "browser available"))
    monkeypatch.setattr("freepod.cli.webbrowser.open", lambda url: opened.append(url) or True)
    run(Platform(connected=False, connect_after=1), ["git", "connect"])
    assert len(opened) == 1 and "oauth2/start" in opened[0]
    assert "Opened it in your browser." in capsys.readouterr().err


def test_connect_gives_up_after_the_timeout(run, capsys, monkeypatch):
    ticks = iter(range(0, 10_000, 100))
    monkeypatch.setattr("freepod.git.time.monotonic", lambda: next(ticks))
    platform = Platform(connected=False)
    assert run(platform, ["--timeout", "250", "git", "connect"]) == EXIT_ERROR
    assert "gave up waiting" in capsys.readouterr().err


def test_connect_when_already_connected_prints_no_link(run, capsys):
    assert run(Platform(), ["git", "connect"]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == "alice\n"
    assert "oauth2/start" not in captured.err


# --- create and setup ------------------------------------------------------


def test_create_adds_the_remote_and_the_helper(run, repo, capsys):
    platform = Platform()
    assert run(platform, ["git", "create"]) == EXIT_OK
    assert capsys.readouterr().out == "https://github.com/alice/recipes\n"
    assert platform.bodies("/api/users/7/git/github/repositories") == [
        {"name": "recipes", "private": True}
    ]
    assert git_module.remote_url(repo, "origin") == "https://github.com/alice/recipes.git"
    assert git_config(repo, "--local", "--get-all", git_module.HELPER_KEY) == "\n!freepod git credential\n"
    assert git_config(repo, "--local", "--get", git_module.HTTP_PATH_KEY) == "true\n"


def test_create_on_an_organization_in_public(run, repo, capsys):
    platform = Platform()
    run(platform, ["git", "create", "site", "--owner", "acme", "--public"])
    assert platform.bodies("/api/users/7/git/github/repositories") == [
        {"name": "site", "private": False, "owner": "acme"}
    ]
    assert git_module.remote_url(repo, "origin") == "https://github.com/acme/site.git"


def test_create_refuses_to_replace_a_remote(run, repo, capsys):
    subprocess.run(["git", "remote", "add", "origin", "https://example.com/x.git"], cwd=repo, check=True)
    platform = Platform()
    assert run(platform, ["git", "create"]) == EXIT_USAGE
    assert platform.requests == []
    assert "--remote" in capsys.readouterr().err


def test_create_reports_a_taken_name(run, repo, capsys):
    assert run(Platform(), ["git", "create", "taken"]) == EXIT_ERROR
    assert "already exists" in capsys.readouterr().err
    assert git_module.remote_url(repo, "origin") is None


def test_create_outside_a_repository_needs_a_name(run, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert run(Platform(), ["git", "create"]) == EXIT_USAGE
    assert run(Platform(), ["git", "create", "loose"]) == EXIT_OK
    assert capsys.readouterr().out.strip().endswith("https://github.com/alice/loose")


def test_setup_on_dev_names_the_environment(run, repo):
    assert run(Platform(), ["--env", "dev", "git", "setup"]) == EXIT_OK
    assert git_config(repo, "--local", "--get-all", git_module.HELPER_KEY) == (
        "\n!freepod --env dev git credential\n"
    )


def test_setup_replaces_earlier_helpers(run, repo):
    subprocess.run(["git", "config", "--local", git_module.HELPER_KEY, "store"], cwd=repo, check=True)
    run(Platform(), ["git", "setup"])
    run(Platform(), ["git", "setup"])
    assert git_config(repo, "--local", "--get-all", git_module.HELPER_KEY) == "\n!freepod git credential\n"


def test_setup_globally(run, repo, isolated_home):
    assert run(Platform(), ["git", "setup", "--global"]) == EXIT_OK
    assert "!freepod git credential" in (isolated_home / ".gitconfig").read_text()


def test_setup_outside_a_repository_needs_global(run, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert run(Platform(), ["git", "setup"]) == EXIT_USAGE


# --- link and unlink -------------------------------------------------------


def test_link_takes_the_origin_branch_and_directory(run, project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    platform = Platform()
    assert run(platform, ["git", "link"]) == EXIT_OK
    assert platform.bodies(f"/api/users/7/deployments/{DEPLOYMENT}/source") == [
        {"repository": "alice/recipes", "root_dir": "web", "branch": "main"}
    ]
    captured = capsys.readouterr()
    assert captured.out == "https://github.com/alice/recipes\n"
    assert "alice/recipes (branch main, in web)" in captured.err


def test_link_to_another_repository_assumes_nothing_from_this_one(run, project, monkeypatch):
    monkeypatch.chdir(project)
    platform = Platform()
    run(platform, ["git", "link", "acme/site"])
    assert platform.bodies(f"/api/users/7/deployments/{DEPLOYMENT}/source") == [
        {"repository": "acme/site", "root_dir": ""}
    ]


def test_link_with_a_branch_and_path(run, project, monkeypatch):
    monkeypatch.chdir(project)
    platform = Platform()
    run(platform, ["git", "link", "--branch", "release", "--path", "apps/web"])
    assert platform.bodies(f"/api/users/7/deployments/{DEPLOYMENT}/source") == [
        {"repository": "alice/recipes", "root_dir": "apps/web", "branch": "release"}
    ]


def test_link_without_a_github_origin_offers_a_pick(run, project, repo, monkeypatch):
    subprocess.run(["git", "remote", "remove", "origin"], cwd=repo, check=True)
    monkeypatch.chdir(project)
    picked = []

    def pick(found):
        picked.append([r["full_name"] for r in found])
        return found[1]

    monkeypatch.setattr("freepod.git.pick_repository", pick)

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    platform = Platform()
    from freepod.api import ApiClient

    monkeypatch.setattr("freepod.cli.Context.session", lambda self, force_flow=None: _StubSession())
    monkeypatch.setattr(
        "freepod.cli.Context.client",
        lambda self, session: ApiClient(self.env, session, client=httpx.Client(transport=httpx.MockTransport(platform)), backoff_base=0),
    )
    monkeypatch.setattr("freepod.cli.sys.stdin", Terminal(""))
    assert main(["git", "link"]) == EXIT_OK
    assert picked == [["alice/recipes", "acme/site"]]
    assert platform.bodies(f"/api/users/7/deployments/{DEPLOYMENT}/source") == [
        {"repository": "acme/site", "root_dir": ""}
    ]


def test_link_without_an_origin_or_a_terminal_asks_for_the_name(run, project, repo, monkeypatch, capsys):
    subprocess.run(["git", "remote", "remove", "origin"], cwd=repo, check=True)
    monkeypatch.chdir(project)
    assert run(Platform(), ["git", "link"]) == EXIT_USAGE
    assert "OWNER/NAME" in capsys.readouterr().err


def test_link_needs_a_project(run, repo, capsys):
    platform = Platform()
    assert run(platform, ["git", "link", "alice/recipes"]) == EXIT_USAGE
    assert platform.requests == []


def test_link_reports_the_platforms_refusal(run, project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    platform = Platform()
    platform.refuse_link = True
    assert run(platform, ["git", "link"]) == EXIT_ERROR
    assert "does not exist" in capsys.readouterr().err


def test_unlink(run, project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    platform = Platform()
    run(platform, ["git", "link"])
    assert run(platform, ["git", "unlink"]) == EXIT_OK
    assert "no longer linked" in capsys.readouterr().err
    assert run(platform, ["git", "unlink"]) == EXIT_OK
    assert "was not linked" in capsys.readouterr().err


def test_status_shows_this_projects_link(run, project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    platform = Platform()
    run(platform, ["git", "status"])
    assert "this project: not linked" in capsys.readouterr().out
    run(platform, ["git", "link"])
    capsys.readouterr()
    run(platform, ["git", "status"])
    assert "this project: alice/recipes (branch main, in web)" in capsys.readouterr().out


def test_create_links_this_projects_deployment(run, repo, monkeypatch, capsys):
    from freepod.project import Project

    Project(repo, deployment_id=DEPLOYMENT).save()
    platform = Platform()
    assert run(platform, ["git", "create"]) == EXIT_OK
    assert platform.bodies(f"/api/users/7/deployments/{DEPLOYMENT}/source") == [
        {"repository": "alice/recipes", "root_dir": "", "branch": "main"}
    ]
    assert "linked to alice/recipes (branch main)" in capsys.readouterr().err


def test_create_survives_a_refused_link(run, repo, capsys):
    from freepod.project import Project

    Project(repo, deployment_id=DEPLOYMENT).save()
    platform = Platform()
    platform.refuse_link = True
    assert run(platform, ["git", "create"]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == "https://github.com/alice/recipes\n"
    assert "Could not link" in captured.err
    assert git_module.remote_url(repo, "origin") == "https://github.com/alice/recipes.git"
