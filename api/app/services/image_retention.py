"""Which of a tenant's registry images the platform keeps.

The rule is computed from the release ledger every time it is asked, never
stored (tenant-image-retention spec). The prune and the deployment write
check both go through `_retentions`, so they cannot disagree. Rationale:
tenant-image-retention design D1-D3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from itertools import groupby
from typing import Any, Iterable, Iterator
from uuid import UUID

from sqlalchemy import TextClause, bindparam, text
from sqlmodel import Session

from app.config import CaelusSettings
from app.services.build_constants import BUILD_STATUS_SUCCEEDED, BUILD_STATUSES_OPEN

APPLIED = "applied"
DESIRED = "desired"
EARLIER = "earlier"
FRESH = "fresh build"
_RANK = {APPLIED: 3, DESIRED: 2, EARLIER: 1, FRESH: 0}

_RELEASE, _BUILD = 0, 1

# Releases and builds in one stream, grouped by owner. Within a deployment the
# applied and desired releases come first, so the walk knows which images are
# current before it counts earlier ones; then the rest, newest first. Values
# are matched in Python: SQL only narrows, through the indexes (design D1).
_STREAM = """
select owner, kind, deployment_id, current, values_json, build_id, status, image, finished_at
from (
    select d.user_id as owner, {release} as kind, d.id as deployment_id,
           case when r.id = d.applied_release_id then 2
                when r.id = d.desired_release_id then 1 else 0 end as current,
           r.number, r.values_json,
           null::uuid as build_id, null::varchar as status, null::varchar as image,
           null::timestamp as finished_at
    from deployment d join deployment_release r on r.deployment_id = d.id
    where d.deleted_at is null and d.user_id in :owners
    union all
    select d.user_id, {build}, null, null, null, null, b.id, b.status, b.image, b.finished_at
    from build b join deployment d on d.id = b.deployment_id
    where d.user_id in :owners {fresh_only}
) stream
order by owner, kind, deployment_id, current desc, number desc
"""
_FRESH_ONLY = "and (b.status in :open or (b.status = :succeeded and b.finished_at >= :since))"


def _statement(fresh_only: bool) -> TextClause:
    sql = _STREAM.format(release=_RELEASE, build=_BUILD, fresh_only=_FRESH_ONLY if fresh_only else "")
    stmt = text(sql).bindparams(bindparam("owners", expanding=True))
    if fresh_only:
        stmt = stmt.bindparams(bindparam("open", expanding=True))
    return stmt


_ALL_BUILDS, _FRESH_BUILDS = _statement(False), _statement(True)


@dataclass(frozen=True)
class Retention:
    """One owner's retained images, each with the reason it is retained; the
    builds whose tags are kept whatever they point at (design D3); and the
    image each of the owner's builds recorded, keyed by its tag."""

    images: dict[str, str] = field(default_factory=dict)
    fresh_builds: frozenset[UUID] = frozenset()
    build_images: dict[str, str] = field(default_factory=dict)

    def retains(self, image: str) -> bool:
        return image in self.images


@lru_cache(maxsize=4096)
def _owner_image(owner: str) -> re.Pattern[str]:
    return re.compile(re.escape(owner) + r"@sha256:[a-f0-9]{64}")


def owner_images(owner: int | str, values: Any) -> set[str]:
    """Every reference to the owner's own image repository among `values`."""
    pattern = _owner_image(str(owner))
    return {s for s in _strings(values) if pattern.fullmatch(s)}


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)
    elif isinstance(value, str):
        yield value


def _label(images: dict[str, str], image: str, reason: str) -> None:
    """Record the strongest reason an image is retained."""
    if _RANK[reason] > _RANK.get(images.get(image, ""), -1):
        images[image] = reason


def _is_fresh(row: Any, since: datetime) -> bool:
    if row.status in BUILD_STATUSES_OPEN:
        return True
    return row.status == BUILD_STATUS_SUCCEEDED and row.finished_at is not None and row.finished_at >= since


def _grace_start(settings: CaelusSettings, now: datetime | None) -> datetime:
    moment = (now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)
    return moment - timedelta(hours=settings.registry_prune_grace_hours)


def is_fresh(build: Any, settings: CaelusSettings, *, now: datetime | None = None) -> bool:
    return _is_fresh(build, _grace_start(settings, now))


def _retention(owner: Any, rows: Iterable[Any], past: int, since: datetime) -> Retention:
    images: dict[str, str] = {}
    fresh: set[UUID] = set()
    build_images: dict[str, str] = {}
    for (kind, _), group in groupby(rows, key=lambda r: (r.kind, r.deployment_id)):
        if kind == _BUILD:
            for row in group:
                if row.image:
                    build_images[str(row.build_id)] = row.image
                if _is_fresh(row, since):
                    fresh.add(row.build_id)
                    if row.image:
                        _label(images, row.image, FRESH)
            continue
        current: set[str] = set()
        earlier: list[str] = []
        for row in group:
            if row.current:
                for image in owner_images(owner, row.values_json):
                    current.add(image)
                    _label(images, image, APPLIED if row.current == 2 else DESIRED)
                continue
            if len(earlier) >= past:
                continue  # the rest of the group is never matched
            for image in sorted(owner_images(owner, row.values_json)):
                if image not in current and image not in earlier and len(earlier) < past:
                    earlier.append(image)
        for image in earlier:
            _label(images, image, EARLIER)
    return Retention(images=images, fresh_builds=frozenset(fresh), build_images=build_images)


def _retentions(
    session: Session,
    owners: list[Any],
    settings: CaelusSettings,
    *,
    fresh_only: bool,
    now: datetime | None,
) -> Iterator[tuple[Any, Retention]]:
    if not owners:
        return
    since = _grace_start(settings, now)
    params: dict[str, Any] = {"owners": owners}
    if fresh_only:
        params |= {"open": list(BUILD_STATUSES_OPEN), "succeeded": BUILD_STATUS_SUCCEEDED, "since": since}
    stmt = _FRESH_BUILDS if fresh_only else _ALL_BUILDS
    rows = session.execute(stmt.execution_options(yield_per=500), params)
    past = settings.registry_retained_past_images
    for owner, group in groupby(rows, key=lambda r: r.owner):
        yield owner, _retention(owner, group, past, since)


def owner_retention(
    session: Session,
    owner_id: int,
    settings: CaelusSettings,
    *,
    now: datetime | None = None,
) -> Retention:
    """One owner's retention, in a single query: what a deployment write checks."""
    for _, retention in _retentions(session, [owner_id], settings, fresh_only=True, now=now):
        return retention
    return Retention()


def retentions(
    session: Session,
    owners: list[Any],
    settings: CaelusSettings,
    *,
    now: datetime | None = None,
) -> Iterator[tuple[Any, Retention]]:
    """Every named owner's retention, streamed in one query, with every build's
    recorded image so the prune can judge build tags without the registry."""
    yield from _retentions(session, owners, settings, fresh_only=False, now=now)
