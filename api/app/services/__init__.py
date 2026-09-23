"""Service layer.

Most modules here are imported by path (``from app.services import deployments``).
``usage`` is a package rather than a module, so its interface is re-exported here to
keep call sites looking the same as every other service's.

The re-export is resolved on first attribute access rather than at import time:
``app.models.core`` imports from ``app.services``, so binding ``usage`` eagerly here
would close a cycle through ``app.models``.
"""

_USAGE_EXPORTS = {
    "OpenCostClient",
    "OpenCostException",
    "SampleRun",
    "last_recorded_window",
    "sample_once",
}

__all__ = sorted(_USAGE_EXPORTS)


def __getattr__(name: str):
    if name in _USAGE_EXPORTS:
        from app.services import usage

        return getattr(usage, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _USAGE_EXPORTS)
