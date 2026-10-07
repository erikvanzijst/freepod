"""Tenant database sizes, read from Prometheus, as a usage source.

The postgres_exporter sidecar of the tenant database cluster (`tf/app/caelus/tenant-db.tf`)
publishes `pg_database_size_bytes{datname}`. A window's byte-hours are its average over
the window times the window's length.

Prometheus is read directly here, unlike for containers: there is one long-lived series
per database and nothing to join, so none of the pod churn that made OpenCost worth
depending on applies. Attribution still comes from the platform database, through the
`deployment_database` record the series' `datname` names.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta
from decimal import Decimal
import logging

from sqlalchemy import text
from sqlmodel import Session

from app.config import CaelusSettings
from app.models.usage import SubjectKind
from app.services.usage.batching import batched
from app.services.usage.ledger import Observation
from app.services.usage.prometheus import PrometheusClient, PrometheusException
from app.services.usage.subjects import SubjectSpec

logger = logging.getLogger(__name__)

# Published by the exporter sidecar in tf/app/caelus/tenant-db.tf.
SIZE_SERIES = "pg_database_size_bytes"

SIZE_METRIC = "db_byte_hours"
ALLOWANCE_METRIC = "db_allowance_byte_hours"

SECONDS_PER_HOUR = Decimal(3600)

# One chunk of measured sizes, kept to the databases this environment's records hold
# and whose deployment was not deleted before the window ended, with the plan's
# allowance. A name the records do not know is not this environment's, or not a
# deployment's at all. Set-based, so one round trip per chunk however many databases.
_KNOWN_DATABASES = text(
    """
    SELECT m.db_name, dd.deployment_id, m.size_bytes, ptv.database_bytes
    FROM unnest(CAST(:names AS text[]), CAST(:sizes AS numeric[])) AS m(db_name, size_bytes)
    JOIN deployment_database dd ON dd.db_name = m.db_name
    JOIN deployment d ON d.id = dd.deployment_id
    LEFT JOIN subscription s ON s.id = d.subscription_id
    LEFT JOIN plan_template_version ptv ON ptv.id = s.plan_template_id
    WHERE d.deleted_at IS NULL OR d.deleted_at >= :window_end
    """
)


class DatabaseSizeSource:
    """Tenant databases in one environment's tenant cluster."""

    name = "databases"
    position_metrics = frozenset({SIZE_METRIC})

    def __init__(self, prometheus: PrometheusClient, *, namespace: str) -> None:
        if not namespace:
            # Unscoped, the other environment's exporter would vouch for this one.
            raise ValueError("the tenant database namespace is required")
        self.prometheus = prometheus
        self.namespace = namespace

    @classmethod
    def from_settings(cls, settings: CaelusSettings) -> "DatabaseSizeSource":
        return cls(
            PrometheusClient(
                settings.prometheus_base_url,
                timeout_seconds=settings.opencost_timeout_seconds,
            ),
            namespace=settings.usage_tenant_db_namespace,
        )

    def covers(self, window_start: datetime, window_seconds: int) -> bool:
        """Whether this environment's exporter published anything over the window.

        Any database counts, `postgres` and `template1` included: the question is
        whether the exporter was measuring, not which databases exist.
        """
        end = window_start + timedelta(seconds=window_seconds)
        return bool(
            self.prometheus.query(
                f'count(count_over_time({SIZE_SERIES}{{namespace="{self.namespace}"}}'
                f"[{window_seconds}s]))",
                end,
            )
        )

    def average_sizes(
        self, window_start: datetime, window_seconds: int
    ) -> Iterator[tuple[str, Decimal]]:
        """Every database's average size over the window, in bytes, by name.

        A database measured for only part of the window is averaged over that part.
        Not filtered by name: which databases are tenants' is the platform records'
        answer (`_known_databases`), not a naming convention's.
        """
        end = window_start + timedelta(seconds=window_seconds)
        result = self.prometheus.query(
            f'avg_over_time({SIZE_SERIES}{{namespace="{self.namespace}"}}[{window_seconds}s])',
            end,
        )
        return (
            (series["metric"]["datname"], Decimal(series["value"][1]))
            for series in result
            if series.get("metric", {}).get("datname")
        )

    def read(
        self, session: Session, window_start: datetime, *, window_seconds: int
    ) -> Iterator[Observation] | None:
        """None when the window is unusable; otherwise its observations, lazily.

        Prometheus answers a window in one response, so its series are held; what is
        derived from them is not.
        """
        try:
            if not self.covers(window_start, window_seconds):
                logger.warning(
                    "Window %s not recorded for databases: the exporter in %s "
                    "published nothing over it",
                    window_start.isoformat(),
                    self.namespace,
                )
                return None
            sizes = self.average_sizes(window_start, window_seconds)
        except PrometheusException as exc:
            logger.warning(
                "Window %s not recorded for databases: %s", window_start.isoformat(), exc
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
        sizes: Iterable[tuple[str, Decimal]],
        *,
        window_end: datetime,
        hours: Decimal,
    ) -> Iterator[Observation]:
        for chunk in batched(sizes):
            names, values = zip(*chunk)
            rows = session.execute(
                _KNOWN_DATABASES,
                {"names": list(names), "sizes": list(values), "window_end": window_end},
            ).all()
            for db_name, deployment_id, size_bytes, allowance_bytes in rows:
                quantities = {SIZE_METRIC: size_bytes * hours}
                # A plan without an allowance costs the window its allowance row,
                # not its size.
                if allowance_bytes and allowance_bytes > 0:
                    quantities[ALLOWANCE_METRIC] = Decimal(allowance_bytes) * hours
                yield Observation(
                    subject=SubjectSpec(
                        kind=SubjectKind.DATABASE,
                        ref=db_name,
                        namespace=self.namespace,
                        deployment_id=deployment_id,
                    ),
                    quantities=quantities,
                )
