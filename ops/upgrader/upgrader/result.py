"""A product's outcome comes from the result.json its session wrote (product-upgrade-runs, D4)."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


class ResultError(Exception):
    pass


def parse_result(raw: bytes | None, schema_path: Path, slug: str, dry_run: bool) -> dict:
    """Validate a session's result.json against the contract in the service's own clone."""
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
    if doc["status"] == "would_skip" and not dry_run:
        raise ResultError("a real run that would skip records skipped, not would_skip")
    return doc


def summary(doc: dict) -> str:
    """One result in a line, and each decision it leaves to a human below it."""
    detail = doc.get("skip_reason") or doc.get("error") or doc.get("branch") or ""
    target = f" -> {doc['target_version']}" if doc.get("target_version") else ""
    draft = " (draft)" if doc.get("draft") else ""
    lines = [f"{doc['product']}: {doc['status']} {doc.get('current_version')}{target}{draft} {detail}".rstrip()]
    lines += [f"  needs a human: {decision}" for decision in doc.get("needs_human") or []]
    return "\n".join(lines)
