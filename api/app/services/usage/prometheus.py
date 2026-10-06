"""Instant queries against Prometheus's HTTP API.

Shared by the OpenCost source's trust check and the database source, which reads its
values here directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.services.errors import CaelusException


class PrometheusException(CaelusException):
    """Prometheus could not be reached, or answered something unusable."""


class PrometheusClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client

    def query(self, promql: str, at: datetime) -> list[dict[str, Any]]:
        """The instant vector `promql` evaluates to at `at`, as Prometheus's result list.

        An empty list is an answer, not a failure: the series did not exist.
        """
        if not self.base_url:
            raise PrometheusException("Prometheus is not configured")

        params = {"query": promql, "time": stamp(at)}
        url = f"{self.base_url}/api/v1/query"
        try:
            if self._client is not None:
                response = self._client.get(url, params=params)
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise PrometheusException(f"Prometheus request failed: {exc}") from exc

        if response.status_code != 200:
            raise PrometheusException(f"Prometheus returned {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise PrometheusException("Prometheus returned a non-JSON body") from exc
        return (payload.get("data") or {}).get("result") or []


def stamp(moment: datetime) -> str:
    """Naive UTC out to the RFC3339 Zulu Prometheus and OpenCost expect."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
