"""The `.freepod.json` project file: load, save, and project-root discovery.

The file holds intent: the deployment pointer, the fields the project manages,
and, for a project on a non-default environment, that environment. Nothing a
deploy produces is written to it; the build's `image` in particular is a build
output, and a file that holds one is refused.

```json
{
  "$schema": "https://freepod.eu/api/products/custom/project-schema",
  "version": 2,
  "deployment": "40bd8dea-…",
  "name": "Arkanoid",
  "auth": {"enabled": true}
}
```

Every key other than `$schema`, `version`, `env` and `deployment` is a
deployment field the file manages: an identity key (`name`, `description`,
`icon`) or a chart property. An unlinked project has no `deployment` key.
Format 1 files are migrated on read (design D8).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import click

from . import FreepodError, UsageError

PROJECT_FILE = ".freepod.json"

#: The environment a project file with no `env` belongs to. Defined here rather
#: than in `config`, which imports this module.
DEFAULT_ENV = "prod"

#: Bumped when the on-disk format changes incompatibly.
FORMAT_VERSION = 2

#: The file's own keys; everything else is a field it manages.
FILE_KEYS = ("$schema", "version", "env", "deployment")

#: The deployment's own metadata, as opposed to its chart properties.
IDENTITY_KEYS = ("name", "description", "icon")

#: Keys a deploy produces rather than a user declaring.
BUILD_OUTPUT_KEYS = frozenset({"image"})

#: The product a project file describes, whose schema `$schema` names.
SCHEMA_PRODUCT = "custom"

#: The hostnames earlier releases of this client wrote, `<label>.<account>.freepod.eu`
#: and `<label>.<account>.dev.freepod.eu`. Fixed here rather than learned from
#: the platform: the rewrite only corrects this client's own earlier output.
_LEGACY_HOSTNAME = re.compile(
    r"^(?P<label>[a-z0-9-]+)\.(?:(?!dev\.)[a-z0-9-]+\.freepod\.eu|[a-z0-9-]+\.dev\.freepod\.eu)$"
)


def schema_url(api_base: str) -> str:
    """The project schema on the environment at `api_base`."""
    return f"{api_base.rstrip('/')}/api/products/{SCHEMA_PRODUCT}/project-schema"


class Project:
    """One project's file, and the directory it was found in."""

    def __init__(
        self,
        root: Path,
        env: Optional[str] = None,
        fields: Optional[Dict[str, Any]] = None,
        deployment_id: Optional[str] = None,
        schema: Optional[str] = None,
    ):
        self.root = Path(root)
        # As declared in the file: None is written as no key at all.
        self.declared_env = env
        self.fields: Dict[str, Any] = dict(fields or {})
        self.deployment_id = str(deployment_id) if deployment_id else None
        self.schema = schema
        # A format 1 file whose `hostname` waits on the deployment's (D8).
        self.unsettled_hostname: Optional[str] = None

    @property
    def env(self) -> str:
        return self.declared_env or DEFAULT_ENV

    @env.setter
    def env(self, name: str) -> None:
        self.declared_env = name

    @property
    def path(self) -> Path:
        return self.root / PROJECT_FILE

    # -- fields -----------------------------------------------------------

    @property
    def identity(self) -> Dict[str, Any]:
        """The identity keys the file sets."""
        return {key: self.fields[key] for key in IDENTITY_KEYS if key in self.fields}

    @property
    def chart_values(self) -> Dict[str, Any]:
        """The chart properties the file sets."""
        return {k: v for k, v in self.fields.items() if k not in IDENTITY_KEYS}

    def set_chart_values(self, values: Dict[str, Any]) -> None:
        """Replace the chart properties, keeping the identity keys."""
        chart = {k: v for k, v in values.items() if k not in BUILD_OUTPUT_KEYS}
        self.fields = {**self.identity, **chart}

    @property
    def managed_fields(self) -> List[str]:
        """Every field the file sets, which is every field it manages."""
        return sorted(self.fields)

    @property
    def hostname(self) -> Optional[str]:
        value = self.fields.get("hostname")
        return value if isinstance(value, str) else None

    # -- persistence ------------------------------------------------------

    def to_document(self) -> Dict[str, Any]:
        document: Dict[str, Any] = {}
        if self.schema:
            document["$schema"] = self.schema
        document["version"] = FORMAT_VERSION
        if self.declared_env is not None:
            document["env"] = self.declared_env
        if self.deployment_id:
            document["deployment"] = self.deployment_id
        for key, value in self.fields.items():
            if key not in BUILD_OUTPUT_KEYS:
                document[key] = value
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
                json.dump(document, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def record_deployment(self, deployment_id: str, api_base: Optional[str] = None) -> None:
        """Pin the deployment pointer and persist it immediately.

        Written before the rollout is awaited: a deployment that exists but is
        not recorded is one the user cannot see, address, or delete. The
        schema follows the environment the pointer belongs to.
        """
        self.deployment_id = str(deployment_id)
        if api_base:
            self.schema = schema_url(api_base)
        self.save()

    def forget_deployment(self) -> None:
        """Drop the deployment pointer and persist it immediately.

        Written the moment the platform accepts a deletion: from then on the
        deployment can never serve this project again. Every other key is
        intent and survives, so `freepod init` re-creates with it.
        """
        self.deployment_id = None
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
    """Read the project file in `root`, migrating a format 1 file."""
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

    version = document.get("version", 1)
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise FreepodError(
            f"{path} declares format version {version!r}, which this client does not "
            f"understand (it supports up to {FORMAT_VERSION}) — upgrade freepod"
        )

    env = document.get("env")
    if env is not None and (not isinstance(env, str) or not env):
        raise FreepodError(f"{path}: 'env' must be a non-empty string")

    if version < FORMAT_VERSION:
        return _migrate(Path(root), document, env)

    if "deployment" in document:
        pointer = document["deployment"]
        if pointer is None:
            raise FreepodError(
                f"{path}: 'deployment' is null. Remove the key to leave the project "
                f"unlinked, or run `freepod link` to point it at a deployment."
            )
        if not isinstance(pointer, str) or not pointer:
            raise FreepodError(f"{path}: 'deployment' must be the deployment's id, as a string")

    schema = document.get("$schema")
    if schema is not None and not isinstance(schema, str):
        raise FreepodError(f"{path}: '$schema' must be a string")

    fields = {k: v for k, v in document.items() if k not in FILE_KEYS}
    if "user_values" in fields:
        raise FreepodError(
            f"{path}: 'user_values' belongs to format 1. In format 2 its keys sit at "
            f"the top level of the file."
        )
    outputs = sorted(BUILD_OUTPUT_KEYS & fields.keys())
    if outputs:
        raise FreepodError(
            f"{path}: '{outputs[0]}' is a build output, which freepod sets on every "
            f"deploy. Remove it from the file."
        )

    return Project(
        root=Path(root),
        env=env,
        fields=fields,
        deployment_id=document.get("deployment"),
        schema=schema,
    )


def _migrate(root: Path, document: Dict[str, Any], env: Optional[str]) -> Project:
    """Rewrite a format 1 file as format 2 (D8).

    The rewrite is saved at once unless the file is linked and sets `hostname`:
    that key is dropped only when it matches the deployment's, which needs a
    read, so it waits for `settle_migration`.
    """
    path = root / PROJECT_FILE
    pointer = document.get("deployment")
    if pointer is not None and (not isinstance(pointer, dict) or not pointer.get("id")):
        raise FreepodError(f"{path}: 'deployment' must be null or carry an 'id'")
    values = document.get("user_values") or {}
    if not isinstance(values, dict):
        raise FreepodError(f"{path}: 'user_values' must be an object")

    fields = {k: v for k, v in values.items() if k not in BUILD_OUTPUT_KEYS}
    hostname = fields.get("hostname")
    if isinstance(hostname, str):
        match = _LEGACY_HOSTNAME.match(hostname.strip().lower())
        if match is not None:
            fields["hostname"] = match.group("label")

    from .config import ENVIRONMENTS

    environment = ENVIRONMENTS.get(env or DEFAULT_ENV)
    project = Project(
        root=root,
        env=env,
        fields=fields,
        deployment_id=pointer["id"] if pointer else None,
        schema=schema_url(environment.api_base) if environment else None,
    )
    if project.deployment_id and "hostname" in fields:
        project.unsettled_hostname = fields["hostname"]
        return project
    project.save()
    if project.deployment_id:
        click.echo(f"Migrated {PROJECT_FILE} to format {FORMAT_VERSION}.", err=True)
    else:
        click.echo(
            f"Migrated {PROJECT_FILE} to format {FORMAT_VERSION}. It records no "
            f"deployment yet: run `freepod init` to create one.",
            err=True,
        )
    return project


def settle_migration(project: Project, deployment: Optional[Dict[str, Any]]) -> None:
    """Finish migrating a linked format 1 file, given its deployment as read.

    `hostname` is dropped when the deployment already has it, and kept as a
    managed field otherwise, so an edit never deployed is not lost.
    """
    hostname = project.unsettled_hostname
    if hostname is None:
        return
    project.unsettled_hostname = None
    if deployment is not None and _same_hostname(hostname, deployment):
        project.fields.pop("hostname", None)
    project.save()
    click.echo(f"Migrated {PROJECT_FILE} to format {FORMAT_VERSION}.", err=True)


def _same_hostname(value: str, deployment: Dict[str, Any]) -> bool:
    value = value.strip().lower()
    stored = (deployment.get("user_values_json") or {}).get("hostname")
    actual = (deployment.get("hostname") or "").lower()
    if value in (actual, (stored or "").lower()):
        return True
    # A label the platform completed beneath the owner's handle.
    first, _, _ = actual.partition(".")
    return "." not in value and first.rpartition("-")[0] == value


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
