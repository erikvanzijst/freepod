"""The object commands of `freepod bucket`: listing, transfers, deletes, links.

Spec: openspec/specs/cli-bucket-objects/spec.md.

A remote path is marked with a leading `:` and rooted at the bucket; a leading
`/` after the marker is dropped, since the store cannot hold such a key anyway.
Without a trailing `/` a path names the object with that exact key when there
is one, and otherwise the prefix `path/`; with one it names the prefix only.

Downloads turn keys into local paths, and keys are whatever the tenant's app
wrote, so each is normalized and refused if it still points outside the
destination. That is checked per key as the listing arrives rather than by
listing everything first: a large tree should start transferring at once.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import sys
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, CancelledError, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, List, Optional, Set, Tuple

from . import FreepodError, UsageError
from .database import format_bytes
from .s3 import MAX_COPY_OBJECT_BYTES, MAX_PRESIGN_SECONDS, Bucket, NoSuchKey, ObjectInfo, S3Error

MARKER = ":"
MIB = 1024 * 1024

#: Up to this size a file goes up in one signed request; above it, in parts.
SINGLE_PUT_MAX = 8 * MIB

#: Small enough that a part finishes inside the edge's 60-second read timeout
#: on an uplink of about 1.1 Mbit/s, and above S3's 5 MiB minimum.
PART_SIZE = 8 * MIB
MAX_PARTS = 10_000

#: Copies within the bucket above S3's single-copy limit go in parts this size.
COPY_PART_SIZE = 1024 * MIB

#: Transfers in flight at once: files, and separately parts of large files.
WORKERS = 4

DELETE_BATCH = 1000

DEFAULT_LINK_SECONDS = 3600


class Cancelled(Exception):
    """The run was interrupted; stop at the next safe point."""


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------


def remote_path(arg: str, *, marker_required: bool) -> Optional[str]:
    """The bucket path `arg` names, or None when it is a local path."""
    if arg.startswith(MARKER):
        return arg[len(MARKER):].lstrip("/")
    if marker_required:
        return None
    return arg.lstrip("/")


def basename(key: str) -> str:
    return key.rstrip("/").rsplit("/", 1)[-1]


def as_prefix(path: str) -> str:
    """`path` as a prefix: the root stays empty, anything else ends in `/`."""
    return path if path == "" or path.endswith("/") else path + "/"


@dataclass
class Target:
    kind: str  # "object" or "prefix"
    key: str  # the object's key, or a prefix ending in "/" ("" is the root)
    info: Optional[ObjectInfo] = None


def resolve(bucket: Bucket, path: str) -> Optional[Target]:
    """What `path` names: the exact object first, then the prefix."""
    if path == "":
        return Target("prefix", "")
    if path.endswith("/"):
        return Target("prefix", path) if bucket.has_prefix(path) else None
    info = bucket.head(path)
    if info is not None:
        return Target("object", path, info)
    if bucket.has_prefix(path + "/"):
        return Target("prefix", path + "/")
    return None


def require(bucket: Bucket, path: str, arg: str) -> Target:
    target = resolve(bucket, path)
    if target is None:
        raise FreepodError(f"'{arg}': no such object or prefix in the bucket.")
    return target


def local_path(root: Path, relative_key: str) -> Optional[Path]:
    """Where a key lands under `root`, or None when it would land outside it.

    Empty and `.` segments are dropped and `..` resolved, so `a/b/../c` lands
    at `a/c`. What still climbs above `root` is refused, and so is anything an
    existing symlink inside `root` would carry out of it.
    """
    if os.sep != "/":
        relative_key = relative_key.replace(os.sep, "/")
        if os.altsep:
            relative_key = relative_key.replace(os.altsep, "/")
    parts: List[str] = []
    for segment in relative_key.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(segment)
    if not parts:
        return None
    path = root.joinpath(*parts)
    real_root = os.path.realpath(root)
    real = os.path.realpath(path)
    if os.path.commonpath([real_root, real]) != real_root:
        return None
    return path


# --------------------------------------------------------------------------
# Progress and problems
# --------------------------------------------------------------------------


class Reporter:
    """Counts what moved, and says what did not.

    Progress is a single self-overwriting line, only on a terminal and never
    under --quiet. A skipped or failed item is always reported: it is what
    explains the non-zero exit.
    """

    def __init__(self, *, quiet: bool, stream=None):
        self.stream = stream or sys.stderr
        self.live = not quiet and _isatty(self.stream)
        self.files = 0
        self.bytes = 0
        self.problems: List[str] = []
        self._lock = threading.Lock()
        self._shown = 0.0
        self._width = 0

    def add(self, nbytes: int = 0, *, files: int = 0) -> None:
        with self._lock:
            self.bytes += nbytes
            self.files += files

    def problem(self, message: str) -> None:
        with self._lock:
            self.problems.append(message)
            self._clear()
            print(f"skipped: {message}", file=self.stream)

    def tick(self, force: bool = False) -> None:
        if not self.live:
            return
        now = time.monotonic()
        if not force and now - self._shown < 0.2:
            return
        with self._lock:
            self._shown = now
            line = f"  {self.files} file{'s' if self.files != 1 else ''}, {format_bytes(self.bytes)}"
            self._width = max(self._width, len(line))
            self.stream.write("\r" + line.ljust(self._width))
            self.stream.flush()

    def finish(self) -> None:
        with self._lock:
            self._clear()

    def _clear(self) -> None:
        if self.live and self._width:
            self.stream.write("\r" + " " * self._width + "\r")
            self.stream.flush()
            self._width = 0


def _isatty(stream) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


# --------------------------------------------------------------------------
# Running transfers
# --------------------------------------------------------------------------


class Pool:
    """Two bounded pools — whole items, and parts of large files — and a stop flag.

    Separate so that an item waiting on its own parts can never starve them.
    """

    def __init__(self, workers: int = WORKERS):
        self.workers = workers
        self.items = ThreadPoolExecutor(workers, thread_name_prefix="freepod-item")
        self.parts = ThreadPoolExecutor(workers, thread_name_prefix="freepod-part")
        self.cancel = threading.Event()

    def check(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()

    def run(self, tasks: Iterable[Callable[[], None]], reporter: Reporter) -> None:
        """Run every task, a bounded number at a time, until done or interrupted.

        The task iterator is consumed lazily, so a listing feeds transfers as
        it arrives rather than being read to its end first.
        """
        pending: Set[Future] = set()
        try:
            for task in tasks:
                pending.add(self.items.submit(task))
                while len(pending) >= self.workers * 2:
                    pending = self._drain(pending, reporter)
            while pending:
                pending = self._drain(pending, reporter)
        except BaseException:
            self.cancel.set()
            for future in pending:
                future.cancel()
            self.parts.shutdown(wait=False, cancel_futures=True)
            self.items.shutdown(wait=True, cancel_futures=True)
            self.parts.shutdown(wait=True)
            raise
        finally:
            reporter.tick(force=True)

    def _drain(self, pending: Set[Future], reporter: Reporter) -> Set[Future]:
        done, rest = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
        reporter.tick()
        for future in done:
            error = future.exception()
            if error is not None:
                raise error
        return set(rest)

    def close(self) -> None:
        self.items.shutdown(wait=True)
        self.parts.shutdown(wait=True)


def _part_size(size: int) -> int:
    """8 MiB, grown in whole MiB only when the file would exceed 10,000 parts."""
    needed = math.ceil(size / MAX_PARTS)
    if needed <= PART_SIZE:
        return PART_SIZE
    return math.ceil(needed / MIB) * MIB


def upload_file(bucket: Bucket, path: Path, key: str, pool: Pool, reporter: Reporter) -> None:
    """One local file to one key, in parts when it is large.

    A multipart upload that does not complete — a failed part, or the user
    pressing Ctrl-C — is aborted before this returns, so its parts do not hold
    disk until the lifecycle rule finds them.
    """
    pool.check()
    size = path.stat().st_size
    if size <= SINGLE_PUT_MAX:
        body = path.read_bytes()
        bucket.put(key, body)
        reporter.add(len(body), files=1)
        return

    part_size = _part_size(size)
    count = math.ceil(size / part_size)
    upload_id = bucket.create_multipart(key)

    def part(number: int) -> str:
        pool.check()
        with open(path, "rb") as handle:
            handle.seek((number - 1) * part_size)
            body = handle.read(part_size)
        etag = bucket.upload_part(key, upload_id, number, body)
        reporter.add(len(body))
        return etag

    futures: List[Future] = []
    try:
        futures = [pool.parts.submit(part, n) for n in range(1, count + 1)]
        etags = [future.result() for future in futures]
        pool.check()
        bucket.complete_multipart(key, upload_id, etags)
    except BaseException:
        for future in futures:
            future.cancel()
        wait(futures)
        try:
            bucket.abort_multipart(key, upload_id)
        except S3Error:
            pass
        raise
    reporter.add(files=1)


def download_object(
    bucket: Bucket,
    key: str,
    dest: Path,
    pool: Pool,
    reporter: Reporter,
    mode: int,
) -> None:
    """One object to one local file, which appears only once it is complete.

    The body goes to a temporary file beside the destination, is checked
    against its length (and its MD5, when the ETag is one), and is then moved
    into place. An interruption or a failure leaves no trace at `dest`.
    """
    pool.check()
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".freepod", dir=str(dest.parent))
    try:
        digest = hashlib.md5()
        received = 0
        with os.fdopen(fd, "wb") as handle, bucket.download(key) as response:
            expected = int(response.headers.get("content-length", "-1"))
            etag = response.headers.get("etag", "").strip('"')
            # Raw, not decoded: the object's bytes exactly as stored.
            for chunk in response.iter_raw(MIB):
                pool.check()
                handle.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                reporter.add(len(chunk))
        if expected >= 0 and received != expected:
            raise S3Error(f"'{key}' arrived incomplete ({received} of {expected} bytes)")
        if re.fullmatch(r"[0-9a-f]{32}", etag) and digest.hexdigest() != etag:
            raise S3Error(f"'{key}' arrived with different content than the store holds")
        os.chmod(tmp, mode)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    reporter.add(files=1)


def copy_object(bucket: Bucket, source: ObjectInfo, destination: str) -> None:
    """A copy inside the store: no object bytes pass through this machine."""
    if source.size <= MAX_COPY_OBJECT_BYTES:
        bucket.copy(source.key, destination)
        return
    upload_id = bucket.create_multipart(destination)
    try:
        etags = []
        for number, first in enumerate(range(0, source.size, COPY_PART_SIZE), start=1):
            last = min(first + COPY_PART_SIZE, source.size) - 1
            etags.append(
                bucket.upload_part_copy(destination, upload_id, number, source.key, first, last)
            )
        bucket.complete_multipart(destination, upload_id, etags)
    except BaseException:
        try:
            bucket.abort_multipart(destination, upload_id)
        except S3Error:
            pass
        raise


class Deleter:
    """Deletes keys in batches, only ever after the caller says they are done."""

    def __init__(self, bucket: Bucket, reporter: Reporter, *, verb: str = "kept"):
        self.bucket = bucket
        self.reporter = reporter
        self.verb = verb
        self.deleted = 0
        self._batch: List[str] = []
        self._lock = threading.Lock()

    def add(self, key: str) -> None:
        with self._lock:
            self._batch.append(key)
            if len(self._batch) < DELETE_BATCH:
                return
            batch, self._batch = self._batch, []
        self._delete(batch)

    def flush(self) -> None:
        with self._lock:
            batch, self._batch = self._batch, []
        self._delete(batch)

    def _delete(self, batch: List[str]) -> None:
        if not batch:
            return
        try:
            failed = dict(self.bucket.delete_many(batch))
        except S3Error as exc:
            failed = {key: str(exc) for key in batch}
        for key, why in failed.items():
            self.reporter.problem(f"'{key}' could not be deleted and was {self.verb}: {why}")
        with self._lock:
            self.deleted += len(batch) - len(failed)


# --------------------------------------------------------------------------
# cp and mv
# --------------------------------------------------------------------------


@dataclass
class Plan:
    """What one cp or mv does: its tasks, and how to finish afterwards."""

    tasks: Iterator[Callable[[], None]]
    finish: List[Callable[[], None]] = field(default_factory=list)


def _guard(reporter: Reporter, name: str, action: Callable[[], None], *, move: bool) -> Callable[[], None]:
    """Run one item, turning its failure into a reported skip rather than an abort."""

    def run() -> None:
        try:
            action()
        except (Cancelled, CancelledError):
            raise
        except (S3Error, OSError) as exc:
            kept = " Its source was kept." if move else ""
            reporter.problem(f"'{name}' was not {'moved' if move else 'copied'}: {_reason(exc)}.{kept}")

    return run


def _reason(exc: BaseException) -> str:
    if isinstance(exc, OSError) and exc.strerror:
        return exc.strerror.lower()
    return str(exc).rstrip(".")


def _umask_mode() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


def plan_transfer(
    bucket: Bucket,
    source: str,
    destination: str,
    *,
    move: bool,
    pool: Pool,
    reporter: Reporter,
) -> Plan:
    """Work out a cp or mv from its two arguments, refusing what cannot be done.

    Every refusal that needs no transfer happens here, before anything moves.
    """
    remote_source = remote_path(source, marker_required=True)
    remote_destination = remote_path(destination, marker_required=True)
    if remote_source is None and remote_destination is None:
        raise UsageError(
            "neither path names the bucket, so this is a local operation your own "
            "shell already does.\n  Mark the bucket's side with ':', as in "
            "`freepod bucket cp report.csv :reports/`."
        )
    if remote_source is None:
        return _plan_upload(bucket, Path(source), remote_destination, move, pool, reporter)
    if remote_destination is None:
        return _plan_download(
            bucket, remote_source, source, destination, move, pool, reporter
        )
    return _plan_within(bucket, remote_source, source, remote_destination, move, reporter)


def _walk_local(root: Path, reporter: Reporter) -> Iterator[Tuple[Path, str]]:
    """Files under `root`, with their `/`-separated paths relative to it.

    Symlinks to files are followed. Symlinked directories are not entered —
    that rules out cycles and keeps the copy inside the tree that was named.
    """
    for directory, subdirectories, files in os.walk(root, followlinks=False):
        here = Path(directory)
        for name in list(subdirectories):
            if (here / name).is_symlink():
                subdirectories.remove(name)
                reporter.problem(f"'{here / name}' is a symlinked directory, which is not followed")
        subdirectories.sort()
        for name in sorted(files):
            path = here / name
            if not path.is_file():
                reporter.problem(f"'{path}' is not a regular file")
                continue
            yield path, path.relative_to(root).as_posix()


def _prune_empty_directories(root: Path) -> None:
    for directory, _subdirectories, _files in os.walk(root, topdown=False):
        try:
            os.rmdir(directory)
        except OSError:
            pass


def _plan_upload(
    bucket: Bucket,
    source: Path,
    destination: str,
    move: bool,
    pool: Pool,
    reporter: Reporter,
) -> Plan:
    if not os.path.lexists(source):
        raise FreepodError(f"'{source}' does not exist on this machine, so there is nothing to copy.")

    def one(path: Path, key: str) -> Callable[[], None]:
        def action() -> None:
            upload_file(bucket, path, key, pool, reporter)
            if move:
                path.unlink()

        return _guard(reporter, str(path), action, move=move)

    if source.is_dir():
        base = as_prefix(destination)
        tasks = (one(path, base + relative) for path, relative in _walk_local(source, reporter))
        plan = Plan(tasks)
        if move:
            plan.finish.append(lambda: _prune_empty_directories(source))
        return plan

    if not source.is_file():
        raise FreepodError(f"'{source}' is not a regular file or a directory.")
    key = destination + source.name if destination == "" or destination.endswith("/") else destination
    return Plan(iter([one(source, key)]))


def _plan_download(
    bucket: Bucket,
    path: str,
    source_arg: str,
    destination_arg: str,
    move: bool,
    pool: Pool,
    reporter: Reporter,
) -> Plan:
    target = require(bucket, path, source_arg)
    destination = Path(destination_arg)
    mode = _umask_mode()
    deleter = Deleter(bucket, reporter) if move else None

    def one(key: str, dest: Path) -> Callable[[], None]:
        def action() -> None:
            download_object(bucket, key, dest, pool, reporter, mode)
            if deleter is not None:
                deleter.add(key)

        return _guard(reporter, key, action, move=move)

    if target.kind == "object":
        into = destination.is_dir() or destination_arg.endswith(("/", os.sep))
        dest = destination / basename(target.key) if into else destination
        if not into and not dest.parent.exists():
            raise FreepodError(f"'{dest.parent}' does not exist on this machine, so nothing can be written there.")
        plan = Plan(iter([one(target.key, dest)]))
    else:
        if destination.exists() and not destination.is_dir():
            raise FreepodError(f"'{destination}' is a file, so a prefix cannot be copied into it.")
        destination.mkdir(parents=True, exist_ok=True)
        plan = Plan(_download_tasks(bucket, target.key, destination, reporter, one, deleter))

    if deleter is not None:
        plan.finish.append(deleter.flush)
    return plan


def _download_tasks(
    bucket: Bucket,
    prefix: str,
    root: Path,
    reporter: Reporter,
    one: Callable[[str, Path], Callable[[], None]],
    deleter: Optional[Deleter],
) -> Iterator[Callable[[], None]]:
    written: Set[str] = set()
    for page in bucket.walk(prefix):
        for item in page.objects:
            relative = item.key[len(prefix):]
            if relative == "":
                continue
            dest = local_path(root, relative)
            if dest is None:
                reporter.problem(f"'{item.key}' would land outside '{root}'")
                continue
            if item.key.endswith("/"):
                if item.size == 0:
                    # A folder marker: the folder, not a file.
                    dest.mkdir(parents=True, exist_ok=True)
                    if deleter is not None:
                        deleter.add(item.key)
                else:
                    reporter.problem(f"'{item.key}' ends in '/' but holds data, so it cannot be a file")
                continue
            name = str(dest)
            if name in written:
                reporter.problem(f"'{item.key}' lands on '{dest}', which an earlier key already wrote")
                continue
            written.add(name)
            yield one(item.key, dest)


def _plan_within(
    bucket: Bucket,
    path: str,
    source_arg: str,
    destination: str,
    move: bool,
    reporter: Reporter,
) -> Plan:
    target = require(bucket, path, source_arg)
    deleter = Deleter(bucket, reporter) if move else None

    def one(source: ObjectInfo, key: str) -> Callable[[], None]:
        def action() -> None:
            copy_object(bucket, source, key)
            reporter.add(source.size, files=1)
            if deleter is not None:
                deleter.add(source.key)

        return _guard(reporter, source.key, action, move=move)

    if target.kind == "object":
        key = (
            destination + basename(target.key)
            if destination == "" or destination.endswith("/")
            else destination
        )
        if key == target.key:
            raise UsageError(f"'{source_arg}' would be {'moved' if move else 'copied'} onto itself.")
        plan = Plan(iter([one(target.info, key)]))
    else:
        base = as_prefix(destination)
        if base == target.key:
            raise UsageError(f"'{source_arg}' would be {'moved' if move else 'copied'} onto itself.")
        if base.startswith(target.key):
            raise UsageError(
                f"'{destination}' is inside '{source_arg}', so the copy would pick up its own output."
            )
        plan = Plan(
            one(item, base + item.key[len(target.key):])
            for page in bucket.walk(target.key)
            for item in page.objects
        )

    if deleter is not None:
        plan.finish.append(deleter.flush)
    return plan


def transfer(
    bucket: Bucket,
    source: str,
    destination: str,
    *,
    move: bool,
    reporter: Reporter,
    workers: int = WORKERS,
) -> None:
    """Carry out a cp or mv. Raises after the run when anything was skipped."""
    pool = Pool(workers)
    try:
        plan = plan_transfer(
            bucket, source, destination, move=move, pool=pool, reporter=reporter
        )
        pool.run(plan.tasks, reporter)
        for step in plan.finish:
            step()
    finally:
        reporter.finish()
        pool.close()
    if reporter.problems:
        count = len(reporter.problems)
        raise FreepodError(
            f"{count} item{'s' if count != 1 else ''} {'was' if count == 1 else 'were'} "
            f"not {'moved' if move else 'copied'}; see above."
        )


# --------------------------------------------------------------------------
# ls, cat, rm, link
# --------------------------------------------------------------------------


def list_entries(
    bucket: Bucket, path: str, arg: str, *, recursive: bool
) -> Iterator[Tuple[str, Optional[ObjectInfo]]]:
    """(name, object) pairs to print; a sub-prefix has no object."""
    target = require(bucket, path, arg)
    if target.kind == "object":
        yield path, target.info
        return
    prefix = target.key
    for page in bucket.walk(prefix, delimiter=None if recursive else "/"):
        entries: List[Tuple[str, Optional[ObjectInfo]]] = [
            (p[len(prefix):], None) for p in page.prefixes
        ]
        entries += [(o.key[len(prefix):], o) for o in page.objects if o.key != prefix]
        yield from sorted(entries, key=lambda entry: entry[0])


def format_entry(name: str, info: Optional[ObjectInfo], *, long: bool) -> str:
    if not long:
        return name
    if info is None:
        return f"{'PRE':>12}  {'':16}  {name}"
    when = info.last_modified.astimezone().strftime("%Y-%m-%d %H:%M") if info.last_modified else ""
    return f"{info.size:>12}  {when:16}  {name}"


def cat(bucket: Bucket, paths: List[Tuple[str, str]], out) -> None:
    """Each object's bytes, in order, exactly as stored and as they arrive."""
    for path, arg in paths:
        if path == "" or path.endswith("/"):
            raise FreepodError(f"'{arg}' names a prefix, not an object.")
        try:
            with bucket.download(path) as response:
                for chunk in response.iter_raw(64 * 1024):
                    out.write(chunk)
                out.flush()
        except NoSuchKey:
            if bucket.has_prefix(path + "/"):
                raise FreepodError(f"'{arg}' names a prefix, not an object.") from None
            raise FreepodError(f"'{arg}': no such object in the bucket.") from None


