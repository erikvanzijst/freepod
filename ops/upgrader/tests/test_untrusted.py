"""Reading what a session wrote without following it anywhere else (D3)."""

import os

import pytest

from upgrader import untrusted

ME = os.getuid()


@pytest.fixture
def root(tmp_path):
    (tmp_path / "out" / "immich").mkdir(parents=True)
    (tmp_path / "out" / "immich" / "result.json").write_text("{}")
    (tmp_path / "secret").write_text("the-key")
    return tmp_path


def test_a_plain_file(root):
    assert untrusted.read(root, "out/immich/result.json", ME, 100) == b"{}"


def test_a_link_as_the_file(root):
    (root / "out/immich/body.md").symlink_to(root / "secret")
    assert untrusted.read(root, "out/immich/body.md", ME, 100) is None


def test_a_link_on_the_way(root):
    (root / "elsewhere").mkdir()
    (root / "elsewhere" / "result.json").write_text("{}")
    (root / "out" / "nextcloud").symlink_to(root / "elsewhere")
    assert untrusted.read(root, "out/nextcloud/result.json", ME, 100) is None


def test_another_owner(root):
    assert untrusted.read(root, "out/immich/result.json", ME + 1, 100) is None


def test_a_fifo_is_neither_read_nor_waited_on(root):
    os.mkfifo(root / "out/immich/change.patch")
    assert untrusted.read(root, "out/immich/change.patch", ME, 100) is None


def test_a_directory(root):
    assert untrusted.read(root, "out/immich", ME, 100) is None


def test_too_large(root):
    assert untrusted.read(root, "out/immich/result.json", ME, 1) is None


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "out/../secret", ""])
def test_only_plain_relative_paths(root, path):
    with pytest.raises(ValueError):
        untrusted.read(root, path, ME, 100)


def test_find_skips_links_and_returns_relative_paths(root):
    session = root / "session"
    (session / "sub").mkdir(parents=True)
    (session / "b.jsonl").write_text("")
    (session / "sub" / "a.jsonl").write_text("")
    (session / "link.jsonl").symlink_to(root / "secret")
    (session / "linked-dir").symlink_to(root / "out")
    (session / "notes.txt").write_text("")
    assert untrusted.find(root, "session", ".jsonl", ME) == ["session/b.jsonl", "session/sub/a.jsonl"]
    assert untrusted.find(root, "session", ".jsonl", ME + 1) == []
    assert untrusted.find(root, "missing", ".jsonl", ME) == []
