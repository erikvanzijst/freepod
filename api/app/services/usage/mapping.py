"""Which catalogued quantity each OpenCost field becomes.

A field absent from the response yields no quantity: absent means not measured, a
recorded zero means measured and zero, and defaulting would erase the distinction. No
cost field is consumed.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.usage.opencost import Allocation

# Ledger metric name -> the OpenCost field it reads. `test_usage_mapping` pins these
# names to the catalog.
FIELD_METRICS: dict[str, str] = {
    "cpu_core_hours":           "cpuCoreHours",
    "cpu_usage_cores_avg":      "cpuCoreUsageAverage",
    "cpu_request_cores_avg":    "cpuCoreRequestAverage",
    "cpu_limit_cores_avg":      "cpuCoreLimitAverage",
    "ram_byte_hours":           "ramByteHours",
    "ram_usage_bytes_avg":      "ramByteUsageAverage",
    "ram_request_bytes_avg":    "ramByteRequestAverage",
    "ram_limit_bytes_avg":      "ramByteLimitAverage",
    "network_transmit_bytes":   "networkTransferBytes",
    "network_receive_bytes":    "networkReceiveBytes",
    "pv_byte_hours":            "pvByteHours",
}

# Not a field: derived from `minutes`, which is what distinguishes a quiet hour from a
# short one.
RUNNING_SECONDS = "running_seconds"

SECONDS_PER_MINUTE = Decimal(60)


def quantities(allocation: Allocation) -> dict[str, Decimal]:
    """The catalogued quantities this allocation reports, by metric name."""
    measured = {
        metric: allocation.fields[field]
        for metric, field in FIELD_METRICS.items()
        if field in allocation.fields
    }
    measured[RUNNING_SECONDS] = allocation.minutes * SECONDS_PER_MINUTE
    return measured
