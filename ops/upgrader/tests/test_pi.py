import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from upgrader import pi
from upgrader.config import Settings

from .test_config import FULL

FIXTURE = Path(__file__).parent / "fixtures" / "session.jsonl"
EXPECTED_STATS = (16218, 3998, 20772)


def settings(**env):
    return Settings.from_env({**FULL, "INFERENCE_API_KEY": "sk-never-on-disk", **env})


def test_models_json_references_the_key_and_never_contains_it(tmp_path):
    agent = pi.write_agent_dir(tmp_path / "agent", settings())
    text = (agent / "models.json").read_text()
    assert '"$INFERENCE_API_KEY"' in text
    assert "sk-never-on-disk" not in text
    provider = json.loads(text)["providers"]["upgrader"]
    assert provider["baseUrl"] == "https://ai.example/v1"
    assert provider["models"][0]["id"] == "qwen"


def test_command():
    cmd = pi.command(settings(THINKING_LEVEL="high"), Path("/w/freepod/products/UPGRADING/SKILL.md"),
                     Path("/w/session"), pi.prompt("immich"))
    assert cmd[:2] == ["pi", "--model"] and cmd[2] == "upgrader/qwen"
    assert cmd[cmd.index("--thinking") + 1] == "high"
    assert cmd[cmd.index("--skill") + 1] == "/w/freepod/products/UPGRADING/SKILL.md"
    assert cmd[cmd.index("--session-dir") + 1] == "/w/session"
    assert "--no-context-files" in cmd and "-p" in cmd and "--session" not in cmd
    assert "--no-extensions" in cmd and cmd[cmd.index("-e") + 1] == str(pi.LOOP_GUARD)
    assert pi.LOOP_GUARD.is_file()
    assert "immich" in cmd[-1]


def test_a_repair_command_resumes_the_transcript():
    cmd = pi.command(settings(), Path("/w/SKILL.md"), Path("/w/session"),
                     pi.repair_prompt("immich", "result.json is not valid JSON"),
                     resume=Path("/w/session/s.jsonl"))
    assert cmd[cmd.index("--session") + 1] == "/w/session/s.jsonl"
    assert "not valid JSON" in cmd[-1] and "immich/result.json" in cmd[-1]


def test_session_stats_from_a_trimmed_experiment_transcript():
    stats = pi.session_stats(FIXTURE)
    assert (stats.input_tokens, stats.output_tokens, stats.peak_context) == EXPECTED_STATS


class _Inference(BaseHTTPRequestHandler):
    bodies: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).bodies.append(body)
        chunk = lambda delta, finish: json.dumps({  # noqa: E731
            "id": "c", "object": "chat.completion.chunk", "created": 0, "model": "qwen",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for data in (chunk({"role": "assistant", "content": "ok"}, None), chunk({}, "stop"), "[DONE]"):
            self.wfile.write(f"data: {data}\n\n".encode())

    def log_message(self, *args):
        pass


@pytest.mark.skipif(shutil.which("pi") is None, reason="needs the pi binary")
@pytest.mark.parametrize("level, effort", [("low", "low"), ("max", "xhigh"), ("medium", "medium")])
def test_thinking_level_reaches_the_model_as_reasoning_effort(tmp_path, level, effort):
    _Inference.bodies = []
    server = HTTPServer(("127.0.0.1", 0), _Inference)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        s = settings(INFERENCE_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1", THINKING_LEVEL=level)
        agent = pi.write_agent_dir(tmp_path / "agent", s)
        subprocess.run(
            ["pi", "--model", "upgrader/qwen", "--thinking", level, "--no-session", "--no-tools",
             "--no-skills", "--no-extensions", "--no-context-files", "--offline", "-p", "--", "hi"],
            cwd=tmp_path, capture_output=True, text=True, timeout=120, check=True,
            # pi reads stdin even under -p; -s would leave it CI's open pipe. As runner.py does.
            stdin=subprocess.DEVNULL,
            env={**os.environ, "PI_CODING_AGENT_DIR": str(agent), "PI_TELEMETRY": "0",
                 "INFERENCE_API_KEY": "sk-test"},
        )
    finally:
        server.shutdown()
    assert _Inference.bodies, "pi sent no request"
    assert _Inference.bodies[0]["chat_template_kwargs"]["reasoning_effort"] == effort


class _Looping(BaseHTTPRequestHandler):
    """A model that asks for `commands[n]` on its nth turn, cycling, for 20 turns."""

    bodies: list = []
    commands: list = []

    def do_POST(self):
        type(self).bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        n = len(type(self).bodies)
        call = {"index": 0, "id": f"call{n}", "type": "function",
                "function": {"name": "bash", "arguments": json.dumps(
                    {"command": type(self).commands[(n - 1) % len(type(self).commands)]})}}
        chunk = lambda delta, finish: json.dumps({  # noqa: E731
            "id": "c", "object": "chat.completion.chunk", "created": 0, "model": "qwen",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        frames = ([chunk({"role": "assistant", "tool_calls": [call]}, None), chunk({}, "tool_calls")]
                  if n <= 20 else [chunk({"role": "assistant", "content": "done"}, None), chunk({}, "stop")])
        for data in (*frames, "[DONE]"):
            self.wfile.write(f"data: {data}\n\n".encode())

    def log_message(self, *args):
        pass


def _run_looping(tmp_path, commands):
    _Looping.bodies, _Looping.commands = [], commands
    server = HTTPServer(("127.0.0.1", 0), _Looping)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        s = settings(INFERENCE_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1")
        agent = pi.write_agent_dir(tmp_path / "agent", s)
        skill = tmp_path / "SKILL.md"
        skill.write_text("---\nname: upgrade-product\ndescription: test\n---\nDo the thing.\n")
        cmd = pi.command(s, skill, tmp_path / "session", "go")
        out = subprocess.run(
            [cmd[0], "--offline", *cmd[1:]], cwd=tmp_path, capture_output=True, text=True,
            timeout=120, stdin=subprocess.DEVNULL,
            env={**os.environ, "PI_CODING_AGENT_DIR": str(agent), "PI_TELEMETRY": "0",
                 "INFERENCE_API_KEY": "sk-test"},
        )
    finally:
        server.shutdown()
    assert out.returncode == 0, out.stderr
    [transcript] = (tmp_path / "session").glob("*.jsonl")
    results = [e["message"] for e in map(json.loads, transcript.read_text().splitlines())
               if e.get("type") == "message" and e["message"].get("role") == "toolResult"]
    return out, results


@pytest.mark.skipif(shutil.which("pi") is None, reason="needs the pi binary")
def test_the_loop_guard_ends_a_session_that_repeats_one_call(tmp_path):
    out, results = _run_looping(tmp_path, ["echo same"])
    assert "loop-guard: stopped the session after 5 identical bash calls" in out.stderr
    assert len(_Looping.bodies) == 5
    assert [r["isError"] for r in results] == [False, False, True, True, True]
    assert results[0]["content"][0]["text"].strip() == "same"
    assert results[2]["content"][0]["text"].startswith("Not run: this is the same bash call 3 times")
    assert results[4]["content"][0]["text"].startswith("Stopped:")


@pytest.mark.skipif(shutil.which("pi") is None, reason="needs the pi binary")
def test_the_loop_guard_lets_a_call_repeat_after_other_work(tmp_path):
    out, results = _run_looping(tmp_path, ["echo one", "echo two"])
    assert "loop-guard" not in out.stderr
    assert len(results) == 20 and not any(r["isError"] for r in results)
