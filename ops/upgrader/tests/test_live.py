import json

from upgrader import live
from upgrader.live import Live, Session, Step, read, steps_of
from upgrader.redact import Redactor


def entry(role, content, **message):
    return {"type": "message", "message": {"role": role, "content": content, **message}}


def assistant_text(text):
    return entry("assistant", [{"type": "text", "text": text}])


def write(path, *entries, partial=b""):
    with path.open("ab") as f:
        for e in entries:
            f.write(json.dumps(e).encode() + b"\n")
        f.write(partial)


def session(tmp_path, redact=None):
    directory = tmp_path / "session"
    directory.mkdir(exist_ok=True)
    return Session(7, directory, redact or Redactor()), directory / "2026-09-15_x.jsonl"


def test_no_file_yet(tmp_path):
    s, _ = session(tmp_path)
    assert read(s, None) == ([], 0)


def test_opening_returns_the_latest_steps_and_the_end(tmp_path):
    s, path = session(tmp_path)
    write(path, *[assistant_text(f"step {i}") for i in range(50)])
    steps, offset = read(s, None)
    assert [x.text for x in steps] == [f"step {i}" for i in range(30, 50)]
    assert offset == path.stat().st_size


def test_opening_a_long_transcript_reads_only_its_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "TAIL_BYTES", 300)
    s, path = session(tmp_path)
    write(path, *[assistant_text(f"step {i:03}") for i in range(200)])
    steps, offset = read(s, None)
    assert steps and steps[-1].text == "step 199" and all(int(x.text[5:]) > 190 for x in steps)
    assert offset == path.stat().st_size


def test_a_refresh_returns_only_what_is_new(tmp_path):
    s, path = session(tmp_path)
    write(path, assistant_text("one"))
    _, offset = read(s, None)
    write(path, assistant_text("two"), assistant_text("three"))
    steps, offset2 = read(s, offset)
    assert [x.text for x in steps] == ["two", "three"]
    assert read(s, offset2) == ([], offset2)


def test_a_line_still_being_written_waits(tmp_path):
    s, path = session(tmp_path)
    write(path, assistant_text("done"), partial=b'{"type": "message", "mess')
    steps, offset = read(s, 0)
    assert [x.text for x in steps] == ["done"]
    assert read(s, offset) == ([], offset)
    with path.open("ab") as f:
        f.write(b'age": {"role": "assistant", "content": [{"type": "text", "text": "later"}]}}\n')
    assert [x.text for x in read(s, offset)[0]] == ["later"]


def test_a_line_larger_than_a_read_is_skipped_with_a_note(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "MAX_READ", 1024)
    s, path = session(tmp_path)
    big = entry("toolResult", [{"type": "text", "text": "x" * 5000}], toolCallId="t")
    write(path, big, assistant_text("after"))
    steps, offset = read(s, 0)
    assert steps == [Step("note", "a 4 KiB entry, too large to show")]
    assert [x.text for x in read(s, offset)[0]] == ["after"]


def test_a_rewritten_file_starts_again_from_its_end(tmp_path):
    s, path = session(tmp_path)
    write(path, *[assistant_text(f"old {i}") for i in range(30)])
    _, offset = read(s, None)
    path.write_bytes(b"")
    write(path, assistant_text("fresh"))
    steps, _ = read(s, offset)
    assert [x.text for x in steps] == ["fresh"]


def test_secrets_are_redacted_before_anything_is_shown(tmp_path):
    redact = Redactor({"INFERENCE_API_KEY": "sk-live-secret"})
    redact.add_token("ghs_minted_now")
    s, path = session(tmp_path, redact)
    write(path, entry("toolResult", [{"type": "text", "text": "GH_TOKEN=ghs_minted_now key=sk-live-secret"}]))
    [step] = read(s, 0)[0]
    assert "ghs_minted_now" not in step.text and "sk-live-secret" not in step.text
    assert "[redacted:github-token]" in step.text


def test_how_entries_become_steps():
    assert steps_of(entry("user", [{"type": "text", "text": "Run the skill"}])) == [Step("user", "Run the skill")]
    call = entry("assistant", [
        {"type": "thinking", "thinking": "Let me read the skill first.\nThen the catalog."},
        {"type": "text", "text": "Reading the skill."},
        {"type": "toolCall", "id": "a", "name": "bash", "arguments": {"command": "git fetch origin"}},
        {"type": "toolCall", "id": "b", "name": "read", "arguments": {"path": "AGENTS.md"}},
    ])
    assert steps_of(call) == [
        Step("thinking", "Let me read the skill first."),
        Step("text", "Reading the skill."),
        Step("tool", "git fetch origin", label="bash"),
        Step("tool", "AGENTS.md", label="read"),
    ]
    output = entry("toolResult", [{"type": "text", "text": "a\nb\nc\nd"}], toolCallId="a")
    assert steps_of(output) == [Step("result", "a\nb\n… +2 lines")]
    failed = entry("toolResult", [{"type": "text", "text": "fatal: no such ref"}], toolCallId="a", isError=True)
    assert steps_of(failed) == [Step("error", "fatal: no such ref")]
    assert steps_of({"type": "compaction"}) == [Step("note", "context compacted")]
    assert steps_of({"type": "model_change"}) == []


def test_the_registry_only_answers_for_the_running_product(tmp_path):
    registry = Live()
    s = Session(3, tmp_path, Redactor())
    assert registry.current(3) is None
    registry.start(s)
    assert registry.current(3) is s and registry.current(4) is None
    registry.stop(4)
    assert registry.current(3) is s
    registry.stop(3)
    assert registry.current(3) is None
