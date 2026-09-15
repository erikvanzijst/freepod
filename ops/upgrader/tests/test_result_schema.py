import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCHEMA = Path(__file__).resolve().parents[3] / "products" / "UPGRADING" / "result.schema.json"


@pytest.fixture(scope="module")
def validator():
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def result(status, **fields):
    base = {
        "schema_version": 1,
        "product": "immich",
        "dry_run": status.startswith("would"),
        "status": status,
        "current_version": "v3.1.0",
        "target_version": "v3.2.1",
        "draft": False,
        "needs_human": [],
    }
    return {**base, **fields}


VALID = [
    result("up_to_date", target_version=None),
    result("opened", pr_url="https://github.com/erikvanzijst/freepod/pull/120",
           branch="upgrade/immich-v3.2.1", draft=True, needs_human=["x86-64-v2 on the node"]),
    result("would_open", branch="upgrade/immich-v3.2.1"),
    result("skipped", skip_reason="ghcr.io/immich-app/immich-server:v3.2.1 has no amd64 build"),
    result("would_skip", branch="upgrade/immich-v3.2.1", skip_reason="PR #118 sets v3.2.1"),
    result("failed", error="step 2: upstream.source is the OWNER/REPO placeholder",
           current_version=None, target_version=None),
    result("up_to_date", target_version=None, pr_url=None, branch=None, skip_reason=None, error=None),
]


@pytest.mark.parametrize("doc", VALID, ids=[d["status"] for d in VALID])
def test_accepts_each_status(validator, doc):
    assert list(validator.iter_errors(doc)) == []


@pytest.mark.parametrize(
    "doc",
    [
        result("failed"),
        result("failed", error=""),
        result("skipped"),
        result("would_skip", branch="upgrade/immich-v3.2.1"),
        result("opened", branch="upgrade/immich-v3.2.1"),
        result("opened", pr_url="https://example.com/x", branch="upgrade/immich-v3.2.1"),
        result("would_open"),
        result("would_open", branch="upgrade/x", pr_url="https://github.com/o/r/pull/1"),
        result("up_to_date"),
        {**result("up_to_date", target_version=None), "status": "done"},
        {k: v for k, v in result("up_to_date", target_version=None).items() if k != "dry_run"},
        result("up_to_date", target_version=None, schema_version=2),
    ],
    ids=[
        "failed-without-error",
        "failed-empty-error",
        "skipped-without-skip-reason",
        "would-skip-without-skip-reason",
        "opened-without-pr-url",
        "opened-with-foreign-url",
        "would-open-without-branch",
        "pr-url-outside-opened",
        "up-to-date-with-target",
        "unknown-status",
        "missing-dry-run",
        "wrong-schema-version",
    ],
)
def test_rejects(validator, doc):
    assert list(validator.iter_errors(doc)) != []
