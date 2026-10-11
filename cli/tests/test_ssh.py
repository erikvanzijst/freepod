"""SSH connection assembly: the key offered, the edge verified, the argv built.

Covers tasks 2.1-2.5 of `cli-ssh-access`. The commands that consume this
assembly (`shell`, `db proxy`, `db shell`) are later tasks; here the pieces are
tested in isolation, with `subprocess` and `shutil.which` stubbed so no real
connection is attempted and no real `ssh` is required to be present.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from freepod import FreepodError, HostKeyMismatch
from freepod import keys as keys_module
from freepod import ssh as ssh_module
from freepod.config import config_dir, token_cache_path


def make_key(directory: Path, name: str = "id_ed25519") -> Path:
    """A real Ed25519 keypair on disk; returns the public key path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "me@here", "-f", str(path)],
        check=True,
        capture_output=True,
    )
    return Path(str(path) + ".pub")


def registered(public_path: Path) -> dict:
    line = public_path.read_text().strip()
    return {
        "fingerprint": keys_module.fingerprint_for_line(line),
        "key_type": line.split()[0],
        "bits": 256,
        "label": "me@here",
        "public_key": " ".join(line.split()[:2]),
        "created_at": "2026-08-27T10:00:00",
    }


# --- 2.5: the ssh prerequisite ---------------------------------------------


def test_require_ssh_returns_the_executable(monkeypatch):
    monkeypatch.setattr(ssh_module.shutil, "which", lambda name: "/usr/bin/ssh")
    assert ssh_module.require_ssh() == "/usr/bin/ssh"


def test_require_ssh_names_the_prerequisite_when_missing(monkeypatch):
    monkeypatch.setattr(ssh_module.shutil, "which", lambda name: None)
    with pytest.raises(Exception) as exc:
        ssh_module.require_ssh()
    message = str(exc.value)
    assert "ssh" in message
    assert "openssh" in message.lower()
    assert "PATH" in message


# --- 2.3: the client's own known_hosts -------------------------------------


def test_known_hosts_lives_beside_the_token_cache():
    assert ssh_module.known_hosts_path().parent == token_cache_path().parent
    assert ssh_module.known_hosts_path().parent == config_dir()


def test_seed_writes_the_published_key_for_port_22():
    path = ssh_module.seed_known_hosts("freepod.eu", 22, "ssh-ed25519", "AAAAhostkey")
    assert path.read_text().splitlines() == ["freepod.eu ssh-ed25519 AAAAhostkey"]


def test_seed_qualifies_the_port_when_it_is_not_22():
    path = ssh_module.seed_known_hosts("freepod.eu", 2222, "ssh-ed25519", "AAAAhostkey")
    assert path.read_text().splitlines() == ["[freepod.eu]:2222 ssh-ed25519 AAAAhostkey"]


def test_seed_replaces_a_stale_entry_for_the_same_endpoint():
    ssh_module.seed_known_hosts("freepod.eu", 22, "ssh-ed25519", "OLDkey")
    path = ssh_module.seed_known_hosts("freepod.eu", 22, "ssh-ed25519", "NEWkey")
    assert path.read_text().splitlines() == ["freepod.eu ssh-ed25519 NEWkey"]


def test_seed_keeps_other_endpoints_intact():
    ssh_module.seed_known_hosts("freepod.eu", 22, "ssh-ed25519", "PRODkey")
    path = ssh_module.seed_known_hosts("dev.freepod.eu", 22, "ssh-ed25519", "DEVkey")
    lines = path.read_text().splitlines()
    assert "freepod.eu ssh-ed25519 PRODkey" in lines
    assert "dev.freepod.eu ssh-ed25519 DEVkey" in lines
    assert len(lines) == 2


def test_seed_is_written_owner_only():
    path = ssh_module.seed_known_hosts("freepod.eu", 22, "ssh-ed25519", "AAAAhostkey")
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_seed_never_touches_the_users_known_hosts(isolated_home):
    ssh_module.seed_known_hosts("freepod.eu", 22, "ssh-ed25519", "AAAAhostkey")
    assert not (isolated_home / ".ssh" / "known_hosts").exists()
    assert not (isolated_home / ".ssh").exists()


