#!/usr/bin/env python3
"""Stands in for pi. FAKE_PI selects what the session does."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

args = sys.argv[1:]
if args == ["--version"]:
    print("0.85.1")
    sys.exit(0)
if args[:1] == ["--export"]:
    Path(args[2]).write_text("<html>" + Path(args[1]).read_text() + "</html>")
    sys.exit(0)

mode = os.environ.get("FAKE_PI", "result:up_to_date")
slug = os.environ["UPGRADE_PRODUCT"]
dry = os.environ["UPGRADE_DRY_RUN"] != "0"
out = Path(os.environ["UPGRADE_OUT_DIR"]) / slug
out.mkdir(parents=True, exist_ok=True)
token = Path(os.environ["UPGRADER_TOKEN_FILE"]).read_text()

session_dir = Path(args[args.index("--session-dir") + 1])
session_dir.mkdir(parents=True, exist_ok=True)
transcript = session_dir / "2026-09-15T03-00-00-000Z_fake.jsonl"
usage = {"input": 1000, "output": 200, "cacheRead": 500}
with transcript.open("w") as f:
    f.write(json.dumps({"type": "session", "cwd": os.getcwd()}) + "\n")
    f.write(json.dumps({"type": "message", "message": {
        "role": "assistant", "usage": usage,
        "content": [{"type": "text", "text": f"GH_TOKEN={token} key={os.environ.get('INFERENCE_API_KEY')}"}],
    }}) + "\n")
    f.flush()
print(f"env has key: {'GITHUB_APP_PRIVATE_KEY' in os.environ}; token {token}", flush=True)
Path(os.environ["FAKE_PI_ENV"]).write_text(json.dumps(dict(os.environ))) if "FAKE_PI_ENV" in os.environ else None

if mode == "sleep":
    child = subprocess.Popen(["sleep", "600"])
    Path(os.environ["FAKE_PI_CHILD"]).write_text(str(child.pid))
    time.sleep(600)

result = {
    "schema_version": 1, "product": slug, "dry_run": dry, "status": "up_to_date",
    "current_version": "1.37.1", "target_version": None, "draft": False, "needs_human": [],
}
if mode == "none":
    sys.exit(0)
if mode == "malformed":
    (out / "result.json").write_text("{not json")
    sys.exit(0)
if mode == "wrong-product":
    result["product"] = "nextcloud"
if mode == "dry-mismatch":
    result["dry_run"] = not dry
if mode.startswith("result:"):
    status = mode.split(":", 1)[1]
    result["status"] = status
    if status in ("would_open", "would_skip", "opened"):
        result.update(target_version="1.37.3", branch=f"upgrade/{slug}-1.37.3", draft=True,
                      needs_human=["Check the invite fix"])
        (out / "body.md").write_text(f"## Summary\nUpgrade {slug}. token {token}\n")
        (out / "change.patch").write_text("diff --git a/x b/x\n")
    if status == "opened":
        result.update(pr_url="https://github.com/erikvanzijst/freepod/pull/200",
                      error=f"CI pending; token {token}", skip_reason=None)
    if status == "would_skip":
        result["skip_reason"] = "PR #150 already sets 1.37.3"
(out / "result.json").write_text(json.dumps(result))
