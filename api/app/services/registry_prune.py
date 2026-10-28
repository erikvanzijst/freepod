"""Untag every image retention no longer keeps, ahead of registry collection.

Every owner's tags are listed first, then retention is read in one stream,
then tags are removed. Leaving retention is permanent, so a database read
taken after the registry read can only keep more than was real when the tags
were listed (design D4). A tag named after a build is judged by the image
that build recorded, since a build tag never moves; only a tag naming no
known image costs a request for its digest. Tags are removed one at a time
and never by digest, so an image goes only when its last tag does (D5).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Protocol
from uuid import UUID

import httpx
from sqlmodel import Session, col, select

from app.config import CaelusSettings
from app.models import BuildORM, DeploymentORM
from app.services import image_retention, registry_tokens
from app.services.image_retention import Retention

logger = logging.getLogger(__name__)

TOKEN_TTL_SECONDS = 900
TAGS_PAGE_SIZE = 1000

_MANIFEST_TYPES = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


class Registry(Protocol):
    def tags(self, repository: str) -> Iterator[str]: ...
    def digest(self, repository: str, tag: str) -> str: ...
    def delete_tag(self, repository: str, tag: str) -> None: ...


class HttpRegistry:
    """The registry's HTTP API, authorized for one owner's repository at a time."""

    def __init__(self, settings: CaelusSettings, *, client: httpx.Client | None = None):
        self._settings = settings
        self._client = client or httpx.Client(timeout=30)
        self._base = f"https://{settings.registry_host}"
        self._token: tuple[str, str] | None = None

    def _auth(self, repository: str) -> dict[str, str]:
        if self._token is None or self._token[0] != repository:
            owner = repository.removeprefix(f"{registry_tokens.IMAGE_REPOSITORY_PREFIX}/")
            issued = registry_tokens.prune_token(
                self._settings, [owner], ttl_seconds=TOKEN_TTL_SECONDS
            )
            self._token = (repository, issued.token)
        return {"Authorization": f"Bearer {self._token[1]}"}

    def tags(self, repository: str) -> Iterator[str]:
        url: str | None = f"{self._base}/v2/{repository}/tags/list?n={TAGS_PAGE_SIZE}"
        while url:
            resp = self._client.get(url, headers=self._auth(repository))
            if resp.status_code == 404:
                return
            resp.raise_for_status()
            yield from resp.json().get("tags") or []
            link = resp.links.get("next", {}).get("url")
            url = f"{self._base}{link}" if link and link.startswith("/") else link

    def digest(self, repository: str, tag: str) -> str:
        resp = self._client.head(
            f"{self._base}/v2/{repository}/manifests/{tag}",
            headers={**self._auth(repository), "Accept": _MANIFEST_TYPES},
        )
        resp.raise_for_status()
        return resp.headers["docker-content-digest"]

    def delete_tag(self, repository: str, tag: str) -> None:
        resp = self._client.delete(
            f"{self._base}/v2/{repository}/manifests/{tag}", headers=self._auth(repository)
        )
        resp.raise_for_status()


@dataclass
class OwnerReport:
    owner: Any
    kept: dict[str, str] = field(default_factory=dict)  # tag -> reason
    removed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        reasons: dict[str, int] = {}
        for reason in self.kept.values():
            reasons[reason] = reasons.get(reason, 0) + 1
        return {
            "owner": self.owner,
            "kept": reasons,
            "removed": self.removed,
            "failed": self.failed,
        }


def _build_id(tag: str) -> UUID | None:
    try:
        return UUID(tag)
    except ValueError:
        return None


def prune_owner(
    registry: Registry,
    owner: Any,
    tags: Iterable[str],
    retention: Retention,
    *,
    dry_run: bool,
) -> OwnerReport:
    report = OwnerReport(owner=owner)
    repository = registry_tokens.image_repository(owner)
    for tag in tags:
        if _build_id(tag) in retention.fresh_builds:
            report.kept[tag] = image_retention.FRESH
            continue
        image = retention.build_images.get(tag)
        if image is None:
            try:
                image = f"{owner}@{registry.digest(repository, tag)}"
            except httpx.HTTPError as exc:
                # Unresolved, so not judged: keeping is always safe.
                logger.warning("Could not resolve %s:%s: %s", repository, tag, exc)
                report.failed.append(tag)
                continue
        if (reason := retention.images.get(image)) is not None:
            report.kept[tag] = reason
            continue
        if not dry_run:
            try:
                registry.delete_tag(repository, tag)
            except httpx.HTTPError as exc:
                logger.warning("Could not remove %s:%s: %s", repository, tag, exc)
                report.failed.append(tag)
                continue
        report.removed.append(tag)
    return report


def owners_with_builds(session: Session) -> list[Any]:
    return list(
        session.exec(
            select(DeploymentORM.user_id)
            .join(BuildORM, col(BuildORM.deployment_id) == col(DeploymentORM.id))
            .distinct()
            .order_by(DeploymentORM.user_id)
        ).all()
    )


def prune(
    session: Session,
    registry: Registry,
    settings: CaelusSettings,
    *,
    dry_run: bool,
    owners: list[Any] | None = None,
) -> Iterator[OwnerReport]:
    owners = owners if owners is not None else owners_with_builds(session)
    # The registry first, for every owner, then the ledger (D4). Only tag
    # names are held across the barrier.
    listed: dict[Any, list[str]] = {}
    for owner in owners:
        try:
            listed[owner] = list(registry.tags(registry_tokens.image_repository(owner)))
        except httpx.HTTPError as exc:
            logger.warning("Could not list owner %s: %s", owner, exc)
            yield OwnerReport(owner=owner, failed=["*"])
    # Read committed takes each statement's snapshot when it runs; ending the
    # transaction keeps that true under any isolation level.
    session.rollback()
    for owner, retention in image_retention.retentions(session, list(listed), settings):
        yield prune_owner(registry, owner, listed.pop(owner), retention, dry_run=dry_run)
    # Owners the stream did not mention have no live release and no build.
    for owner, tags in listed.items():
        yield prune_owner(registry, owner, tags, Retention(), dry_run=dry_run)
