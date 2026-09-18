"""`freepod key`: registration, the local record, and recovery by fingerprint."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from freepod import EXIT_ERROR, EXIT_OK, EXIT_USAGE, UsageError
from freepod import keys as keys_module
from freepod.cli import main

from conftest import json_response

USER = {"id": 7, "email": "dev@example.com", "is_admin": False, "created_at": "2026-01-01T00:00:00"}


def generate(directory: Path, name: str = "id_ed25519", comment: str = "me@here") -> Path:
    """A real keypair on disk; returns the public key path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(path)],
        check=True,
        capture_output=True,
    )
    return Path(str(path) + ".pub")


def registered(public_path: Path, label="me@here", created="2026-08-27T10:00:00") -> dict:
    line = public_path.read_text().strip()
    return {
        "fingerprint": keys_module.fingerprint_for_line(line),
        "key_type": line.split()[0],
        "bits": 256,
        "label": label,
        "public_key": " ".join(line.split()[:2]),
        "created_at": created,
    }


class Platform:
    """A scripted `/ssh-keys` collection."""

    def __init__(self, keys=None):
        self.keys = list(keys or [])
        self.requests = []
        self.refuse = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        path = request.url.path
        if path == "/api/me":
            return json_response(200, USER)
        if request.method == "GET":
            return json_response(200, self.keys)
        if request.method == "POST":
            if self.refuse:
                return json_response(self.refuse[0], {"detail": self.refuse[1],
                                                      "code": self.refuse[2]})
            body = json.loads(request.content)
            line = body["public_key"]
            stored = {
                "fingerprint": keys_module.fingerprint_for_line(line),
                "key_type": line.split()[0],
                "bits": 256,
                "label": body.get("label") or line.split()[2] if len(line.split()) > 2 else "key",
                "public_key": " ".join(line.split()[:2]),
                "created_at": "2026-08-27T10:00:00",
            }
            self.keys.append(stored)
            return json_response(201, stored)
        if request.method == "DELETE":
            fingerprint = request.url.path.rsplit("/ssh-keys/", 1)[1]
            from urllib.parse import unquote

            wanted = unquote(fingerprint)
            before = len(self.keys)
            self.keys = [k for k in self.keys if k["fingerprint"] != wanted]
            if len(self.keys) == before:
                return json_response(404, {"detail": f"No SSH key with fingerprint {wanted}"})
            return httpx.Response(204)
        return json_response(405, {"detail": "no"})


class _StubSession:
    access_token = "token"

    def authenticate(self, force_login: bool = False, interactive: bool = True) -> None:
        return None


@pytest.fixture
def run_key(monkeypatch, tmp_path):
    """Drive `main(['key', ...])` against a scripted platform."""

    def go(platform, argv):
        from freepod.api import ApiClient
        from freepod.config import ENVIRONMENTS

        monkeypatch.setattr(
            "freepod.cli.Context.session", lambda self, force_flow=None: _StubSession()
        )
        monkeypatch.setattr(
            "freepod.cli.Context.client",
            lambda self, session: ApiClient(
                self.env,
                session,
                client=httpx.Client(transport=httpx.MockTransport(platform)),
                backoff_base=0,
            ),
        )
        return main(argv)

    return go


# --- Fingerprints ----------------------------------------------------------


def test_fingerprint_matches_ssh_keygen(tmp_path):
    pub = generate(tmp_path / "k")
    reported = subprocess.run(
        ["ssh-keygen", "-lf", str(pub)], check=True, capture_output=True, text=True
    ).stdout.split()[1]
    assert keys_module.fingerprint_for_file(pub) == reported


def test_fingerprint_of_nonsense_is_none():
    assert keys_module.fingerprint_for_line("not a key") is None


# --- list ------------------------------------------------------------------


def test_list_reports_no_keys_with_guidance(run_key, capsys):
    assert run_key(Platform([]), ["key", "list"]) == EXIT_OK
    out = capsys.readouterr()
    assert "No SSH keys are registered" in out.err
    assert "freepod key add" in out.err


