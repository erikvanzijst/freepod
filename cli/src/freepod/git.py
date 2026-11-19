"""`freepod git`: the account's GitHub connection, the repositories it creates,
and git's credential helper.

GitHub credentials stay on the platform. When git talks to github.com it asks
the helper for a password, and the helper asks the platform for a token that
reaches one repository for an hour.
"""

from __future__ import annotations

import re
import subprocess
import time
from calendar import timegm
from pathlib import Path
from typing import Any, Dict, IO, List, Optional
from urllib.parse import quote

from . import FreepodError, PermissionError_, UsageError
from .api import ApiClient, _json_code, _json_detail
from .config import Environment
from .project import DEFAULT_ENV

HOST = "github.com"
CONNECT_PATH = "/settings/git?connect=github"
POLL_SECONDS = 3
HELPER_KEY = f"credential.https://{HOST}.helper"
HTTP_PATH_KEY = f"credential.https://{HOST}.useHttpPath"
REPOSITORY = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")

NOT_CONNECTED = "this account is not connected to GitHub. Run `freepod git connect`."


def connect_url(env: Environment) -> str:
    """Signs the browser in to Freepod first, then the Settings page starts GitHub's."""
    return f"{env.api_base}/oauth2/start?rd={quote(CONNECT_PATH, safe='')}"


def _refusal(response: Any) -> FreepodError:
    if _json_code(response) == "git_not_connected":
        return FreepodError(NOT_CONNECTED)
    detail = _json_detail(response) or response.text.strip()[:300]
    return FreepodError(detail)


def connections(api: ApiClient, user_id: Any) -> List[Dict[str, Any]]:
    return api.get_json(f"/api/users/{user_id}/git")


def github(api: ApiClient, user_id: Any) -> Optional[Dict[str, Any]]:
    return next((c for c in connections(api, user_id) if c.get("provider") == "github"), None)


def installations(api: ApiClient, user_id: Any) -> List[Dict[str, Any]]:
    response = api.get(f"/api/users/{user_id}/git/github/installations")
    if not response.is_success:
        raise _refusal(response)
    return response.json()


def wait_for_connection(
    api: ApiClient,
    user_id: Any,
    timeout: float,
) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        found = github(api, user_id)
        if found is not None:
            return found
        if time.monotonic() >= deadline:
            raise FreepodError(
                "gave up waiting for GitHub to be connected. Run `freepod git connect` again."
            )
        time.sleep(POLL_SECONDS)


def create(
    api: ApiClient,
    user_id: Any,
    *,
    name: str,
    owner: Optional[str],
    private: bool,
    description: Optional[str],
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"name": name, "private": private}
    if owner:
        body["owner"] = owner
    if description:
        body["description"] = description
    response = api.post(f"/api/users/{user_id}/git/github/repositories", json=body)
    if response.status_code != 201:
        raise _refusal(response)
    return response.json()


def credential(api: ApiClient, user_id: Any, repository: str) -> Dict[str, Any]:
    """Write access when the user has it, read access otherwise."""
    path = f"/api/users/{user_id}/git/github/credentials"
    try:
        response = api.post(path, json={"repository": repository, "access": "write"})
    except PermissionError_:
        response = api.post(path, json={"repository": repository, "access": "read"})
    if not response.is_success:
        raise _refusal(response)
    return response.json()


# --------------------------------------------------------------------------
# git's credential helper protocol
# --------------------------------------------------------------------------


def read_request(stream: IO[str]) -> Dict[str, str]:
    """Attributes git sends, one `key=value` per line, ended by a blank line."""
    request: Dict[str, str] = {}
    for line in stream:
        line = line.rstrip("\n")
        if not line:
            break
        key, _, value = line.partition("=")
        request[key] = value
    return request


def repository_of(request: Dict[str, str]) -> Optional[str]:
    """`owner/name` from the request's path, which git sends only with useHttpPath."""
    path = request.get("path", "").strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    return path if REPOSITORY.match(path) else None


def format_response(issued: Dict[str, Any]) -> str:
    lines = [f"username={issued['username']}", f"password={issued['password']}"]
    expiry = _epoch(issued.get("expires_at"))
    if expiry is not None:
        lines.append(f"password_expiry_utc={expiry}")
    return "\n".join(lines) + "\n"


