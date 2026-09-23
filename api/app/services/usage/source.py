"""Whether a window can be read at all, and what it yields when it can.

The trust boundary between `opencost.py` and the ledger. Three ways a window is
unusable -- unreachable or non-200, no allocations, or OpenCost's own exporter not
publishing over it -- and all three look alike to the caller, because the response to
each is the same: record nothing, advance nothing, try again later.

Distinct from an *unattributable* window, which is usable and does advance progress.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging

from app.services.usage.opencost import Allocation, OpenCostClient, OpenCostException

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowReading:
    """What one window yielded, and why it yielded nothing when it did."""

    start: datetime
    end: datetime
    allocations: list[Allocation] | None
    reason: str | None = None

    @property
    def is_usable(self) -> bool:
        return self.allocations is not None

    @property
    def interval_seconds(self) -> int:
        return int((self.end - self.start).total_seconds())


def _unusable(start: datetime, end: datetime, reason: str) -> WindowReading:
    logger.warning("Window %s not recorded: %s", start.isoformat(), reason)
    return WindowReading(start=start, end=end, allocations=None, reason=reason)


def read_window(
    client: OpenCostClient, start: datetime, end: datetime
) -> WindowReading:
    """Read one window, or say why it cannot be trusted.

    The exporter check runs first: a window whose numbers are wrong is worth no
    allocation request.
    """
    try:
        if not client.allocation_series_cover(start, end):
            return _unusable(
                start, end, "OpenCost's exporter published nothing over the window"
            )
        windows = client.fetch_allocations(start, end)
    except OpenCostException as exc:
        return _unusable(start, end, str(exc))

    allocations = windows[0] if windows else []
    if not allocations:
        return _unusable(start, end, "the source reported no allocations")

    return WindowReading(start=start, end=end, allocations=allocations)


def billable(allocations: list[Allocation]) -> list[Allocation]:
    """Everything but the unmounted-PV buckets.

    They carry a tenant namespace under this aggregation, so they are recognized by
    container name rather than by a missing one.
    """
    return [a for a in allocations if not a.is_unmounted]
