"""`freepod cp`: which side is the deployment's, and the refusals made first.

The transfer itself is `sftp`'s, so it is stubbed to capture the argv and the
batch script it is fed; everything up to that call, including every refusal
that needs no connection, is real. The copy running end to end against a live
deployment is what `openspec/changes/archive/2026-09-03-unified-ssh-sidecar/tasks.md` § 6.2 covers.
"""

from __future__ import annotations

import httpx
import pytest

from freepod import EXIT_ERROR, EXIT_OK, EXIT_USAGE
from freepod import copy as copy_module
from freepod import keys as keys_module
from freepod.cli import main

from test_shell import (
    DEPLOYMENT_ID,
    DEPLOYMENT_NAME,
    EDGE,
    Platform,
    key_entry,
    project_at,
)


@pytest.fixture
def no_sftp(monkeypatch):
    """Neither prerequisite nor execution touches the outside world."""
    monkeypatch.setattr("freepod.ssh.require_sftp", lambda: "/usr/bin/sftp")


@pytest.fixture
def capture_transfer(monkeypatch):
    """Record the argv and the batch script, and report a clean transfer."""
    captured: dict = {}

    def fake_run(args, script):
        captured.update(args=args, script=script)
        return 0

    monkeypatch.setattr("freepod.copy.run", fake_run)
    return captured


def ready(tmp_path, monkeypatch, stub_api):
    project_at(tmp_path)
    keys_module.generate_keypair(keys_module.generated_key_path())
    stub_api(
        Platform(
            deployment={
                "id": DEPLOYMENT_ID,
                "name": DEPLOYMENT_NAME,
                "status": "ready",
            },
            keys=[key_entry()],
        )
    )
    monkeypatch.chdir(tmp_path)


# --- which side is the deployment's ----------------------------------------

def test_the_marked_side_decides_the_direction_and_the_connection_is_the_shells(
    stub_api, cached_credential, no_sftp, capture_transfer, tmp_path, monkeypatch
):
    ready(tmp_path, monkeypatch, stub_api)
    (tmp_path / "report.csv").write_text("a,b\n")

    with pytest.raises(SystemExit) as exc:
        main(["cp", "report.csv", ":/app/report.csv"])
    assert exc.value.code == EXIT_OK

    args = capture_transfer["args"]
    assert args[0] == "sftp"
    assert f"{DEPLOYMENT_ID}@{EDGE['host']}" in args
    # sftp spells the port -P, and reads its script rather than taking a command.
    assert args[args.index("-P") + 1] == str(EDGE["port"])
    assert args[args.index("-b") + 1] == "-"
    # The same connection assembly every other SSH command uses.
    assert "IdentitiesOnly=yes" in args
    assert args.count("-i") == 1
    assert args[args.index("-i") + 1] == str(keys_module.generated_key_path())
    assert any(a.startswith("UserKnownHostsFile=") for a in args)
    assert "StrictHostKeyChecking=yes" in args
    # No terminal is allocated for a transfer; a pty would corrupt the stream.
    assert "-tt" not in args and "-t" not in args

    assert capture_transfer["script"].startswith("put -r ")


def test_the_direction_reverses_with_the_marking(
    stub_api, cached_credential, no_sftp, capture_transfer, tmp_path, monkeypatch
):
    ready(tmp_path, monkeypatch, stub_api)

    with pytest.raises(SystemExit) as exc:
        main(["cp", ":/app/out.log", "out.log"])
    assert exc.value.code == EXIT_OK
    assert capture_transfer["script"].startswith("get -r ")


def test_the_long_form_names_this_projects_deployment(
    stub_api, cached_credential, no_sftp, capture_transfer, tmp_path, monkeypatch
):
    ready(tmp_path, monkeypatch, stub_api)

    with pytest.raises(SystemExit) as exc:
        main(["cp", f"{DEPLOYMENT_ID}:/app/out.log", "out.log"])
    assert exc.value.code == EXIT_OK
    assert '"/app/out.log"' in capture_transfer["script"]


def test_a_local_path_containing_a_colon_stays_local(
    stub_api, cached_credential, no_sftp, capture_transfer, tmp_path, monkeypatch
):
    """A prefix rule, not `scp`'s 'colon before the first slash'."""
    ready(tmp_path, monkeypatch, stub_api)
    (tmp_path / "notes:draft.txt").write_text("draft\n")

    with pytest.raises(SystemExit) as exc:
        main(["cp", "notes:draft.txt", ":/app/notes.txt"])
    assert exc.value.code == EXIT_OK
    assert '"notes:draft.txt"' in capture_transfer["script"]
    assert capture_transfer["script"].startswith("put -r ")


# --- the refusals, all of them before a connection -------------------------

