"""Containers, read from OpenCost's allocation API, as a usage source.

Reading a window is `source`, naming what each allocation contains is `mapping`, and
attribution is the `deployment` table, looked up one chunk of allocations at a time.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta

from sqlmodel import Session

from app.services.usage import subjects
from app.services.usage.batching import batched
from app.services.usage.ledger import Observation
from app.services.usage.mapping import quantities
from app.services.usage.opencost import Allocation, OpenCostClient
from app.services.usage.source import billable, read_window

# Builds record every other container quantity, so these three are the container
# source's only resume position.
POSITION_METRICS = frozenset(
    {"network_receive_bytes", "network_transmit_bytes", "pv_byte_hours"}
)


class OpenCostSource:
    """Every container in this environment's tenants and the platform's namespaces."""

    name = "opencost"
    position_metrics = POSITION_METRICS

    def __init__(
        self,
        client: OpenCostClient,
        *,
        environment: str,
        builds_namespace: str | None = None,
    ) -> None:
        self.client = client
        self.environment = environment
        self.builds_namespace = builds_namespace

    def read(
        self, session: Session, window_start: datetime, *, window_seconds: int
    ) -> Iterator[Observation] | None:
        """None when the window is unusable; otherwise its observations, lazily.

        OpenCost answers a window in one response, so the allocations are held; what
        is derived from them is not.
        """
        window_end = window_start + timedelta(seconds=window_seconds)
        reading = read_window(self.client, window_start, window_end)
        if not reading.is_usable:
            return None

        allocations = billable(
            reading.allocations,
            environment=self.environment,
            builds_namespace=self.builds_namespace,
        )
        if not allocations:
            return None
        return observations(session, allocations)


def observations(
    session: Session, allocations: Iterable[Allocation]
) -> Iterator[Observation]:
    """Each allocation as an observation, attributed one chunk at a time.

    Platform namespaces resolve to no deployment and are still recorded.
    """
    for chunk in batched(allocations):
        owners = subjects.deployment_ids_by_namespace(
            session, {a.namespace for a in chunk if a.namespace}
        )
        for allocation in chunk:
            yield Observation(
                subject=subjects.container_subject(allocation, owners.get(allocation.namespace)),
                quantities=quantities(allocation),
            )