def remove(bucket: Bucket, paths: List[Tuple[str, str]], *, recursive: bool, reporter: Reporter) -> int:
    """Delete what `paths` name. Every refusal happens before anything is deleted."""
    targets = [(require(bucket, path, arg), arg) for path, arg in paths]
    for target, arg in targets:
        if target.kind == "prefix" and not recursive:
            raise UsageError(
                f"'{arg}' is a prefix. `freepod bucket rm -r` deletes everything under it."
            )

    deleter = Deleter(bucket, reporter, verb="left in place")
    for target, _arg in targets:
        if target.kind == "object":
            deleter.add(target.key)
            continue
        for page in bucket.walk(target.key):
            for item in page.objects:
                deleter.add(item.key)
                reporter.tick()
    deleter.flush()
    reporter.finish()
    if reporter.problems:
        count = len(reporter.problems)
        raise FreepodError(f"{count} object{'s' if count != 1 else ''} could not be deleted; see above.")
    return deleter.deleted


_DURATION = re.compile(r"(\d+)([smhd]?)")
_UNIT = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_expiry(value: str) -> int:
    match = _DURATION.fullmatch(value.strip().lower())
    if match is None:
        raise UsageError(f"'{value}' is not a duration; use a number with s, m, h or d, as in 30m or 2d.")
    seconds = int(match.group(1)) * _UNIT[match.group(2)]
    if seconds < 1:
        raise UsageError("a link must be valid for at least one second.")
    if seconds > MAX_PRESIGN_SECONDS:
        raise UsageError("a link can be valid for at most 7 days (7d).")
    return seconds


def link(bucket: Bucket, path: str, arg: str, *, put: bool, expires: int) -> str:
    if path == "" or path.endswith("/"):
        raise FreepodError(f"'{arg}' names a prefix; a link is for one object.")
    if not put and bucket.head(path) is None:
        if bucket.has_prefix(path + "/"):
            raise FreepodError(f"'{arg}' names a prefix; a link is for one object.")
        raise FreepodError(f"'{arg}': no such object in the bucket.")
    return bucket.presign("PUT" if put else "GET", path, expires)
