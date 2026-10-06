"""The usage ledger: sampling OpenCost and Prometheus and recording what deployments consume.

Modules, layered in the order an OpenCost window travels through them:

  - ``opencost``  transport, and the check that says whether a window is trustworthy
  - ``source``    the trust boundary: a window is readable, or it is refused
  - ``mapping``   which catalogued quantity each OpenCost field becomes
  - ``subjects``  who an allocation belongs to
  - ``ledger``    the append-only, idempotent write
  - ``sampler``   which windows to read per source, in what order, and when to stop

Tenant databases are a second source: ``databases`` reads their sizes through
``prometheus`` and attributes them through the platform's database records.

Callers outside this package want the names re-exported below; everything else is
internal to the layering.
"""

from app.services.usage.opencost import (  # noqa: F401
    OpenCostClient,
    OpenCostException,
)
from app.services.usage.sampler import (  # noqa: F401
    SampleRun,
    last_recorded_window,
    sample_once,
)

__all__ = [
    "OpenCostClient",
    "OpenCostException",
    "SampleRun",
    "last_recorded_window",
    "sample_once",
]