def test_neither_side_marked_is_refused_by_name(
    stub_api, cached_credential, no_sftp, capture_transfer, tmp_path, monkeypatch, capsys
):
    ready(tmp_path, monkeypatch, stub_api)
    (tmp_path / "a.txt").write_text("a\n")

    assert main(["cp", "a.txt", "b.txt"]) == EXIT_USAGE
    assert "neither path names the deployment" in capsys.readouterr().err
    assert "args" not in capture_transfer


def test_both_sides_marked_is_refused_by_name(
    stub_api, cached_credential, no_sftp, capture_transfer, tmp_path, monkeypatch, capsys
):
    ready(tmp_path, monkeypatch, stub_api)

    assert main(["cp", ":/app/a", ":/app/b"]) == EXIT_USAGE
    assert "does not copy between deployments" in capsys.readouterr().err
    assert "args" not in capture_transfer


def test_a_marked_path_naming_another_deployment_is_refused(
    stub_api, cached_credential, no_sftp, capture_transfer, tmp_path, monkeypatch, capsys
):
    """Refused rather than resolved: this command acts on one deployment, and
    quietly ignoring the name it was given would make it look otherwise."""
    ready(tmp_path, monkeypatch, stub_api)

    assert main(["cp", "some-other-app-9x8y7z:/app/out.log", "out.log"]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "some-other-app-9x8y7z" in err
    assert DEPLOYMENT_ID in err
    assert "args" not in capture_transfer


def test_a_missing_local_source_is_caught_before_connecting(
    stub_api, cached_credential, no_sftp, capture_transfer, tmp_path, monkeypatch, capsys
):
    ready(tmp_path, monkeypatch, stub_api)

    assert main(["cp", "absent.txt", ":/app/absent.txt"]) == EXIT_ERROR
    assert "does not exist on this machine" in capsys.readouterr().err
    assert "args" not in capture_transfer


def test_an_unwritable_local_destination_is_caught_before_connecting(
    stub_api, cached_credential, no_sftp, capture_transfer, tmp_path, monkeypatch, capsys
):
    ready(tmp_path, monkeypatch, stub_api)

    assert main(["cp", ":/app/out.log", "no/such/dir/out.log"]) == EXIT_ERROR
    assert "nothing can be written there" in capsys.readouterr().err
    assert "args" not in capture_transfer


def test_missing_sftp_is_a_named_prerequisite(
    stub_api, cached_credential, capture_transfer, tmp_path, monkeypatch, capsys
):
    ready(tmp_path, monkeypatch, stub_api)
    (tmp_path / "a.txt").write_text("a\n")
    monkeypatch.setattr("shutil.which", lambda name: None)

    assert main(["cp", "a.txt", ":/app/a.txt"]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "sftp" in err and "openssh" in err.lower()
    assert "args" not in capture_transfer


# --- a failed copy is never a successful one -------------------------------

def test_an_incomplete_transfer_exits_non_zero_and_reports_no_success(
    stub_api, cached_credential, no_sftp, tmp_path, monkeypatch, capsys
):
    ready(tmp_path, monkeypatch, stub_api)
    (tmp_path / "a.txt").write_text("a\n")
    monkeypatch.setattr("freepod.copy.run", lambda args, script: 1)

    with pytest.raises(SystemExit) as exc:
        main(["cp", "a.txt", ":/app/a.txt"])
    assert exc.value.code == 1
    assert "Copied" not in capsys.readouterr().err


def test_a_completed_transfer_says_so(
    stub_api, cached_credential, no_sftp, capture_transfer, tmp_path, monkeypatch, capsys
):
    ready(tmp_path, monkeypatch, stub_api)
    (tmp_path / "a.txt").write_text("a\n")

    with pytest.raises(SystemExit) as exc:
        main(["cp", "a.txt", ":/app/a.txt"])
    assert exc.value.code == EXIT_OK
    # A completion notice, not a result: it goes to the progress channel, which
    # `--quiet` suppresses. The result of a copy is the file.
    assert "Copied" in capsys.readouterr().err


# --- the batch script ------------------------------------------------------

def test_the_transfer_always_recurses_and_never_preserves_timestamps():
    """`-r` is given for every copy and asked for by nobody: the protocol
    recurses and a single file is unaffected. `-p` is not, because it would
    preserve timestamps as well as modes and only modes are promised."""
    line = copy_module.batch("tree", "/app/tree", upload=True)
    assert line.startswith("put -r ")
    assert " -p " not in line


def test_a_path_holding_syntax_reaches_the_far_end_whole():
    """sftp parses its batch lines and globs their arguments, so a filename
    holding a quote or a bracket must arrive as one literal argument."""
    quoted = copy_module.quote('od[d] "name"*.txt')
    assert quoted.startswith('"') and quoted.endswith('"')
    for character in '\\"*?[':
        assert f"\\{character}" in quoted or character not in 'od[d] "name"*.txt'
