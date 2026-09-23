"""Thin transport over OpenCost's allocation API, plus the check that says whether its
answer can be trusted.

Knows windows, aggregation keys and OpenCost's field names; nothing about subjects,
deployments or the ledger.

Three things here are load-bearing and non-obvious. The aggregation must name all four
fields, or the namespace is dropped and attribution becomes impossible. Identity comes
from ``properties``, never the response key, which prefixes the controller with its
kind. And ``allocation_series_cover`` asks Prometheus whether OpenCost's own exporter
published over a window, because ``/allocation`` answers 200 with request-only numbers
when it did not -- a health check, not a measurement; see the design's "A window whose
measurements are untrustworthy is not recorded".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import json
import logging
from typing import Any

import httpx

from app.config import CaelusSettings, get_settings
from app.services.errors import CaelusException

logger = logging.getLogger(__name__)

ALLOCATION_PATH = "/allocation"
AGGREGATE_BY = "namespace,controllerKind,controller,container"

# Translated at the boundary and never stored, so a rename upstream cannot reach the
# ledger's identities.
UNALLOCATED = "__unallocated__"
UNMOUNTED = "__unmounted__"

ALLOCATION_SERIES = "container_cpu_allocation"


class OpenCostException(CaelusException):
    """OpenCost could not be reached, or answered something unusable."""


@dataclass(frozen=True)
class Allocation:
    """One container's usage over one window.

    ``controller`` and ``controller_kind`` are None when OpenCost could not resolve
    them -- not an error, and not a reason to retry.
    """

    namespace: str | None
    controller_kind: str | None
    controller: str | None
    container: str
    window_start: datetime
    window_end: datetime
    minutes: Decimal
    fields: dict[str, Decimal]

    @property
    def is_unmounted(self) -> bool:
        """A synthetic bucket for volumes no running pod mounts.

        Carries a namespace under this aggregation, so it is not self-excluding.
        """
        return self.container == UNMOUNTED

    @property
    def is_resolved(self) -> bool:
        return self.controller is not None and self.controller_kind is not None


def _parse_window(value: str) -> datetime:
    """RFC3339 in, naive UTC out, matching the schema's timestamp columns.

    Converted rather than merely stripped: a non-Zulu offset would otherwise be stored
    as its own local wall clock, putting the window at the wrong instant and off the
    alignment grid.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC).replace(tzinfo=None)


def _decimal(value: Any) -> Decimal:
    """`str` first for a float, so a caller that parsed the JSON itself does not
    inherit a binary artifact."""
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _property(properties: dict[str, Any], name: str) -> str | None:
    value = properties.get(name)
    if value is None or value == UNALLOCATED:
        return None
    return value


def parse_allocations(payload: dict[str, Any]) -> list[list[Allocation]]:
    """One list of allocations per window, in the order OpenCost returned them."""
    windows: list[list[Allocation]] = []
    for window in payload.get("data") or []:
        allocations = []
        for entry in window.values():
            properties = entry.get("properties") or {}
            container = _property(properties, "container")
            if container is None:
                continue
            allocations.append(
                Allocation(
                    namespace=_property(properties, "namespace"),
                    controller_kind=_property(properties, "controllerKind"),
                    controller=_property(properties, "controller"),
                    container=container,
                    window_start=_parse_window(entry["window"]["start"]),
                    window_end=_parse_window(entry["window"]["end"]),
                    minutes=_decimal(entry.get("minutes")),
                    fields={
                        key: _decimal(value)
                        for key, value in entry.items()
                        if isinstance(value, (int, float, Decimal))
                        and not isinstance(value, bool)
                    },
                )
            )
        windows.append(allocations)
    return windows


class OpenCostClient:
    """Reads allocations, and asks Prometheus whether they can be trusted."""

    def __init__(
        self,
        base_url: str,
        *,
        prometheus_url: str = "",
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.prometheus_url = prometheus_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client

    def _get(self, url: str, params: dict[str, str]) -> httpx.Response:
        if self._client is not None:
            return self._client.get(url, params=params)
        with httpx.Client(timeout=self.timeout_seconds) as client:
            return client.get(url, params=params)

    @classmethod
    def from_settings(
        cls, settings: CaelusSettings | None = None, **kwargs: Any
    ) -> "OpenCostClient":
        settings = settings or get_settings()
        return cls(
            settings.opencost_base_url,
            prometheus_url=settings.prometheus_base_url,
            timeout_seconds=settings.opencost_timeout_seconds,
            **kwargs,
        )

    def fetch_allocations(
        self, start: datetime, end: datetime, *, step: str = "1h"
    ) -> list[list[Allocation]]:
        """Fetch one window per step between `start` and `end`.

        Raises rather than returning empty: unreachable and "reported nothing" are
        different answers.
        """
        if not self.base_url:
            raise OpenCostException("OpenCost is not configured")

        params = {
            "window": f"{_stamp(start)},{_stamp(end)}",
            "step": step,
            "aggregate": AGGREGATE_BY,
            "accumulate": "false",
        }
        try:
            response = self._get(f"{self.base_url}{ALLOCATION_PATH}", params)
        except httpx.HTTPError as exc:
            raise OpenCostException(f"OpenCost request failed: {exc}") from exc

        if response.status_code != 200:
            raise OpenCostException(
                f"OpenCost returned {response.status_code} for {params['window']}"
            )
        try:
            payload = json.loads(response.text, parse_float=Decimal)
        except ValueError as exc:
            raise OpenCostException("OpenCost returned a non-JSON body") from exc

        return parse_allocations(payload)

    def allocation_series_cover(self, start: datetime, end: datetime) -> bool:
        """Whether OpenCost's own exporter published over this window.

        False means `cpuCoreHours` collapsed to the request and must not be recorded.
        """
        if not self.prometheus_url:
            raise OpenCostException("Prometheus is not configured")

        span = int((end - start).total_seconds())
        try:
            response = self._get(
                f"{self.prometheus_url}/api/v1/query",
                {
                    "query": f"count(count_over_time({ALLOCATION_SERIES}[{span}s]))",
                    "time": _stamp(end),
                },
            )
        except httpx.HTTPError as exc:
            raise OpenCostException(f"Prometheus request failed: {exc}") from exc

        if response.status_code != 200:
            raise OpenCostException(f"Prometheus returned {response.status_code}")
        result = (response.json().get("data") or {}).get("result") or []
        return bool(result)


def _stamp(moment: datetime) -> str:
    """Naive UTC out to the RFC3339 Zulu both APIs expect."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
