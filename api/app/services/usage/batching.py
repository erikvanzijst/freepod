"""Chunking, shared by everything that writes to the ledger."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from itertools import islice
from typing import TypeVar

# Rows per statement: well under PostgreSQL's 65535 bind parameters at six per sample,
# and large enough that a window with tens of thousands of subjects is a few dozen
# round trips.
CHUNK_SIZE = 1000

T = TypeVar("T")


def batched(items: Iterable[T], size: int = CHUNK_SIZE) -> Iterator[tuple[T, ...]]:
    """`itertools.batched`, which needs Python 3.12; the API declares 3.11."""
    iterator = iter(items)
    while chunk := tuple(islice(iterator, size)):
        yield chunk