# --- pin_edge: verify the published key before connecting ------------------


def test_pin_edge_seeds_the_store_and_returns_the_target():
    host, port, store = ssh_module.pin_edge(
        {"host": "freepod.eu", "port": 22, "host_key": {"ssh-ed25519": "AAAAedge"}}
    )
    assert (host, port) == ("freepod.eu", 22)
    assert store.read_text().splitlines() == ["freepod.eu ssh-ed25519 AAAAedge"]


def test_pin_edge_refuses_an_unpublished_key():
    """An empty host_key is 'cannot verify', never trust-on-first-use."""
    with pytest.raises(FreepodError) as exc:
        ssh_module.pin_edge({"host": "freepod.eu", "port": 22, "host_key": {}})
    assert "cannot be verified" in str(exc.value)


def test_pin_edge_refuses_a_missing_address():
    with pytest.raises(FreepodError):
        ssh_module.pin_edge({"host": "", "port": 22, "host_key": {"ssh-ed25519": "AAAA"}})


# --- 2.2: exactly one identity offered -------------------------------------


def _args(**overrides):
    params = dict(
        user="myapp",
        host="freepod.eu",
        port=22,
        key_path=Path("/keys/id_ed25519.pub"),
        known_hosts=Path("/config/known_hosts"),
    )
    params.update(overrides)
    return ssh_module.build_args(**params)


def test_offers_exactly_one_identity():
    args = _args()
    assert args.count("-i") == 1
    identity = args[args.index("-i") + 1]
    assert identity == "/keys/id_ed25519.pub"
    assert "IdentitiesOnly=yes" in args


def test_the_identity_is_the_private_half_where_one_exists(isolated_home):
    pub = make_key(isolated_home / "keys", "id_ed25519")
    private = pub.with_name(pub.name[: -len(".pub")])
    assert ssh_module.identity_file(pub) == private
    # And build_args offers that private half, not the world-readable public one.
    args = _args(key_path=pub)
    assert args[args.index("-i") + 1] == str(private)


def test_the_identity_is_the_public_key_when_no_private_half_exists():
    """An agent or hardware-token key has no private file; the public key selects it."""
    assert ssh_module.identity_file(Path("/keys/id_ed25519.pub")) == Path("/keys/id_ed25519.pub")


def test_pins_the_edge_to_the_client_store():
    args = _args()
    assert 'UserKnownHostsFile="/config/known_hosts"' in args
    assert "StrictHostKeyChecking=yes" in args
    # The user's own known_hosts is neither named nor the default.
    assert not any(".ssh/known_hosts" in a for a in args)


def test_targets_the_edge_with_the_deployment_as_user():
    args = _args()
    assert "myapp@freepod.eu" in args
    assert "-p" in args and args[args.index("-p") + 1] == "22"


def test_forward_is_a_no_remote_command_tunnel():
    args = _args(local_forward="127.0.0.1:5432:caelus-db:5432")
    # -N: the forward is the whole point, so no remote command runs.
    assert "-N" in args
    assert "-L" in args and args[args.index("-L") + 1] == "127.0.0.1:5432:caelus-db:5432"
    # Still a connection to the edge; the forward just changes what it carries.
    assert "myapp@freepod.eu" in args


def test_remote_command_is_appended_last():
    args = _args(command=["psql", "-d", "app"])
    assert args[-3:] == ["psql", "-d", "app"]
    assert "myapp@freepod.eu" in args


def test_tty_is_requested_only_when_asked():
    assert "-tt" not in _args()
    assert "-tt" in _args(tty=True)


def test_tty_sits_with_the_options_before_the_target():
    """-tt is an option, so it precedes user@host like the rest."""
    args = _args(tty=True)
    assert args.index("-tt") < args.index("myapp@freepod.eu")


# --- 2.4: the edge is verified, not trusted --------------------------------


