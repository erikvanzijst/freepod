"""A product's outcome comes from the result.json its session wrote (product-upgrade-runs, D4)."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


class ResultError(Exception):
    pass


def parse_result(raw: bytes | None, schema_path: Path, slug: str, dry_run: bool) -> dict:
    """Validate a session's result.json against the contract in the session's own clone."""
    if raw is None:
        raise ResultError("the session ended without writing result.json")
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ResultError(f"result.json is not valid JSON: {exc}") from exc
    try:
        schema = json.loads(schema_path.read_text())
    except (OSError, ValueError) as exc:
        raise ResultError(f"the clone has no readable {schema_path.name}: {exc}") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        where = "/".join(str(p) for p in errors[0].path) or "(top level)"
        raise ResultError(f"result.json does not follow the contract at {where}: {errors[0].message}")
    if doc["product"] != slug:
        raise ResultError(f"result.json is for {doc['product']!r}, not {slug!r}")
    if doc["dry_run"] != dry_run:
        mode = "a dry run" if dry_run else "a real run"
        raise ResultError(f"result.json says dry_run={doc['dry_run']}, but the session was {mode}")
    return doc


def main(argv: list[str]) -> int:
    """`python -m upgrader.result SCHEMA RESULT SLUG DRY(0|1)`: validate and summarize one result."""
    schema, path, slug, dry = argv
    result = Path(path)
    try:
        doc = parse_result(result.read_bytes() if result.is_file() else None, Path(schema), slug, dry != "0")
    except ResultError as exc:
        print(f"{slug}: failed: {exc}")
        return 1
    detail = doc.get("pr_url") or doc.get("skip_reason") or doc.get("error") or doc.get("branch") or ""
    target = f" -> {doc['target_version']}" if doc.get("target_version") else ""
    draft = " (draft)" if doc.get("draft") else ""
    print(f"{slug}: {doc['status']} {doc.get('current_version')}{target}{draft} {detail}".rstrip())
    for decision in doc.get("needs_human") or []:
        print(f"  needs a human: {decision}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
