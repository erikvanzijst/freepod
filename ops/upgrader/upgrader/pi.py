"""The agent harness: its model configuration (D7), its invocation, and its transcripts."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Settings

PROVIDER = "upgrader"


def models_config(settings: Settings) -> dict:
    return {
        "providers": {
            PROVIDER: {
                "baseUrl": settings.inference_base_url,
                "api": "openai-completions",
                "apiKey": "$INFERENCE_API_KEY",
                "compat": {
                    "supportsDeveloperRole": False,
                    "thinkingFormat": "chat-template",
                    "thinkingTokenBudgetField": "thinking_budget_tokens",
                    "chatTemplateKwargs": {"reasoning_effort": {"$var": "thinking.effort"}},
                },
                "models": [
                    {
                        "id": settings.inference_model,
                        "reasoning": True,
                        "contextWindow": 200000,
                        "thinkingLevelMap": {"minimal": "low", "max": "xhigh"},
                    }
                ],
            }
        }
    }


def write_agent_dir(agent_dir: Path, settings: Settings) -> Path:
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "models.json").write_text(json.dumps(models_config(settings), indent=2))
    return agent_dir


def prompt(slug: str) -> str:
    return (
        f"Run the upgrade-product skill for the {slug} product only. The repository is already "
        "cloned at ./freepod: work in that clone and do not clone it again. Read the skill file "
        "in full before you start."
    )


def command(settings: Settings, skill: Path, session_dir: Path, slug: str, pi: str = "pi") -> list[str]:
    return [
        pi,
        "--model", f"{PROVIDER}/{settings.inference_model}",
        "--thinking", settings.thinking_level,
        "--skill", str(skill),
        "--no-context-files",
        "--session-dir", str(session_dir),
        "-p", "--", prompt(slug),
    ]


def version(pi: str = "pi") -> str | None:
    try:
        out = subprocess.run([pi, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None


def export_html(transcript: Path, html: Path, pi: str = "pi") -> None:
    subprocess.run(
        [pi, "--export", str(transcript), str(html)],
        check=True, capture_output=True, timeout=300, env={**os.environ, "PI_TELEMETRY": "0"},
    )


@dataclass(frozen=True)
class SessionStats:
    input_tokens: int
    output_tokens: int
    peak_context: int


def session_stats(transcript: Path) -> SessionStats:
    """Token totals over the assistant turns; the peak context is the largest input plus cache read."""
    total_in = total_out = peak = 0
    with transcript.open() as lines:
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            message = entry.get("message") or {}
            if entry.get("type") != "message" or message.get("role") != "assistant":
                continue
            usage = message.get("usage") or {}
            total_in += usage.get("input") or 0
            total_out += usage.get("output") or 0
            peak = max(peak, (usage.get("input") or 0) + (usage.get("cacheRead") or 0))
    return SessionStats(total_in, total_out, peak)