def test_mismatch_is_recognised_from_stderr():
    assert ssh_module.is_host_key_mismatch("Host key verification failed.")
    assert ssh_module.is_host_key_mismatch(b"Host key verification failed.")
    assert not ssh_module.is_host_key_mismatch("Permission denied (publickey).")
    assert not ssh_module.is_host_key_mismatch(None)


def _completed(returncode: int, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["ssh"], returncode=returncode, stderr=stderr)


def test_run_raises_on_a_host_key_mismatch(monkeypatch):
    fake = lambda *a, **k: _completed(255, "Host key verification failed.")
    monkeypatch.setattr(ssh_module.subprocess, "run", fake)
    with pytest.raises(HostKeyMismatch) as exc:
        ssh_module.run(["ssh", "x@y"], capture_output=True)
    assert "does not match" in str(exc.value)


def test_run_returns_other_failures_to_the_caller(monkeypatch):
    """An authentication refusal is uniform and says only "no" — not a mismatch."""
    proc = _completed(255, "Permission denied (publickey).")
    monkeypatch.setattr(ssh_module.subprocess, "run", lambda *a, **k: proc)
    assert ssh_module.run(["ssh", "x@y"], capture_output=True) is proc


def test_run_returns_success(monkeypatch):
    proc = _completed(0)
    monkeypatch.setattr(ssh_module.subprocess, "run", lambda *a, **k: proc)
    assert ssh_module.run(["ssh", "x@y"], capture_output=True) is proc


def test_run_interactive_returns_the_exit_code(monkeypatch):
    proc = _completed(3)
    monkeypatch.setattr(ssh_module.subprocess, "run", lambda *a, **k: proc)
    assert ssh_module.run_interactive(["ssh", "x@y"]) == 3


def test_run_interactive_captures_nothing(monkeypatch):
    """The session owns the terminal, so nothing is captured or re-classified."""
    seen = {}

    def fake(args, **kwargs):
        seen.update(kwargs)
        return _completed(0)

    monkeypatch.setattr(ssh_module.subprocess, "run", fake)
    ssh_module.run_interactive(["ssh", "x@y"])
    assert "capture_output" not in seen
    assert "stdout" not in seen
    assert "stderr" not in seen


def test_nothing_is_recorded_when_the_key_is_wrong():
    """StrictHostKeyChecking is what keeps a wrong key out of the store."""
    args = _args()
    assert "StrictHostKeyChecking=yes" in args
    assert "accept-new" not in " ".join(args)
    assert "StrictHostKeyChecking=no" not in args


# --- 2.1: the recorded key is used directly, no search ---------------------


def test_recorded_key_is_used_without_searching(isolated_home, monkeypatch):
    pub = make_key(isolated_home / ".ssh", "id_ed25519")
    entry = registered(pub)
    keys_module.remember("prod", entry["fingerprint"], pub)

    def no_search(_registered):
        raise AssertionError("recover() must not run when a valid record exists")

    monkeypatch.setattr(keys_module, "recover", no_search)
    assert keys_module.resolve_local_key("prod", [entry]) == pub


def test_missing_record_falls_back_to_fingerprint_recovery(isolated_home):
    pub = make_key(isolated_home / ".ssh", "id_ed25519")
    entry = registered(pub)
    assert keys_module.resolve_local_key("prod", [entry]) == pub
    # And it is recorded, so the next invocation needs no search.
    assert keys_module.local_key("prod")["path"] == str(pub)


def test_a_known_hosts_path_with_a_space_stays_one_value():
    """ssh splits this option on whitespace; a Windows profile often has a space."""
    value = ssh_module._config_path(Path("/Users/Jan de Vries/.config/freepod/known_hosts"))

    assert value == '"/Users/Jan de Vries/.config/freepod/known_hosts"'


def test_a_windows_known_hosts_path_uses_forward_slashes():
    from pathlib import PureWindowsPath

    value = ssh_module._config_path(PureWindowsPath(r"C:\Users\Jan de Vries\known_hosts"))

    assert value == '"C:/Users/Jan de Vries/known_hosts"'
