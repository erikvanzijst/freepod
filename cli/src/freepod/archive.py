"""Turning a project directory into a deterministic tar stream.

Four levels of ignore precedence, last match wins:

1. **Hard excludes**, never overridable: `.git/`.
2. **Built-in defaults**: dependency, build-output, cache, and editor artifacts.
3. **`.gitignore`**, honored by default including nested ones.
4. **`.freepodignore`**, applied last, so `!` negations can re-include anything
   except a hard exclude.

Matching is `pathspec`; the walk is ours. The walk owns the two things
`pathspec` does not do: per-directory layering (git evaluates each `.gitignore`
relative to its own directory, so we carry a stack of specs rewritten relative
to the project root) and **pruning** — not descending into an excluded
directory.

Pruning is not merely an optimization. `pathspec` and git genuinely disagree
about `node_modules/` followed by `!node_modules/keep.txt`: git reports
`keep.txt` as ignored, `GitIgnoreSpec.match_file()` re-includes it. Pruning
yields git's answer, which is the one a user can hold in their head. The idiom
that does work is documented in the README:

```
node_modules/*            ← exclude the entries, not the directory itself
!node_modules/keep.txt    ← re-inclusion now applies
```

See design D10 and D11.
"""

from __future__ import annotations

import contextlib
import os
import stat
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import IO, Iterable, List, Optional, Sequence, Tuple

import pathspec

from .project import PROJECT_FILE

#: Never overridable, not even by a `.freepodignore` negation. Uploading a
#: repository's history is never intended and is frequently enormous.
HARD_EXCLUDES = (".git/",)

#: Always applied, ahead of the project's own ignore files so that either can
#: override them. `.env` is deliberately absent — see D11.
DEFAULT_EXCLUDES = (
    "node_modules/",
    ".venv/",
    "venv/",
    "__pycache__/",
    "*.pyc",
    ".pytest_cache/",
    "target/",
    "dist/",
    "build/",
    ".DS_Store",
    "*.swp",
    ".env.local",
    ".env.*.local",
)

GITIGNORE_FILE = ".gitignore"
FREEPODIGNORE_FILE = ".freepodignore"

#: Below this, the archive stays in memory; above it, it spills to disk.
SPOOL_MAX_BYTES = 32 * 1024 * 1024


class Layer:
    """One ignore file's patterns, rewritten relative to the project root.

    The negation bodies are kept alongside the compiled spec because pruning
    needs a question `pathspec` cannot answer: *could* anything below this
    directory be re-included by a later negation?
    """

    def __init__(self, spec: pathspec.GitIgnoreSpec, negations: Sequence[str] = ()):
        self.spec = spec
        self.negations = list(negations)


class Ignores:
    """A stack of layers, evaluated last-match-wins as git does."""

    def __init__(self, layers: Sequence[Layer]):
        self._layers = list(layers)

    def excluded(self, relative: str, is_dir: bool) -> bool:
        candidate = relative + "/" if is_dir and not relative.endswith("/") else relative
        verdict = False
        for layer in self._layers:
            matched = layer.spec.check_file(candidate)
            if matched.include is not None:
                verdict = matched.include
        return verdict

    def negates_under(self, directory: str) -> bool:
        """Whether any layer negates a path beneath `directory`."""
        prefix = directory.rstrip("/") + "/"
        for layer in self._layers:
            for body in layer.negations:
                if body.startswith(prefix):
                    return True
        return False

    def extend(self, layer: Optional[Layer]) -> "Ignores":
        return Ignores(self._layers + [layer]) if layer is not None else self


def _negation_bodies(patterns: Iterable[str], base: str) -> List[str]:
    """The root-relative paths a layer's `!` patterns could re-include."""
    bodies = []
    for raw in patterns:
        stripped = raw.strip()
        if not stripped.startswith("!"):
            continue
        body = stripped[1:].lstrip("/")
        if not body:
            continue
        bodies.append(f"{base}/{body}" if base else body)
    return bodies


def _rewrite(patterns: Iterable[str], base: str) -> List[str]:
    """Re-anchor a directory's ignore patterns onto the project root.

    git evaluates a `.gitignore` relative to the directory containing it. A
    pattern with no separator matches at any depth *below* that directory; one
    with a separator is anchored to it. Both become root-relative here so a
    single spec can judge a root-relative path.
    """
    if not base:
        return list(patterns)

    rewritten = []
    for raw in patterns:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            rewritten.append(line)
            continue

        negated = stripped.startswith("!")
        body = stripped[1:] if negated else stripped

        # A trailing separator marks directory-only; a leading one anchors.
        anchored = "/" in body.rstrip("/")
        body = body.lstrip("/") if body.startswith("/") else body

        prefix = f"{base}/"
        if anchored:
            combined = f"{prefix}{body}"
        else:
            # Unanchored: matches at any depth under this directory.
            combined = f"{prefix}**/{body}"
            rewritten.append(("!" if negated else "") + f"{prefix}{body}")

        rewritten.append(("!" if negated else "") + combined)
    return rewritten


