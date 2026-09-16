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
                     Path("/w/session"), "immich")
    assert cmd[:2] == ["pi", "--model"] and cmd[2] == "upgrader/qwen"
    assert cmd[cmd.index("--thinking") + 1] == "high"
    assert cmd[cmd.index("--skill") + 1] == "/w/freepod/products/UPGRADING/SKILL.md"
    assert cmd[cmd.index("--session-dir") + 1] == "/w/session"
    assert "--no-context-files" in cmd and "-p" in cmd
    assert "immich" in cmd[-1]


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
