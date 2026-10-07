"""Object storage bucket sizes, read from Prometheus, as a usage source.

The bucket size exporter beside each environment's Garage instance
(`daemons/bucket-exporter/`) publishes `caelus_bucket_bytes{bucket}` for every
deployment bucket, zeros included, and `caelus_bucket_exporter_buckets` for as long as
it runs. A window's byte-hours are a bucket's average over the window times the
window's length.

Attribution is the bucket's name, `dep-<deployment id>`, confirmed against the
`deployment` table by primary key a chunk at a time.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta
from decimal import Decimal
import logging
import re
from uuid import UUID

from sqlalchemy import text
from sqlmodel import Session

from app.config import CaelusSettings
from app.models.usage import SubjectKind
from app.services.usage.batching import batched
from app.services.usage.ledger import Observation
from app.services.usage.prometheus import PrometheusClient, PrometheusException
from app.services.usage.subjects import SubjectSpec

logger = logging.getLogger(__name__)

# Published by daemons/bucket-exporter.
SIZE_SERIES = "caelus_bucket_bytes"
LIVENESS_SERIES = "caelus_bucket_exporter_buckets"

SIZE_METRIC = "object_storage_byte_hours"

SECONDS_PER_HOUR = Decimal(3600)

_BUCKET_NAME = re.compile(
    r"dep-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)

# One chunk of measured sizes, kept to the deployments this environment's records hold
# and that were not deleted before the window ended. A primary-key join: it is both the
# deletion cutoff and the guard on `usage_subject.deployment_id`'s foreign key.
_KNOWN_BUCKETS = text(
    """
    SELECT u.bucket, u.deployment_id, u.size_bytes
    FROM unnest(CAST(:buckets AS text[]), CAST(:ids AS uuid[]),
                CAST(:sizes AS numeric[])) AS u(bucket, deployment_id, size_bytes)
    JOIN deployment d ON d.id = u.deployment_id
    WHERE d.deleted_at IS NULL OR d.deleted_at >= :window_end
    """
)


def deployment_id_of(bucket: str) -> UUID | None:
    """The deployment a bucket's name carries, or None for any other name."""
    match = _BUCKET_NAME.fullmatch(bucket)
    return UUID(match.group(1)) if match else None


class BucketSizeSource:
    """Deployment buckets on one environment's Garage instance."""

    name = "buckets"
    position_metrics = frozenset({SIZE_METRIC})

    def __init__(self, prometheus: PrometheusClient, *, namespace: str) -> None:
        if not namespace:
            # Unscoped, the other environment's exporter would vouch for this one.
            raise ValueError("the bucket exporter's namespace is required")
        self.prometheus = prometheus
        self.namespace = namespace

    @classmethod
    def from_settings(cls, settings: CaelusSettings) -> "BucketSizeSource":
        return cls(
            PrometheusClient(
                settings.prometheus_base_url,
                timeout_seconds=settings.opencost_timeout_seconds,
            ),
            namespace=settings.usage_bucket_namespace,
        )

    def covers(self, window_start: datetime, window_seconds: int) -> bool:
        """Whether this environment's exporter ran at any point in the window.

        Its bucket count, not any bucket's size: an environment with no buckets still
        has usable windows.
        """
        end = window_start + timedelta(seconds=window_seconds)
        return bool(
            self.prometheus.query(
                f'count(count_over_time({LIVENESS_SERIES}{{namespace="{self.namespace}"}}'
                f"[{window_seconds}s]))",
                end,
            )
        )

    def average_sizes(
        self, window_start: datetime, window_seconds: int
    ) -> Iterator[tuple[str, UUID, Decimal]]:
        """Every non-empty deployment bucket's average size over the window, in bytes.

        Averaged over every sample of the bucket rather than per series: an exporter
        restart mid-window publishes the same bucket from a new `instance`. A bucket
        measured for only part of the window is averaged over that part.
        """
        end = window_start + timedelta(seconds=window_seconds)
        selector = f'{SIZE_SERIES}{{namespace="{self.namespace}"}}[{window_seconds}s]'
        result = self.prometheus.query(
            f"sum by (bucket) (sum_over_time({selector}))"
            f" / sum by (bucket) (count_over_time({selector}))",
            end,
        )
        for series in result:
            bucket = series.get("metric", {}).get("bucket", "")
            deployment_id = deployment_id_of(bucket)
            size = Decimal(series["value"][1])
            if deployment_id is not None and size > 0:
                yield bucket, deployment_id, size

    def read(
        self, session: Session, window_start: datetime, *, window_seconds: int
    ) -> Iterator[Observation] | None:
        """None when the window is unusable; otherwise its observations, lazily."""
        try:
            if not self.covers(window_start, window_seconds):
                logger.warning(
                    "Window %s not recorded for buckets: the exporter in %s "
                    "published nothing over it",
                    window_start.isoformat(),
                    self.namespace,
                )
                return None
            sizes = list(self.average_sizes(window_start, window_seconds))
        except PrometheusException as exc:
            logger.warning(
                "Window %s not recorded for buckets: %s", window_start.isoformat(), exc
            )
            return None
        return self._observations(
            session,
            sizes,
            window_end=window_start + timedelta(seconds=window_seconds),
            hours=Decimal(window_seconds) / SECONDS_PER_HOUR,
        )

    def _observations(
        self,
        session: Session,
        sizes: Iterable[tuple[str, UUID, Decimal]],
        *,
        window_end: datetime,
        hours: Decimal,
    ) -> Iterator[Observation]:
        for chunk in batched(sizes):
            buckets, ids, values = zip(*chunk)
            rows = session.execute(
                _KNOWN_BUCKETS,
                {
                    "buckets": list(buckets),
                    "ids": list(ids),
                    "sizes": list(values),
                    "window_end": window_end,
                },
            ).all()
            for bucket, deployment_id, size_bytes in rows:
                yield Observation(
                    subject=SubjectSpec(
                        kind=SubjectKind.BUCKET,
                        ref=bucket,
                        namespace=self.namespace,
                        deployment_id=deployment_id,
                    ),
                    quantities={SIZE_METRIC: size_bytes * hours},
                )