def _read_ignore_file(path: Path, base: str) -> Optional[Layer]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    patterns = _rewrite(lines, base)
    if not patterns:
        return None
    return Layer(
        pathspec.GitIgnoreSpec.from_lines(patterns),
        _negation_bodies(lines, base),
    )


def _spec(patterns: Sequence[str]) -> pathspec.GitIgnoreSpec:
    return pathspec.GitIgnoreSpec.from_lines(patterns)


class Packer:
    """Walks a project root and emits the members that belong in the archive."""

    def __init__(
        self,
        root: Path,
        *,
        honor_gitignore: bool = True,
        on_skip=None,
    ):
        self.root = Path(root).resolve()
        self.honor_gitignore = honor_gitignore
        self.on_skip = on_skip or (lambda path, reason: None)
        self.skipped: List[Tuple[str, str]] = []

        self._hard = _spec(HARD_EXCLUDES)
        self._defaults = _spec(DEFAULT_EXCLUDES)
        # Only the *project's own* layers live in the stack. Hard excludes and
        # built-in defaults are consulted separately, because they differ in
        # how they interact with pruning — see `_prunes`.
        self._base = Ignores([])

        # `.freepodignore` is applied last so its negations outrank everything
        # except the hard excludes, which are re-applied after it.
        self._freepodignore = (
            _read_ignore_file(self.root / FREEPODIGNORE_FILE, "")
            if (self.root / FREEPODIGNORE_FILE).is_file()
            else None
        )

    # -- exclusion --------------------------------------------------------

    @staticmethod
    def _matches(spec: pathspec.GitIgnoreSpec, relative: str, is_dir: bool) -> bool:
        candidate = relative + "/" if is_dir and not relative.endswith("/") else relative
        return bool(spec.check_file(candidate).include)

    def _stack(self, ignores: Ignores) -> Ignores:
        return ignores.extend(self._freepodignore)

    def _excluded(self, ignores: Ignores, relative: str, is_dir: bool) -> bool:
        """Whether a *file* is excluded, last match wins across all four levels."""
        # `.freepod.json` is included unconditionally: it holds no secrets, and
        # a project whose own descriptor was missing from its build would be a
        # baffling failure.
        if relative == PROJECT_FILE:
            return False
        if self._matches(self._hard, relative, is_dir):
            return True

        verdict = self._matches(self._defaults, relative, is_dir)
        candidate = relative + "/" if is_dir and not relative.endswith("/") else relative
        for layer in self._stack(ignores)._layers:
            matched = layer.spec.check_file(candidate)
            if matched.include is not None:
                verdict = matched.include
        return verdict

    def _prunes(self, ignores: Ignores, relative: str) -> bool:
        """Whether to skip descending into a directory entirely.

        Three cases, and the middle one is what makes the client agree with git:

        * A **hard** exclude always prunes. Nothing re-includes `.git/`.
        * A **project** ignore file excluding the directory prunes
          unconditionally, which is why `node_modules/` followed by
          `!node_modules/keep.txt` leaves `keep.txt` out — git's answer, and
          the reason the documented idiom excludes the *entries* instead.
        * A **built-in default** prunes only if the project does not negate
          something beneath it. Git has no equivalent of these defaults, so
          letting one silently defeat `node_modules/*` + `!node_modules/keep.txt`
          would break the very idiom the README tells people to use.
        """
        if self._matches(self._hard, relative, True):
            return True

        stack = self._stack(ignores)
        if stack.excluded(relative, True):
            return True

        if self._matches(self._defaults, relative, True):
            return not stack.negates_under(relative)

        return False

    # -- walking ----------------------------------------------------------

    def members(self) -> List[Tuple[str, Path]]:
        """Every included member, as (archive path, filesystem path), sorted."""
        found: List[Tuple[str, Path]] = []
        self._walk(self.root, "", self._base, found)
        found.sort(key=lambda entry: entry[0])
        return found

    def _layer_for(self, directory: Path, base: str) -> Optional[Layer]:
        if not self.honor_gitignore:
            return None
        candidate = directory / GITIGNORE_FILE
        if not candidate.is_file():
            return None
        return _read_ignore_file(candidate, base)

    def _walk(
        self,
        directory: Path,
        base: str,
        ignores: Ignores,
        found: List[Tuple[str, Path]],
    ) -> None:
        ignores = ignores.extend(self._layer_for(directory, base))

        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            self._skip(base or ".", f"cannot read directory: {exc}")
            return

        for entry in entries:
            relative = f"{base}/{entry.name}" if base else entry.name

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
                is_link = entry.is_symlink()
            except OSError as exc:
                self._skip(relative, f"cannot stat: {exc}")
                continue

            if is_dir:
                if self._prunes(ignores, relative):
                    # Pruned, not walked-and-filtered. This is both the
                    # performance win and the thing that makes a negation
                    # unable to reach inside, matching git.
                    continue
                self._walk(Path(entry.path), relative, ignores, found)
                continue

            if self._excluded(ignores, relative, False):
                continue

            if is_link:
                if not self._link_stays_inside(Path(entry.path)):
                    self._skip(relative, "symlink resolves outside the project")
                    continue
                found.append((relative, Path(entry.path)))
                continue

            if not is_file:
                self._skip(relative, self._describe_special(Path(entry.path)))
                continue

            found.append((relative, Path(entry.path)))

    def _link_stays_inside(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        try:
            resolved.relative_to(self.root)
        except ValueError:
            return False
        return True

    @staticmethod
    def _describe_special(path: Path) -> str:
        try:
            mode = os.lstat(path).st_mode
        except OSError:
            return "unreadable special file"
        if stat.S_ISSOCK(mode):
            return "socket"
        if stat.S_ISFIFO(mode):
            return "FIFO"
        if stat.S_ISBLK(mode) or stat.S_ISCHR(mode):
            return "device node"
        return "not a regular file"

    def _skip(self, relative: str, reason: str) -> None:
        self.skipped.append((relative, reason))
        self.on_skip(relative, reason)


def _normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
    """Strip everything that would differ between two machines.

    Ownership is zeroed and the account names blanked, so an archive does not
    carry the packer's local user around and two machines packing the same tree
    agree.
    """
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    # Normalize the mode to the two states extraction cares about, so a
    # difference in umask between machines does not change the archive.
    info.mode = 0o755 if info.mode & 0o100 else 0o644
    return info


def pack(
    root: Path,
    *,
    honor_gitignore: bool = True,
    on_skip=None,
) -> Tuple[IO[bytes], int, List[Tuple[str, Path]]]:
    """Pack `root` into a spooled temporary file.

    Returns `(handle, size, members)` with the handle rewound to 0. The caller
    owns the handle and must close it — `close()` on a `SpooledTemporaryFile`
    removes the backing file if it spilled to disk.

    The archive is materialized rather than streamed for two independent
    reasons: the presigned POST's policy carries a `content-length-range`
    condition the store evaluates against the request, and a stream cannot be
    retried — re-packing a tree that may have changed produces a different
    archive. See design D9.
    """
    packer = Packer(root, honor_gitignore=honor_gitignore, on_skip=on_skip)
    members = packer.members()

    handle: IO[bytes] = tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_BYTES, suffix=".tar.gz")
    try:
        with tarfile.open(fileobj=handle, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
            for relative, path in members:
                info = tar.gettarinfo(str(path), arcname=relative)
                info = _normalize(info)
                if info.isreg():
                    with open(path, "rb") as source:
                        tar.addfile(info, source)
                else:
                    tar.addfile(info)
        size = handle.tell()
        handle.seek(0)
    except BaseException:
        handle.close()
        raise

    return handle, size, members


@contextlib.contextmanager
def packed_archive(root: Path, *, honor_gitignore: bool = True, on_skip=None):
    """`pack`, with the temporary storage guaranteed to be released.

    The guarantee belongs here rather than in the caller: `close()` on a
    `SpooledTemporaryFile` is what removes the backing file when the archive
    spilled to disk, and a deploy has several ways to end early — a refused
    size check, a failed build, a Ctrl-C — each of which would otherwise leak
    up to the platform's maximum archive size into the temp directory.
    """
    handle, size, members = pack(root, honor_gitignore=honor_gitignore, on_skip=on_skip)
    try:
        yield handle, size, members
    finally:
        handle.close()


def report(
    size: int,
    members: Sequence[Tuple[str, Path]],
    *,
    verbose: bool = False,
    echo=None,
) -> None:
    """Announce the packed size, and under `--verbose` the biggest entries."""
    emit = echo or (lambda message: print(message, file=sys.stderr))
    emit(f"Packed {len(members)} file{'' if len(members) == 1 else 's'}, {human(size)}.")
    if not verbose:
        return
    for name, entry_size in largest(members):
        emit(f"    {human(entry_size):>10}  {name}")


def largest(members: Sequence[Tuple[str, Path]], count: int = 10) -> List[Tuple[str, int]]:
    """The biggest members by on-disk size, for `--verbose`."""
    sized = []
    for relative, path in members:
        try:
            sized.append((relative, path.stat().st_size))
        except OSError:
            continue
    sized.sort(key=lambda entry: entry[1], reverse=True)
    return sized[:count]


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"  # pragma: no cover
