"""Reading what a session wrote without letting it point the service at anything else (D3).

Every path is walked from a directory the service owns, one component at a time and without
following a link, and only a regular file the session user owns is read. A hard link to one of
the service's files keeps the service as its owner, so it is refused like a symbolic link.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def _parts(relpath: str) -> list[str]:
    parts = PurePosixPath(relpath).parts
    if not parts or any(p in ("", ".", "..", "/") for p in parts):
        raise ValueError(f"not a plain relative path: {relpath!r}")
    return list(parts)


def _walk(root: Path, dirs: list[str]) -> int | None:
    fd = os.open(root, _DIR)
    try:
        for name in dirs:
            child = os.open(name, _DIR, dir_fd=fd)
            os.close(fd)
            fd = child
    except OSError:
        os.close(fd)
        return None
    return fd


def open_file(root: Path, relpath: str, owner: int) -> int | None:
    """A descriptor on `root/relpath`, or None when it is not a regular file `owner` owns reached
    without a link. The caller closes it."""
    *dirs, name = _parts(relpath)
    parent = _walk(root, dirs)
    if parent is None:
        return None
    try:
        fd = os.open(name, _FILE, dir_fd=parent)
    except OSError:
        return None
    finally:
        os.close(parent)
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != owner:
        os.close(fd)
        return None
    os.set_blocking(fd, True)
    return fd


def read(root: Path, relpath: str, owner: int, limit: int) -> bytes | None:
    """The file's bytes, or None when it is missing, refused, or larger than `limit`."""
    fd = open_file(root, relpath, owner)
    if fd is None:
        return None
    with os.fdopen(fd, "rb") as f:
        data = f.read(limit + 1)
    return None if len(data) > limit else data


def find(root: Path, relpath: str, suffix: str, owner: int, depth: int = 3) -> list[str]:
    """The regular files ending in `suffix` that `owner` owns under `root/relpath`, as paths
    relative to `root`, sorted. Links are neither followed nor returned."""
    found: list[str] = []

    def visit(fd: int, prefix: str, level: int) -> None:
        with os.scandir(fd) as entries:
            for entry in entries:
                path = f"{prefix}/{entry.name}"
                if entry.is_dir(follow_symlinks=False) and level < depth:
                    try:
                        child = os.open(entry.name, _DIR, dir_fd=fd)
                    except OSError:
                        continue
                    try:
                        visit(child, path, level + 1)
                    finally:
                        os.close(child)
                elif entry.name.endswith(suffix) and entry.is_file(follow_symlinks=False) \
                        and entry.stat(follow_symlinks=False).st_uid == owner:
                    found.append(path)

    fd = _walk(root, _parts(relpath))
    if fd is None:
        return []
    try:
        visit(fd, relpath, 1)
    finally:
        os.close(fd)
    return sorted(found)