def _epoch(value: Any) -> Optional[int]:
    if not isinstance(value, str):
        return None
    try:
        return timegm(time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


# --------------------------------------------------------------------------
# The local repository
# --------------------------------------------------------------------------


def _git(*args: str, cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        raise FreepodError("git is not installed") from None
    if check and result.returncode != 0:
        raise FreepodError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def repository_root(cwd: Optional[Path] = None) -> Optional[Path]:
    result = _git("rev-parse", "--show-toplevel", cwd=cwd, check=False)
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def remote_url(root: Path, remote: str) -> Optional[str]:
    result = _git("remote", "get-url", remote, cwd=root, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def add_remote(root: Path, remote: str, url: str) -> None:
    _git("remote", "add", remote, url, cwd=root)


def current_branch(root: Path) -> Optional[str]:
    result = _git("symbolic-ref", "--quiet", "--short", "HEAD", cwd=root, check=False)
    return result.stdout.strip() or None if result.returncode == 0 else None


def helper_command(env: Environment) -> str:
    """The helper as git runs it, naming the environment unless it is the default."""
    flag = "" if env.name == DEFAULT_ENV else f" --env {env.name}"
    return f"!freepod{flag} git credential"


def configure(env: Environment, *, root: Optional[Path], everywhere: bool) -> str:
    """Point git at the helper for github.com, in one repository or for the user.

    The empty value first clears helpers configured before this one for the
    same URL, so a stored password cannot answer instead.
    """
    if not everywhere and root is None:
        raise UsageError("not inside a git repository; run it in one, or pass --global")
    scope = "--global" if everywhere else "--local"
    _git("config", scope, "--unset-all", HELPER_KEY, cwd=root, check=False)
    _git("config", scope, "--add", HELPER_KEY, "", cwd=root)
    _git("config", scope, "--add", HELPER_KEY, helper_command(env), cwd=root)
    _git("config", scope, HTTP_PATH_KEY, "true", cwd=root)
    return "every repository" if everywhere else str(root)


# --------------------------------------------------------------------------
# The repository a deployment is built from
# --------------------------------------------------------------------------

_REMOTE = re.compile(
    r"^(?:https://(?:[^@/]+@)?github\.com/|ssh://git@github\.com/|git@github\.com:)"
    r"(?P<repo>[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$"
)


def github_repository(url: Optional[str]) -> Optional[str]:
    """`owner/name` of a github.com remote URL, or None for anything else."""
    if not url:
        return None
    match = _REMOTE.match(url.strip())
    return match.group("repo") if match else None


def project_path(project_root: Path, git_root: Path) -> str:
    """Where the project sits in its repository, as `dir/sub`; "" at the root."""
    relative = project_root.resolve().relative_to(git_root.resolve())
    return "" if str(relative) == "." else relative.as_posix()


def source(api: ApiClient, user_id: Any, deployment_id: str) -> Optional[Dict[str, Any]]:
    response = api.get(f"/api/users/{user_id}/deployments/{deployment_id}/source")
    if response.status_code == 404 and _json_code(response) == "source_not_linked":
        return None
    if not response.is_success:
        raise _refusal(response)
    return response.json()


def link(
    api: ApiClient,
    user_id: Any,
    deployment_id: str,
    *,
    repository: str,
    branch: Optional[str],
    root_dir: str,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"repository": repository, "root_dir": root_dir}
    if branch:
        body["branch"] = branch
    response = api.put(f"/api/users/{user_id}/deployments/{deployment_id}/source", json=body)
    if not response.is_success:
        raise _refusal(response)
    return response.json()


def unlink(api: ApiClient, user_id: Any, deployment_id: str) -> bool:
    """False when there was no link to remove."""
    response = api.delete(f"/api/users/{user_id}/deployments/{deployment_id}/source")
    if response.status_code == 404 and _json_code(response) == "source_not_linked":
        return False
    if not response.is_success:
        raise _refusal(response)
    return True


def repositories(api: ApiClient, user_id: Any) -> List[Dict[str, Any]]:
    response = api.get(f"/api/users/{user_id}/git/github/repositories")
    if not response.is_success:
        raise _refusal(response)
    return response.json()


def describe(linked: Dict[str, Any]) -> str:
    where = f", in {linked['root_dir']}" if linked.get("root_dir") else ""
    return f"{linked['full_name']} (branch {linked['branch']}{where})"


def pick_repository(
    found: List[Dict[str, Any]], *, input: Any = None, output: Any = None
) -> Optional[Dict[str, Any]]:
    from .picker import pick

    width = max(len(r["full_name"]) for r in found)
    labels = [
        f"{r['full_name'].ljust(width)}  {'private' if r.get('private') else 'public'}"
        for r in found
    ]
    return pick(
        found,
        labels,
        title="Link to which repository? Type to narrow, ↑↓ to move, Enter to pick.",
        empty="no repository matches",
        input=input,
        output=output,
    )
