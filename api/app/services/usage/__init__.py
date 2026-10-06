"""The usage ledger: sampling OpenCost and Prometheus and recording what deployments consume.

A source reads one closed window and yields observations -- a subject and its
quantities -- lazily; ``ledger`` writes them a chunk at a time, each chunk's subjects in
one upsert and its samples in another, so memory stays bounded however many subjects a
window holds.

  - ``sampler``     which windows to read per source, in what order, and when to stop
  - ``containers``  the OpenCost source: ``opencost`` (transport), ``source`` (whether a
                    window is trustworthy), ``mapping`` (fields to catalogued quantities)
  - ``databases``   the tenant database source, read through ``prometheus``
  - ``subjects``    subject identity, container attribution, and the bulk upsert
  - ``ledger``      the append-only, idempotent, chunked write
  - ``batching``    the chunking both use
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
