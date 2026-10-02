"""The `.freepod.json` project file: load, save, and project-root discovery.

The file holds intent — the deployment pointer, the user values, and, for a
project on a non-default environment, that environment — and nothing a deploy
would rewrite. In particular the build's `image`
is never written to it: it is a build output, not intent, and persisting it
would mean a rewritten committed file on every deploy, which is git churn and a
merge conflict for any team of two. See design D4.

```json
{
  "version": 1,
  "deployment": {"id": "40bd8dea-…", "name": "custom-d8dtx4"},
  "user_values": {"hostname": "myapp.freepod.eu"}
}
```

Before the first deploy, `deployment` is `null`. An absent `env` means
`DEFAULT_ENV`; it is written only for a project on another environment.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from . import FreepodError, UsageError

PROJECT_FILE = ".freepod.json"

#: The environment a project file with no `env` belongs to. Defined here rather
#: than in `config`, which imports this module.
DEFAULT_ENV = "prod"

#: Bumped when the on-disk format changes incompatibly.
FORMAT_VERSION = 1

#: Keys a deploy produces rather than a user declaring. Stripped on write.
#:
#: `image` is not merely omitted when absent — it is removed even if a caller
#: passes one, because the platform's schema declares it `type: "string"` under
#: `additionalProperties: false`, so neither a value nor an explicit null
#: belongs in a file that is committed and diffed.
BUILD_OUTPUT_KEYS = frozenset({"image"})


class Project:
    """One project's file, and the directory it was found in."""

    def __init__(
        self,
        root: Path,
        env: Optional[str] = None,
        user_values: Optional[Dict[str, Any]] = None,
        deployment: Optional[Dict[str, str]] = None,
        version: int = FORMAT_VERSION,
    ):
        self.root = Path(root)
        # As declared in the file: None is written as no key at all.
        self.declared_env = env
        self.user_values = dict(user_values or {})
        self.deployment = dict(deployment) if deployment else None
        self.version = version

    @property
    def env(self) -> str:
        return self.declared_env or DEFAULT_ENV

    @env.setter
    def env(self, name: str) -> None:
        self.declared_env = name

    # -- location ---------------------------------------------------------

    @property
    def path(self) -> Path:
        return self.root / PROJECT_FILE

    @property
    def deployment_id(self) -> Optional[str]:
        return self.deployment.get("id") if self.deployment else None

    @property
    def deployment_name(self) -> Optional[str]:
        return self.deployment.get("name") if self.deployment else None

    @property
    def hostname(self) -> Optional[str]:
        value = self.user_values.get("hostname")
        return value if isinstance(value, str) else None

    # -- persistence ------------------------------------------------------

    def to_document(self) -> Dict[str, Any]:
        values = {k: v for k, v in self.user_values.items() if k not in BUILD_OUTPUT_KEYS}
        document: Dict[str, Any] = {"version": self.version}
        if self.declared_env is not None:
            document["env"] = self.declared_env
        document["deployment"] = dict(self.deployment) if self.deployment else None
        document["user_values"] = values
        return document

    def save(self) -> None:
        """Write the file, atomically, with a trailing newline.

        Atomic-replace so an interrupted write cannot truncate a file that
        carries the only pointer to a live deployment.
        """
        document = self.to_document()
        temporary = self.path.with_name(f"{PROJECT_FILE}.{os.getpid()}.tmp")
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2)
                handle.write("\n")
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def record_deployment(self, deployment_id: str, name: str) -> None:
        """Pin the deployment pointer and persist it immediately.

        Written before the rollout is awaited: a deployment that exists but is
        not recorded is one the user cannot see, address, or delete.
        """
        self.deployment = {"id": str(deployment_id), "name": name}
        self.save()

    def forget_deployment(self) -> None:
        """Drop the deployment pointer and persist it immediately.

        The counterpart of `record_deployment`, and written the moment the
        platform accepts a deletion rather than once the teardown lands: from
        that point the deployment can never serve this project again, so a
        pointer to it would only make the next deploy fail. Everything else in
        the file — the environment, the user values — is intent and survives,
        so a later `freepod deploy` re-creates under the same hostname.
        """
        self.deployment = None
        self.save()


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def find_project_root(start: Optional[Path] = None) -> Optional[Path]:
    """The nearest ancestor of `start` containing `.freepod.json`, git-style."""
    current = Path(start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        if (directory / PROJECT_FILE).is_file():
            return directory
    return None


def load(root: Path) -> Project:
    """Read the project file in `root`."""
    path = Path(root) / PROJECT_FILE
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise FreepodError(f"cannot read {path}: {exc}") from None
    except ValueError as exc:
        raise FreepodError(f"{path} is not valid JSON: {exc}") from None

    if not isinstance(document, dict):
        raise FreepodError(f"{path} must contain a JSON object")

    version = document.get("version", FORMAT_VERSION)
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise FreepodError(
            f"{path} declares format version {version!r}, which this client does not "
            f"understand (it supports up to {FORMAT_VERSION}) — upgrade freepod"
        )

    env = document.get("env")
    if env is not None and (not isinstance(env, str) or not env):
        raise FreepodError(f"{path}: 'env' must be a non-empty string")

    user_values = document.get("user_values")
    if user_values is None:
        user_values = {}
    if not isinstance(user_values, dict):
        raise FreepodError(f"{path}: 'user_values' must be an object")

    deployment = document.get("deployment")
    if deployment is not None:
        if not isinstance(deployment, dict) or not deployment.get("id"):
            raise FreepodError(f"{path}: 'deployment' must be null or carry an 'id'")

    return Project(
        root=Path(root),
        env=env,
        user_values=user_values,
        deployment=deployment,
        version=version,
    )


def require_project(start: Optional[Path] = None) -> Project:
    """Find and load the project, refusing a directory that has none.

    The environment the file declares is not checked here: it is the default
    target of every command run from this directory, and an explicit `--env`
    that disagrees with it is reconciled by the caller, which alone knows what
    it is about to do with the recorded deployment.
    """
    root = find_project_root(start)
    if root is None:
        where = Path(start or Path.cwd()).resolve()
        raise UsageError(
            f"no {PROJECT_FILE} found in {where} or any parent directory — "
            f"this project is not initialized. Run `freepod init` to set it up."
        )
    return load(root)
