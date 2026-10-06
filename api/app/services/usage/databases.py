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

from datetime import datetime, timedelta
from decimal import Decimal
import logging
import re

from sqlmodel import Session, select

from app.config import CaelusSettings
from app.models import DeploymentDatabaseORM, DeploymentORM
from app.models.usage import SubjectKind
from app.services.relational_storage import NAME_PREFIX
from app.services.usage import subjects
from app.services.usage.ledger import SampleRow
from app.services.usage.prometheus import PrometheusClient, PrometheusException

logger = logging.getLogger(__name__)

# Published by the exporter sidecar in tf/app/caelus/tenant-db.tf.
SIZE_SERIES = "pg_database_size_bytes"

SIZE_METRIC = "db_byte_hours"
ALLOWANCE_METRIC = "db_allowance_byte_hours"

SECONDS_PER_HOUR = Decimal(3600)


class DatabaseSizeSource:
    """Tenant databases in one environment's tenant cluster."""

    name = "databases"
    subject_kind = SubjectKind.DATABASE

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

    def average_sizes(self, window_start: datetime, window_seconds: int) -> dict[str, Decimal]:
        """Each tenant database's average size over the window, in bytes, by name.

        A database measured for only part of the window is averaged over that part.
        """
        end = window_start + timedelta(seconds=window_seconds)
        result = self.prometheus.query(
            f'avg_over_time({SIZE_SERIES}{{namespace="{self.namespace}",'
            f'datname=~"{re.escape(NAME_PREFIX)}.*"}}[{window_seconds}s])',
            end,
        )
        return {
            series["metric"]["datname"]: Decimal(series["value"][1])
            for series in result
            if series.get("metric", {}).get("datname")
        }

    def read(
        self,
        session: Session,
        window_start: datetime,
        *,
        window_seconds: int,
        observed_at: datetime,
    ) -> list[SampleRow] | None:
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

        window_end = window_start + timedelta(seconds=window_seconds)
        hours = Decimal(window_seconds) / SECONDS_PER_HOUR
        rows: list[SampleRow] = []
        for record, deployment in _known_databases(session, set(sizes)):
            if deployment.deleted_at is not None and deployment.deleted_at < window_end:
                continue
            subject_id = subjects.upsert_subject(
                session,
                kind=SubjectKind.DATABASE,
                ref=record.db_name,
                namespace=self.namespace,
                deployment_id=deployment.id,
                observed_at=observed_at,
            )
            quantities = {SIZE_METRIC: sizes[record.db_name] * hours}
            allowance = _allowance_bytes(deployment)
            if allowance is not None:
                quantities[ALLOWANCE_METRIC] = Decimal(allowance) * hours
            rows.extend(
                SampleRow(
                    subject_id=subject_id,
                    metric=metric,
                    window_start=window_start,
                    interval_seconds=window_seconds,
                    value=value,
                )
                for metric, value in quantities.items()
            )
        return rows


def _known_databases(
    session: Session, names: set[str]
) -> list[tuple[DeploymentDatabaseORM, DeploymentORM]]:
    """The databases this environment's records hold, among `names`.

    A name the records do not know is not recorded: it is not this environment's, or
    not a deployment's at all.
    """
    if not names:
        return []
    return list(
        session.exec(
            select(DeploymentDatabaseORM, DeploymentORM)
            .join(DeploymentORM, DeploymentORM.id == DeploymentDatabaseORM.deployment_id)
            .where(DeploymentDatabaseORM.db_name.in_(sorted(names)))
        ).all()
    )


def _allowance_bytes(deployment: DeploymentORM) -> int | None:
    """The current plan's database allowance, or None when it declares none.

    Unlike `relational_storage.resolve_quota_bytes`, a missing allowance is not an
    error here: it costs the window its allowance row, not its size.
    """
    subscription = deployment.subscription
    template = subscription.plan_template if subscription is not None else None
    allowance = template.database_bytes if template is not None else None
    return allowance if allowance and allowance > 0 else None