def test_list_shows_fingerprint_and_label(run_key, tmp_path, capsys):
    pub = generate(tmp_path / "k")
    assert run_key(Platform([registered(pub)]), ["key", "list"]) == EXIT_OK
    out = capsys.readouterr().out
    assert keys_module.fingerprint_for_file(pub) in out
    assert "me@here" in out


def test_list_marks_the_key_this_machine_holds(run_key, tmp_path, isolated_home, capsys):
    pub = generate(isolated_home / ".ssh")
    platform = Platform([registered(pub)])
    keys_module.remember("prod", keys_module.fingerprint_for_file(pub), pub)

    assert run_key(platform, ["key", "list"]) == EXIT_OK
    marked = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("*")]
    assert len(marked) == 1


def test_list_does_not_mark_a_key_this_machine_cannot_offer(
    run_key, tmp_path, isolated_home, capsys
):
    """A record naming a file that is gone points at a key `shell` would refuse;
    marking it would tell the user the opposite."""
    pub = generate(tmp_path / "gone")
    platform = Platform([registered(pub)])
    keys_module.remember("prod", keys_module.fingerprint_for_file(pub), pub)
    pub.unlink()

    assert run_key(platform, ["key", "list"]) == EXIT_OK
    assert not [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("*")]


# --- add -------------------------------------------------------------------


def test_add_with_no_argument_generates_and_registers(run_key, isolated_home, capsys):
    platform = Platform([])
    assert run_key(platform, ["key", "add"]) == EXIT_OK

    generated = keys_module.generated_key_path()
    assert generated.is_file()
    assert oct(generated.stat().st_mode & 0o777) == "0o600"
    assert len(platform.keys) == 1
    assert keys_module.local_key("prod")["fingerprint"] == platform.keys[0]["fingerprint"]
    assert platform.keys[0]["fingerprint"] in capsys.readouterr().out


def test_generation_never_writes_to_dot_ssh(run_key, isolated_home):
    run_key(Platform([]), ["key", "add"])
    assert not (isolated_home / ".ssh").exists()


def test_add_states_the_key_is_the_ssh_credential(run_key, isolated_home, capsys):
    run_key(Platform([]), ["key", "add"])
    assert "SSH credential" in capsys.readouterr().err


def test_rerunning_add_does_not_generate_a_second_key(run_key, isolated_home, capsys):
    platform = Platform([])
    run_key(platform, ["key", "add"])
    first = platform.keys[0]["fingerprint"]

    assert run_key(platform, ["key", "add"]) == EXIT_OK
    assert len(platform.keys) == 1
    out = capsys.readouterr()
    assert "already holds a registered key" in out.err
    assert first in out.out


def test_add_registers_an_existing_public_key_and_records_it(run_key, tmp_path, isolated_home):
    pub = generate(tmp_path / "mine", comment="alice@laptop")
    platform = Platform([])
    assert run_key(platform, ["key", "add", str(pub)]) == EXIT_OK

    assert len(platform.keys) == 1
    recorded = keys_module.local_key("prod")
    assert recorded["path"] == str(pub)
    assert recorded["fingerprint"] == keys_module.fingerprint_for_file(pub)


