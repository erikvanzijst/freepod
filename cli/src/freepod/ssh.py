"""SSH connection assembly for `shell`, `cp`, `db proxy` and `db shell`.

The client does not implement SSH; it drives the system `ssh`. This module is
the assembly those commands share: it names the one key to offer, pins the
edge's host key to the value the platform publishes, and builds the argument
list. It knows nothing about what the connection is *for* — a shell, a forward,
a database session — that is the caller's argument, appended last.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from . import FreepodError, HostKeyMismatch
from .config import config_dir, ensure_config_dir


def known_hosts_path() -> Path:
    """The client's own known_hosts, beside the token cache.

    Never the user's `~/.ssh/known_hosts`: a mismatch must be this client's
    failure to report, not a modification of a file the user curates, and a
    user who keeps their own entry for the edge should not have it overridden.
    """
    return config_dir() / "known_hosts"


def _require_tool(name: str, purpose: str) -> str:
    """One system tool, or a named-prerequisite error naming what to install.

    A missing OpenSSH tool is a prerequisite, not a fault of this client, so it
    is reported by name with the fix rather than surfacing as an unhandled
    `FileNotFoundError` deep in a subprocess call.
    """
    path = shutil.which(name)
    if path is None:
        raise FreepodError(
            f"the system `{name}` executable is required to {purpose} but was not "
            f"found on your PATH. Install OpenSSH — for example "
            f"`apt-get install openssh-client` or `brew install openssh` — and try again."
        )
    return path


def require_sftp() -> str:
    """The system `sftp`, which carries a copy."""
    return _require_tool("sftp", "copy files")


def require_ssh() -> str:
    """The system `ssh`, which opens a session."""
    return _require_tool("ssh", "open a session")


def _host_part(host: str, port: int) -> str:
    """The known_hosts spelling of one endpoint: port-qualified unless it is 22."""
    return host if port == 22 else f"[{host}]:{port}"


def known_hosts_entry(host: str, port: int, key_type: str, base64: str) -> str:
    """One OpenSSH known_hosts line for a published host key."""
    return f"{_host_part(host, port)} {key_type} {base64}"


def seed_known_hosts(host: str, port: int, key_type: str, base64: str) -> Path:
    """Record the published host key in the client's own known_hosts.

    Upserts the line for this endpoint — replacing a stale entry for the same
    host:port, leaving every other line untouched — and writes it owner-only in
    the 0700 config directory. The line is the value the platform published, so
    a later `StrictHostKeyChecking` connection accepts the real edge and refuses
    anything else.
    """
    target = _host_part(host, port)
    path = known_hosts_path()
    lines: List[str] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            if line.split()[0] == target:
                # A stale entry for this endpoint is replaced, not accumulated.
                continue
            lines.append(line)
    lines.append(known_hosts_entry(host, port, key_type, base64))

    ensure_config_dir()
    temporary = f"{path}.{os.getpid()}.tmp"
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)
    return path


def pin_edge(edge: dict) -> tuple[str, int, Path]:
    """Verify the edge's published host key and pin it in the client's store.

    Returns the `(host, port, known_hosts)` that `build_args` needs. The host
    key is a per-environment fact the platform already knows, so the one
    connection worth attacking — the first, which would otherwise trust whatever
    answers — is checked against it rather than guessed at. An environment that
    has not configured a key reports an empty `host_key`; that is refused as
    "cannot verify", never treated as permission to trust on first use.
    """
    host = edge.get("host")
    port = edge.get("port")
    if not host or not isinstance(port, int):
        raise FreepodError("the platform reported no SSH edge address; please report this.")
    host_key = edge.get("host_key") or {}
    if not host_key:
        raise FreepodError(
            "the platform has not published an SSH host key, so the edge "
            "cannot be verified. No connection was attempted. Please report "
            "this — the platform should know the answer."
        )
    # The platform publishes the edge's single host key, keyed by OpenSSH type.
    key_type, base64 = next(iter(host_key.items()))
    known_hosts = seed_known_hosts(host, port, key_type, base64)
    return host, port, known_hosts


def identity_file(key_path: Path) -> Path:
    """The file to hand to `-i`: the private half, where there is one on disk.

    The record is keyed by the public key, and a key held only in an agent or
    on a hardware token has no private file at all — for those, the public key
    is what selects the identity. But a file-based key must be offered by its
    private half: ssh refuses a world-readable public key as an identity, and a
    public key cannot sign. Where the private half sits beside the public one
    (the layout `freepod key add` writes), it is the one that authenticates.
    """
    if key_path.name.endswith(".pub"):
        private = key_path.with_name(key_path.name[: -len(".pub")])
        if private.is_file():
            return private
    return key_path


def edge_options(key_path: Path, known_hosts: Path) -> List[str]:
    """The options every connection to the edge carries, whichever tool makes it.

    Shared by `ssh` and `sftp`, which differ only in the program name and how
    they spell the port. Each option here looks like belt-and-braces until the
    day someone removes one, so each sits beside its reason.
    """
    return [
        # One identity, and only that one. The edge answers *every* offered key
        # with a partial success, so a client that offers several — which a
        # populated agent does by default — exhausts the server's authentication
        # budget and is refused before it reaches the right key.
        "-o",
        "IdentitiesOnly=yes",
        "-i",
        str(identity_file(key_path)),
        # Pin the edge to the key the platform published, in a store the user
        # does not curate. StrictHostKeyChecking means a mismatch is a refusal,
        # never a prompt, and never a key recorded on first use.
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "StrictHostKeyChecking=yes",
    ]


def build_sftp_args(
    *,
    user: str,
    host: str,
    port: int,
    key_path: Path,
    known_hosts: Path,
) -> List[str]:
    """The argv for one file transfer over the edge, reading its script on stdin.

    `sftp` spells the port `-P` and takes no remote command; the transfer is
    driven by batch lines rather than arguments, which is what keeps a path
    holding a space or a glob character out of argv parsing entirely.
    """
    return [
        "sftp",
        "-P",
        str(port),
        *edge_options(key_path, known_hosts),
        "-b",
        "-",
        f"{user}@{host}",
    ]


def build_args(
    *,
    user: str,
    host: str,
    port: int,
    key_path: Path,
    known_hosts: Path,
    command: Optional[List[str]] = None,
    local_forward: Optional[str] = None,
    tty: bool = False,
) -> List[str]:
    """The argv for one connection to the edge.

    Exactly one identity is offered, and the edge's host key is pinned to the
    value the platform published. The options that make a host-key mismatch a
    refusal rather than a prompt sit beside their reason, because each looks
    like belt-and-braces until the day someone removes one.
    """
    args = ["ssh", "-p", str(port), *edge_options(key_path, known_hosts)]
    if tty:
        # Force a remote tty. The sidecar runs under a ForceCommand, which does
        # not allocate a pseudo-terminal on its own, so an interactive session
        # comes up without one — and a database client that reads no terminal
        # sees no prompt — unless we ask for it here.
        args.append("-tt")
    args.append(f"{user}@{host}")
    if local_forward is not None:
        # -N: no remote command; the forward is the whole point of the session.
        args += ["-N", "-L", local_forward]
    if command:
        args += list(command)
    return args


#: The one line of ssh's stderr that identifies a host-key mismatch.
_HOST_KEY_MISMATCH = "host key verification failed"


def is_host_key_mismatch(stderr: Optional[object]) -> bool:
    """Whether ssh's failure was a host-key mismatch, not an auth or network one.

    Takes whatever `subprocess` hands back — a str, bytes, or None when stderr
    was not captured — and recognizes the mismatch in any of them.
    """
    if stderr is None:
        return False
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    return _HOST_KEY_MISMATCH in stderr.lower()


#: The one phrase ssh's stderr carries when the far end declines a forward.
#: It is the refusal that reads like an authorization failure in practice: the
#: key was accepted, the channel opened, and the destination was not permitted.
_FORWARD_REFUSED = "administratively prohibited"


def is_forward_refused(stderr: Optional[object]) -> bool:
    """Whether ssh's failure was a refused forward, not an auth or network one.

    A forward is refused *after* authentication, so the two failures are
    distinguishable in ssh's own output: an authentication refusal says
    "Permission denied", a forward refusal says the destination was
    administratively prohibited. Naming the cause the client can support —
    rather than guessing — is what keeps the two from blurring into one.
    """
    if stderr is None:
        return False
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    return _FORWARD_REFUSED in stderr.lower()


def run(args: List[str], **subprocess_kwargs) -> subprocess.CompletedProcess:
    """Run one assembled connection, surfacing a host-key mismatch as its own error.

    Any other non-zero exit is returned to the caller to interpret: an
    authentication refusal is uniform by design and says only "no", so nothing
    here may name a cause it cannot support. A mismatch is the one failure ssh
    itself identifies, so it is raised rather than returned.
    """
    proc = subprocess.run(args, **subprocess_kwargs)
    if proc.returncode != 0 and is_host_key_mismatch(proc.stderr):
        raise HostKeyMismatch(
            "the SSH edge presented a host key that does not match the one the "
            "platform publishes. The connection was refused and nothing was "
            "recorded. If you did not change the edge's host key, report this — "
            "it means something else is answering where the edge should be."
        )
    return proc


def run_interactive(args: List[str]) -> int:
    """Run a session on the user's own terminal; return its exit code.

    An interactive session or a single remote command alike: both own the
    foreground, so nothing is captured. The user's own stdin, stdout and stderr
    are the session's, which is what lets a command be redirected or piped on
    either side, and a host-key mismatch reach the user in real time. The exit
    code is handed back for the caller to propagate; there is no captured
    stream to re-classify here — whatever ssh said, the user read.
    """
    return subprocess.run(args).returncode
