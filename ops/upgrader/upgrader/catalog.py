"""Which curated products a run covers (product-upgrade-runs)."""

from __future__ import annotations

from pathlib import Path

import yaml

PLACEHOLDER = "OWNER/REPO"


def eligible(clone: Path) -> list[str]:
    """Slugs of the catalog files with a real `upstream` block, in slug order."""
    slugs = []
    for path in sorted((clone / "products" / "catalog").glob("*.yaml")):
        doc = yaml.safe_load(path.read_text()) or {}
        upstream = doc.get("upstream")
        source = upstream.get("source") if isinstance(upstream, dict) else None
        if isinstance(source, dict) and PLACEHOLDER not in source.values():
            slugs.append(path.stem)
    return slugs
