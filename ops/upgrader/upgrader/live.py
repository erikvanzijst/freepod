"""The running session's transcript as pi writes it, read by byte offset so that a refresh reads only
what is new (product-upgrade-dashboard, D13)."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

from .redact import Redactor

TAIL_BYTES = 64 * 1024
MAX_READ = 256 * 1024
OPENING_STEPS = 20


@dataclass(frozen=True)
class Step:
    kind: str  # user, text, thinking, tool, result, error or note
    text: str
    label: str = ""


@dataclass(frozen=True)
class Session:
    result_id: int
    directory: Path
    redact: Redactor


class Live:
    """The session running now. The runner registers it and the dashboard reads it (D1)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._session: Session | None = None

    def start(self, session: Session) -> None:
        with self._lock:
            self._session = session

    def stop(self, result_id: int) -> None:
        with self._lock:
            if self._session and self._session.result_id == result_id:
                self._session = None

    def current(self, result_id: int) -> Session | None:
        with self._lock:
            session = self._session
        return session if session and session.result_id == result_id else None


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _first_lines(text: str, count: int, width: int) -> str:
    rows = [row for row in text.splitlines() if row.strip()]
    shown = [_clip(row, width) for row in rows[:count]]
    rest = len(rows) - len(shown)
    return "\n".join(shown) + (f"\n… +{rest} lines" if rest > 0 else "")


def _texts(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    return [c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text"]


def steps_of(entry: dict) -> list[Step]:
    if entry.get("type") == "compaction":
        return [Step("note", "context compacted")]
    message = entry.get("message") if entry.get("type") == "message" else None
    if not isinstance(message, dict):
        return []
    role, content = message.get("role"), message.get("content") or []
    if role == "user":
        text = " ".join(_texts(content))
        return [Step("user", _clip(text, 600))] if text.strip() else []
    if role == "toolResult":
        text = "\n".join(_texts(content))
        if message.get("isError"):
            return [Step("error", _first_lines(text, 3, 200) or "error")]
        return [Step("result", _first_lines(text, 2, 160) or "(no output)")]
    if role != "assistant" or not isinstance(content, list):
        return []
    steps = []
    for c in content:
        kind = c.get("type") if isinstance(c, dict) else None
        if kind == "thinking" and c.get("thinking", "").strip():
            steps.append(Step("thinking", _clip(c["thinking"].strip().splitlines()[0], 140)))
        elif kind == "text" and c.get("text", "").strip():
            steps.append(Step("text", _clip(c["text"], 1200)))
        elif kind == "toolCall":
            args = c.get("arguments") or {}
            target = args.get("command") or args.get("path") or args.get("file_path") or json.dumps(args)
            steps.append(Step("tool", _clip(str(target), 400), label=str(c.get("name") or "tool")))
    return steps


def _parse(data: bytes, redact: Redactor) -> list[Step]:
    steps: list[Step] = []
    for line in data.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(redact.bytes(line))
        except ValueError:
            continue
        if isinstance(entry, dict):
            steps.extend(steps_of(entry))
    return steps


def transcript(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None
    return next(iter(sorted(directory.rglob("*.jsonl"))), None)


def read(session: Session, offset: int | None) -> tuple[list[Step], int]:
    """The steps written after `offset`, and the offset to ask for next. Without an offset (a panel
    that just opened), or past the end (the file was rewritten), the latest few steps. Every call
    reads a bounded number of bytes, however long the transcript is."""
    path = transcript(session.directory)
    if path is None:
        return [], 0
    with path.open("rb") as f:
        size = f.seek(0, 2)
        if offset is None or offset > size:
            start = max(0, size - TAIL_BYTES)
            f.seek(start)
            data = f.read(size - start)
            if start:
                cut = data.find(b"\n")
                data, start = (data[cut + 1:], start + cut + 1) if cut >= 0 else (b"", start)
            end = data.rfind(b"\n") + 1
            return _parse(data[:end], session.redact)[-OPENING_STEPS:], start + end
        f.seek(offset)
        data = f.read(MAX_READ)
        end = data.rfind(b"\n") + 1
        if end:
            return _parse(data[:end], session.redact), offset + end
        if len(data) < MAX_READ:
            return [], offset
        skipped = len(data)
        while chunk := f.read(MAX_READ):
            cut = chunk.find(b"\n")
            if cut >= 0:
                skipped += cut + 1
                return [Step("note", f"a {skipped // 1024} KiB entry, too large to show")], offset + skipped
            skipped += len(chunk)
        return [], offset
