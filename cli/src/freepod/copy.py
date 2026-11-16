"""Copying files between the local machine and a deployment.

Spec: openspec/specs/cli-ssh-access/spec.md · Rationale: the archived
`unified-ssh-sidecar` change under openspec/changes/archive/, design.md § D5.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from freepod import FreepodError, UsageError
from freepod import ssh as ssh_module


#: What marks a path as the deployment's. A bare colon, or the deployment's own
#: name and one -- a *prefix* rule, so a local file called `notes:draft.txt` is
#: never mistaken for a remote path (D5).
MARKER = ":"


def split_marker(path: str, deployment: str) -> Optional[str]:
    """The remote path `path` names, or None when it names a local one."""
    if path.startswith(MARKER):
        return path[len(MARKER) :]
    prefix = f"{deployment}{MARKER}"
    if path.startswith(prefix):
        return path[len(prefix) :]
    return None


def _named_deployment(path: str) -> Optional[str]:
    """The name in a `<name>:` prefix, when the path plausibly carries one.

    Only ever used to explain a refusal. A path whose colon follows a path
    separator is somebody's file, not a mis-typed deployment.
    """
    head, sep, _rest = path.partition(MARKER)
    if not sep or not head or "/" in head:
        return None
    return head


def direction(source: str, destination: str, deployment: str) -> Tuple[str, str, bool]:
    """`(local, remote, upload)` for one copy, or a refusal naming the ambiguity.

    Exactly one side is the deployment's, and which one decides the direction --
    there is no flag to set inconsistently with the paths.
    """
    remote_source = split_marker(source, deployment)
    remote_destination = split_marker(destination, deployment)

    if remote_source is not None and remote_destination is not None:
        raise UsageError(
            "both paths name the deployment, and `freepod cp` does not copy "
            "between deployments.\n  Mark exactly one side with ':'."
        )
    if remote_source is None and remote_destination is None:
        for side, path in (("source", source), ("destination", destination)):
            if (named := _named_deployment(path)) is not None:
                raise UsageError(
                    f"the {side} '{path}' names '{named}', which is not this "
                    f"project's deployment '{deployment}'.\n"
                    f"  This command acts on '{deployment}' alone; write ':{path.partition(MARKER)[2]}' "
                    f"to name it."
                )
        raise UsageError(
            "neither path names the deployment, so this is a local copy your "
            "own shell already does.\n"
            "  Mark the deployment's side with ':', as in "
            "`freepod cp report.csv :/app/report.csv`."
        )
    if remote_source is not None:
        return destination, remote_source, False
    return source, remote_destination, True


def check_local(local: str, *, upload: bool) -> None:
    """The refusals visible without a connection, made before spending one.

    A predictable failure should not cost a round trip, and should not read as
    a platform problem.
    """
    path = Path(local)
    if upload:
        if not path.exists():
            raise FreepodError(f"'{local}' does not exist on this machine, so there is nothing to copy.")
        return
    parent = path.parent if path.parent != Path("") else Path(".")
    if path.is_dir():
        parent = path
    if not parent.exists():
        raise FreepodError(f"'{parent}' does not exist on this machine, so nothing can be written there.")


#: Characters the far end's batch parser would otherwise read as syntax. sftp
#: globs its arguments, so a local file holding `[` or `*` needs escaping too.
_ESCAPE = '\\"*?['


def quote(path: str) -> str:
    """One path as a single sftp batch argument, syntax and globbing disarmed."""
    return '"' + "".join("\\" + c if c in _ESCAPE else c for c in path) + '"'


def batch(local: str, remote: str, *, upload: bool) -> str:
    """The one sftp batch line that carries the copy.

    `-r` is always given and never asked for: the protocol recurses, a single
    file is unaffected by it, and `kubectl cp` -- one container you own -- has
    no such flag either. It is not `-p`: that would preserve timestamps as well
    as modes, and only modes are promised.
    """
    verb = "put" if upload else "get"
    first, second = (local, remote) if upload else (remote, local)
    return f"{verb} -r {quote(first)} {quote(second)}\n"


def run(args: List[str], script: str) -> int:
    """Drive one transfer, returning sftp's own exit code.

    stderr is the user's, so whatever sftp said about a path it could not read
    reaches them as it was written, and a host-key mismatch is raised by
    `ssh.run` as the one failure the tooling identifies for us. Its stdout is
    not: in batch mode that is the script echoed back and a line per directory
    entered, which is this command's own plumbing rather than anything the user
    asked to see. Nothing is transferred on it -- the payload rides the
    protocol, not the stream.
    """
    proc = ssh_module.run(args, input=script, text=True, stdout=subprocess.DEVNULL)
    return proc.returncode