def test_add_refuses_a_private_key_path(run_key, tmp_path, capsys):
    pub = generate(tmp_path / "mine")
    private = Path(str(pub)[: -len(".pub")])
    assert run_key(Platform([]), ["key", "add", str(private)]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "private key" in err
    assert f"{private}.pub" in err


def test_add_surfaces_the_platforms_refusal(run_key, tmp_path, capsys):
    pub = generate(tmp_path / "mine")
    platform = Platform([])
    platform.refuse = (400, "RSA keys must be at least 2048 bits.", "key_too_short")
    assert run_key(platform, ["key", "add", str(pub)]) == EXIT_ERROR
    assert "2048 bits" in capsys.readouterr().err


def test_add_rebinds_a_key_the_account_already_holds(run_key, tmp_path, isolated_home, capsys):
    """Naming an already-registered key is how an ambiguous machine is pointed
    at one; a duplicate must bind the record, not end the run."""
    pub = generate(tmp_path / "mine", comment="alice@laptop")
    platform = Platform([registered(pub)])
    platform.refuse = (409, "This key is already registered as 'alice@laptop'.", "duplicate_key")

    assert run_key(platform, ["key", "add", str(pub)]) == EXIT_OK

    recorded = keys_module.local_key("prod")
    assert recorded["path"] == str(pub)
    assert recorded["fingerprint"] == keys_module.fingerprint_for_file(pub)
    out = capsys.readouterr()
    assert "already registered" in out.err
    assert keys_module.fingerprint_for_file(pub) in out.out


def test_add_accepts_a_label(run_key, tmp_path):
    pub = generate(tmp_path / "mine")
    platform = Platform([])
    run_key(platform, ["key", "add", str(pub), "--label", "Work laptop"])
    body = json.loads(platform.requests[-1].content)
    assert body["label"] == "Work laptop"


def test_add_never_transmits_private_material(run_key, tmp_path):
    pub = generate(tmp_path / "mine")
    platform = Platform([])
    run_key(platform, ["key", "add", str(pub)])
    for request in platform.requests:
        assert b"PRIVATE KEY" not in request.content


# --- the local record ------------------------------------------------------


def test_record_holds_no_key_material(run_key, isolated_home):
    run_key(Platform([]), ["key", "add"])
    assert "PRIVATE KEY" not in keys_module.record_path().read_text()


def test_record_is_written_owner_only(run_key, isolated_home):
    run_key(Platform([]), ["key", "add"])
    assert oct(keys_module.record_path().stat().st_mode & 0o777) == "0o600"


def test_environments_do_not_share_a_record(tmp_path, isolated_home):
    pub = generate(tmp_path / "k")
    keys_module.remember("dev", keys_module.fingerprint_for_file(pub), pub)
    assert keys_module.local_key("dev") is not None
    assert keys_module.local_key("prod") is None


def test_record_survives_across_invocations(tmp_path, isolated_home):
    pub = generate(tmp_path / "k")
    keys_module.remember("prod", keys_module.fingerprint_for_file(pub), pub)
    assert keys_module.local_key("prod")["path"] == str(pub)


# --- recovery --------------------------------------------------------------


def test_recovery_adopts_a_single_matching_key(tmp_path, isolated_home):
    pub = generate(isolated_home / ".ssh", "id_ed25519")
    entry = registered(pub)
    assert keys_module.resolve_local_key("prod", [entry]) == pub
    assert keys_module.local_key("prod")["fingerprint"] == entry["fingerprint"]


def test_recovery_works_without_the_private_half(tmp_path, isolated_home):
    """An agent- or token-held key has only a `.pub` file on disk."""
    pub = generate(isolated_home / ".ssh", "id_ed25519")
    Path(str(pub)[: -len(".pub")]).unlink()
    entry = registered(pub)
    assert keys_module.resolve_local_key("prod", [entry]) == pub


def test_recovery_reports_when_nothing_matches(tmp_path, isolated_home):
    generate(isolated_home / ".ssh", "id_ed25519")
    other = generate(tmp_path / "elsewhere", "other")
    with pytest.raises(Exception) as exc:
        keys_module.resolve_local_key("prod", [registered(other)])
    assert "freepod key add" in str(exc.value)


def test_recovery_prefers_the_generated_key(tmp_path, isolated_home):
    """A tie between the client's own key and the user's is not a real
    question: both authenticate, and only one of them is this client's to bind."""
    generated = generate(keys_module.config_dir(), "id_ed25519")
    mine = generate(isolated_home / ".ssh", "id_rsa")

    chosen = keys_module.resolve_local_key("prod", [registered(generated), registered(mine)])

    assert chosen == generated
    assert keys_module.local_key("prod")["path"] == str(generated)


def test_recovery_asks_when_several_match(tmp_path, isolated_home):
    first = generate(isolated_home / ".ssh", "id_ed25519")
    second = generate(isolated_home / ".ssh", "id_other")
    with pytest.raises(Exception) as exc:
        keys_module.resolve_local_key("prod", [registered(first), registered(second)])
    message = str(exc.value)
    assert "several" in message
    assert str(first) in message and str(second) in message


def test_recovery_ignores_a_stale_record(tmp_path, isolated_home):
    stale = generate(tmp_path / "gone", "stale")
    live = generate(isolated_home / ".ssh", "id_ed25519")
    keys_module.remember("prod", keys_module.fingerprint_for_file(stale), stale)

    assert keys_module.resolve_local_key("prod", [registered(live)]) == live
    assert keys_module.local_key("prod")["path"] == str(live)


def test_candidates_are_public_files_only(tmp_path, isolated_home):
    generate(isolated_home / ".ssh", "id_ed25519")
    assert all(p.suffix == ".pub" for p in keys_module.candidate_public_keys())


# --- rm --------------------------------------------------------------------


def test_rm_removes_a_key_this_machine_does_not_hold(run_key, tmp_path):
    pub = generate(tmp_path / "elsewhere")
    entry = registered(pub)
    platform = Platform([entry])
    assert run_key(platform, ["key", "rm", entry["fingerprint"]]) == EXIT_OK
    assert platform.keys == []


def test_rm_clears_the_record_for_this_machines_key(run_key, tmp_path, isolated_home):
    pub = generate(isolated_home / ".ssh")
    entry = registered(pub)
    keys_module.remember("prod", entry["fingerprint"], pub)

    assert run_key(Platform([entry]), ["key", "rm", entry["fingerprint"]]) == EXIT_OK
    assert keys_module.local_key("prod") is None


def test_rm_of_another_machines_key_leaves_the_record(run_key, tmp_path, isolated_home):
    mine = generate(isolated_home / ".ssh")
    theirs = generate(tmp_path / "theirs", "other")
    keys_module.remember("prod", keys_module.fingerprint_for_file(mine), mine)

    entry = registered(theirs)
    assert run_key(Platform([entry, registered(mine)]), ["key", "rm", entry["fingerprint"]]) == EXIT_OK
    assert keys_module.local_key("prod") is not None


def test_rm_encodes_the_fingerprint(run_key, tmp_path):
    """Half of all fingerprints contain `/` or `+`."""
    entry = {"fingerprint": "SHA256:a/b+c", "key_type": "ssh-ed25519", "bits": 256,
             "label": "x", "public_key": "ssh-ed25519 AAAA", "created_at": "2026-08-27T10:00:00"}
    platform = Platform([entry])
    assert run_key(platform, ["key", "rm", entry["fingerprint"]]) == EXIT_OK
    assert platform.keys == []
    sent = platform.requests[-1].url
    assert "%2F" in str(sent) and "%2B" in str(sent)


def test_verbose_output_carries_no_private_material(run_key, tmp_path, isolated_home, capsys):
    """Including --verbose, which is where a client is most tempted to leak."""
    pub = generate(tmp_path / "mine")
    private = Path(str(pub)[: -len(".pub")]).read_text()
    secret_line = private.splitlines()[1]

    platform = Platform([])
    run_key(platform, ["--verbose", "key", "add", str(pub)])
    run_key(platform, ["--verbose", "key", "list"])

    out = capsys.readouterr()
    combined = out.out + out.err
    assert "PRIVATE KEY" not in combined
    assert secret_line not in combined


def test_generated_key_is_not_printed_in_verbose(run_key, isolated_home, capsys):
    run_key(Platform([]), ["--verbose", "key", "add"])
    private = keys_module.generated_key_path().read_text()
    out = capsys.readouterr()
    combined = out.out + out.err
    assert "PRIVATE KEY" not in combined
    assert private.splitlines()[1] not in combined


def test_rm_reports_a_missing_key(run_key, capsys):
    assert run_key(Platform([]), ["key", "rm", "SHA256:nope"]) == EXIT_ERROR
    assert "No SSH key" in capsys.readouterr().err
