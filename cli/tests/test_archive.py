"""The project archive.

The gitignore-semantics tests are written as a differential against real `git`
rather than against hand-computed expectations. Design D10 chose git's behavior
deliberately over `pathspec`'s where they diverge, and the only trustworthy
oracle for "what would git do" is git.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile

import pytest

from freepod.archive import (
    DEFAULT_EXCLUDES,
    Packer,
    human,
    largest,
    pack,
    packed_archive,
    report,
)

HAS_GIT = shutil.which("git") is not None


def build(root, tree):
    for relative, content in tree.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def packed(root, **kwargs):
    return sorted(relative for relative, _ in Packer(root, **kwargs).members())


def git_tracked(root):
    """What `git add -A` would stage — the oracle for gitignore semantics."""
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    subprocess.run(
        ["git", "add", "-A"],
        cwd=root,
        check=True,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    out = subprocess.run(
        ["git", "ls-files"], cwd=root, check=True, capture_output=True, text=True, env=env
    ).stdout.split()
    return sorted(out)


# --------------------------------------------------------------------------
# Differential against git (task 8.9)
# --------------------------------------------------------------------------

GIT_PARITY_CASES = {
    "a directory exclusion cannot be negated into": {
        ".gitignore": "vendor/\n!vendor/keep.txt\n",
        "vendor/keep.txt": "x",
        "vendor/other.js": "y",
        "app.py": "z",
    },
    "excluding entries instead permits re-inclusion": {
        ".gitignore": "vendor/*\n!vendor/keep.txt\n",
        "vendor/keep.txt": "x",
        "vendor/other.js": "y",
        "app.py": "z",
    },
    "nested ignore files layer": {
        ".gitignore": "*.log\n",
        "sub/.gitignore": "!important.log\ntemp/\n",
        "sub/important.log": "x",
        "sub/other.log": "y",
        "sub/temp/a.txt": "z",
        "root.log": "w",
        "app.py": "q",
    },
    "anchored and unanchored patterns": {
        ".gitignore": "/out\nbin/\n*.tmp\n",
        "out/a.js": "x",
        "sub/out/b.js": "y",
        "sub/bin/c.js": "z",
        "a.tmp": "w",
        "sub/d.tmp": "v",
        "app.py": "q",
    },
    "character classes with a negation": {
        ".gitignore": "*.[oa]\n!keep.o\n",
        "x.o": "1",
        "y.a": "2",
        "keep.o": "3",
        "app.py": "4",
    },
    "an unanchored pattern from a subdirectory": {
        "sub/.gitignore": "cache/\n",
        "sub/deep/cache/x.txt": "1",
        "sub/cache/y.txt": "2",
        "sub/keep.txt": "3",
    },
    "comments and blank lines are ignored": {
        ".gitignore": "# a comment\n\n*.bak\n",
        "a.bak": "1",
        "app.py": "2",
    },
}


@pytest.mark.skipif(not HAS_GIT, reason="git is not installed")
@pytest.mark.parametrize("name", sorted(GIT_PARITY_CASES))
def test_selection_matches_git(name, tmp_path):
    """None of these trees touch a built-in default, so git is a fair oracle."""
    build(tmp_path, GIT_PARITY_CASES[name])
    expected = [p for p in git_tracked(tmp_path) if not p.endswith(".gitignore")]
    actual = [p for p in packed(tmp_path) if not p.endswith(".gitignore")]
    assert actual == expected


# --------------------------------------------------------------------------
# Where the built-in defaults meet the project's own ignores (task 8.3)
# --------------------------------------------------------------------------


def test_the_node_modules_idiom_re_includes(tmp_path):
    """The idiom the README documents must actually work.

    `node_modules/` is a built-in default, so without special care the default
    would prune the directory before the negation could ever apply.
    """
    build(
        tmp_path,
        {
            ".gitignore": "node_modules/*\n!node_modules/keep.txt\n",
            "node_modules/keep.txt": "x",
            "node_modules/other.js": "y",
            "app.py": "z",
        },
    )
    assert "node_modules/keep.txt" in packed(tmp_path)
    assert "node_modules/other.js" not in packed(tmp_path)


def test_a_directory_exclusion_still_beats_a_negation(tmp_path):
    """git's answer, which is the one a user can hold in their head."""
    build(
        tmp_path,
        {
            ".gitignore": "node_modules/\n!node_modules/keep.txt\n",
            "node_modules/keep.txt": "x",
            "app.py": "z",
        },
    )
    assert packed(tmp_path) == [".gitignore", "app.py"]


def test_a_default_exclude_applies_with_no_ignore_file_present(tmp_path):
    build(tmp_path, {"node_modules/big.js": "x", "__pycache__/a.pyc": "y", "app.py": "z"})
    assert packed(tmp_path) == ["app.py"]


def test_freepodignore_can_re_include_a_default_excluded_file(tmp_path):
    build(
        tmp_path,
        {
            ".freepodignore": "!dist/bundle.js\n",
            "dist/bundle.js": "x",
            "dist/other.js": "y",
            "app.py": "z",
        },
    )
    result = packed(tmp_path)
    assert "dist/bundle.js" in result
    assert "dist/other.js" not in result


def test_re_inclusion_reaches_the_negated_path_and_nothing_else_beneath(tmp_path):
    """Descending to honor one negation must not readmit the whole directory.

    The traversal is what makes the negation reachable at all, so the exclusion
    now has to be re-established per file — including in subdirectories the
    walk enters only because it is already inside.
    """
    build(
        tmp_path,
        {
            ".freepodignore": "!dist/bundle.js\n",
            "dist/bundle.js": "x",
            "dist/other.js": "y",
            "dist/sub/deep.js": "z",
            "dist/sub/nested/deeper.js": "w",
            "app.py": "q",
        },
    )
    result = packed(tmp_path)

    assert "dist/bundle.js" in result
    assert [entry for entry in result if entry.startswith("dist/")] == ["dist/bundle.js"]


@pytest.mark.parametrize(
    "pattern",
    [
        "!node_modules/keep.txt",
        "!/node_modules/keep.txt",
        "!node_modules/**/keep.txt",
    ],
)
def test_an_anchored_negation_naming_the_directory_forces_traversal(pattern, tmp_path):
    build(
        tmp_path,
        {".freepodignore": pattern + "\n", "node_modules/keep.txt": "x", "app.py": "z"},
    )
    assert "node_modules/keep.txt" in packed(tmp_path)


def test_a_negation_that_goes_depth_independent_partway_reaches_only_what_it_names(tmp_path):
    """`!dir/**/file` re-includes at the level it names, and no deeper.

    The mechanism is the anchoring rule recursing: traversal is decided again
    at every directory, so `node_modules/**/keep.txt` prefixes
    `node_modules/` and descends, but does not prefix `node_modules/deep/` and
    that level prunes. Spelling the path out reaches the depth, as the second
    half of this test shows.

    This is emphatically *not* "git would do the same". There is no git oracle
    here at all: `node_modules/` is a built-in default, a client invention with
    no version-control equivalent, so at this level there is nothing for git to
    be right about. The rule is ours and its justification is traversal cost.
    Reaching for git to explain level-2 behavior invites someone to "align" the
    pruning rule with git and delete the cost argument along with it.
    """
    tree = {
        "node_modules/keep.txt": "x",
        "node_modules/deep/keep.txt": "y",
        "app.py": "z",
    }

    build(tmp_path, dict(tree, **{".freepodignore": "!node_modules/**/keep.txt\n"}))
    shallow_only = [e for e in packed(tmp_path) if e.startswith("node_modules/")]
    assert shallow_only == ["node_modules/keep.txt"]

    for entry in tmp_path.iterdir():
        if entry.name == ".freepodignore":
            entry.unlink()
    build(tmp_path, {".freepodignore": "!node_modules/deep/keep.txt\n"})
    named_depth = [e for e in packed(tmp_path) if e.startswith("node_modules/")]
    assert named_depth == ["node_modules/deep/keep.txt"], (
        "an anchored negation must reach the depth it names — if this fails the "
        "cause is the prefix rule, not anything to do with git"
    )


@pytest.mark.parametrize("pattern", ["!keep.txt", "!**/keep.txt", "!*.txt"])
def test_an_unanchored_negation_does_not_force_traversal(pattern, tmp_path):
    """Intended, not a gap — do not "fix" this without reading the reason.

    A depth-independent negation could match beneath *any* directory, so
    honoring it would mean descending into every default-excluded tree on every
    pack, to discover that almost none of them contain a match. That is the
    484 MB `node_modules` stat storm the defaults exist to avoid, reintroduced
    by a single `!*.md` in a `.freepodignore`.

    The remedy is to name the directory — see the anchored cases above — and
    the README documents it. If this test ever needs to change, the cost of
    walking every excluded tree has to be argued first.
    """
    build(
        tmp_path,
        {".freepodignore": pattern + "\n", "node_modules/keep.txt": "x", "app.py": "z"},
    )
    assert packed(tmp_path) == [".freepodignore", "app.py"]


def test_an_unanchored_negation_still_works_outside_a_default_excluded_directory(tmp_path):
    """The limit is scoped to pruning, not to negation in general."""
    build(
        tmp_path,
        {
            ".gitignore": "*.txt\n",
            ".freepodignore": "!keep.txt\n",
            "keep.txt": "x",
            "drop.txt": "y",
            "sub/keep.txt": "z",
            "app.py": "q",
        },
    )
    result = packed(tmp_path)
    assert "keep.txt" in result and "sub/keep.txt" in result
    assert "drop.txt" not in result


def test_a_negation_deep_inside_a_default_excluded_directory_is_honored(tmp_path):
    build(
        tmp_path,
        {
            ".freepodignore": "!dist/sub/nested/keep.js\n",
            "dist/bundle.js": "x",
            "dist/sub/nested/keep.js": "y",
            "dist/sub/nested/drop.js": "z",
            "app.py": "q",
        },
    )
    result = packed(tmp_path)

    assert [entry for entry in result if entry.startswith("dist/")] == [
        "dist/sub/nested/keep.js"
    ]


def test_freepodignore_is_applied_after_gitignore(tmp_path):
    build(
        tmp_path,
        {
            ".gitignore": "secret.txt\n",
            ".freepodignore": "!secret.txt\n",
            "secret.txt": "x",
            "app.py": "z",
        },
    )
    assert "secret.txt" in packed(tmp_path)


# --------------------------------------------------------------------------
# Hard excludes (task 8.1)
# --------------------------------------------------------------------------


def test_the_version_control_directory_is_never_packed(tmp_path):
    build(tmp_path, {".git/config": "x", ".git/objects/ab/cdef": "y", "app.py": "z"})
    assert packed(tmp_path) == ["app.py"]


def test_the_version_control_directory_cannot_be_re_included(tmp_path):
    build(
        tmp_path,
        {
            ".freepodignore": "!.git/\n!.git/**\n!.git/config\n",
            ".git/config": "x",
            "app.py": "z",
        },
    )
    assert "app.py" in packed(tmp_path)
    assert not any(entry.startswith(".git/") for entry in packed(tmp_path))


# --------------------------------------------------------------------------
# --no-gitignore (task 8.1)
# --------------------------------------------------------------------------


def test_gitignore_can_be_disabled(tmp_path):
    build(tmp_path, {".gitignore": "notes.txt\n", "notes.txt": "x", "app.py": "z"})

    assert "notes.txt" not in packed(tmp_path)
    assert "notes.txt" in packed(tmp_path, honor_gitignore=False)


def test_defaults_still_apply_with_gitignore_disabled(tmp_path):
    build(tmp_path, {"node_modules/a.js": "x", "app.py": "z"})
    assert packed(tmp_path, honor_gitignore=False) == ["app.py"]


# --------------------------------------------------------------------------
# The project file and .env (tasks 8.4, D11)
# --------------------------------------------------------------------------


def test_the_project_file_is_always_included(tmp_path):
    build(tmp_path, {".freepod.json": "{}", ".gitignore": ".freepod.json\n", "app.py": "z"})
    assert ".freepod.json" in packed(tmp_path)


def test_a_committed_env_file_is_packed(tmp_path):
    build(tmp_path, {".env": "A=1", "app.py": "z"})
    assert ".env" in packed(tmp_path)


def test_local_env_overrides_are_excluded(tmp_path):
    build(
        tmp_path,
        {
            ".env": "A=1",
            ".env.local": "B=2",
            ".env.production.local": "C=3",
            "app.py": "z",
        },
    )
    result = packed(tmp_path)
    assert ".env" in result
    assert ".env.local" not in result
    assert ".env.production.local" not in result


def test_a_gitignored_env_file_is_excluded(tmp_path):
    """The ignore stack already does the right thing without a special case."""
    build(tmp_path, {".gitignore": ".env\n", ".env": "A=1", "app.py": "z"})
    assert ".env" not in packed(tmp_path)


def test_env_is_not_in_the_default_excludes():
    assert ".env" not in DEFAULT_EXCLUDES
    assert ".env.local" in DEFAULT_EXCLUDES


# --------------------------------------------------------------------------
# Unsafe members (task 8.5)
# --------------------------------------------------------------------------


def test_a_symlink_escaping_the_project_is_omitted_and_reported(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (project / "app.py").write_text("z", encoding="utf-8")
    os.symlink(outside, project / "escape.txt")

    packer = Packer(project)
    members = [relative for relative, _ in packer.members()]

    assert "escape.txt" not in members
    assert any("escape.txt" in path for path, _ in packer.skipped)
    assert any("outside" in reason for _, reason in packer.skipped)


def test_a_symlink_inside_the_project_is_kept(tmp_path):
    build(tmp_path, {"app.py": "z", "sub/target.txt": "x"})
    os.symlink(tmp_path / "sub" / "target.txt", tmp_path / "link.txt")

    assert "link.txt" in packed(tmp_path)


def test_a_fifo_is_omitted_and_reported(tmp_path):
    build(tmp_path, {"app.py": "z"})
    os.mkfifo(tmp_path / "pipe")

    packer = Packer(tmp_path)
    members = [relative for relative, _ in packer.members()]

    assert "pipe" not in members
    assert any(path == "pipe" and "FIFO" in reason for path, reason in packer.skipped)


def test_skips_are_reported_through_the_callback(tmp_path):
    build(tmp_path, {"app.py": "z"})
    os.mkfifo(tmp_path / "pipe")

    seen = []
    Packer(tmp_path, on_skip=lambda path, reason: seen.append((path, reason))).members()

    assert seen and seen[0][0] == "pipe"


# --------------------------------------------------------------------------
# Layout and determinism (tasks 8.6, 8.7)
# --------------------------------------------------------------------------


def test_members_are_at_the_archive_root_with_relative_paths(tmp_path):
    build(tmp_path, {"package.json": "{}", "src/index.js": "x"})

    handle, size, _ = pack(tmp_path)
    try:
        with tarfile.open(fileobj=handle, mode="r:gz") as tar:
            names = tar.getnames()
    finally:
        handle.close()

    assert "package.json" in names
    assert "src/index.js" in names
    assert not any(name.startswith("/") for name in names)
    assert not any(name.startswith("./") for name in names)


def test_members_are_sorted_by_path(tmp_path):
    build(tmp_path, {"z.txt": "1", "a.txt": "2", "m/b.txt": "3"})

    handle, _, _ = pack(tmp_path)
    try:
        with tarfile.open(fileobj=handle, mode="r:gz") as tar:
            names = tar.getnames()
    finally:
        handle.close()

    assert names == sorted(names)


def test_ownership_metadata_is_normalized(tmp_path):
    build(tmp_path, {"app.py": "z"})

    handle, _, _ = pack(tmp_path)
    try:
        with tarfile.open(fileobj=handle, mode="r:gz") as tar:
            for info in tar.getmembers():
                assert info.uid == 0 and info.gid == 0
                assert info.uname == "" and info.gname == ""
    finally:
        handle.close()


def test_repacking_an_unchanged_tree_is_reproducible(tmp_path):
    build(tmp_path, {"app.py": "z", "src/index.js": "x", "README.md": "y"})

    def contents():
        handle, _, _ = pack(tmp_path)
        try:
            with tarfile.open(fileobj=handle, mode="r:gz") as tar:
                return [
                    (info.get_info(), tar.extractfile(info).read() if info.isreg() else None)
                    for info in tar.getmembers()
                ]
        finally:
            handle.close()

    # Members, their order, metadata and data; not the compressed bytes, whose
    # gzip header carries the time of packing.
    assert contents() == contents()


def test_the_handle_is_rewound_and_the_size_is_the_packed_size(tmp_path):
    build(tmp_path, {"app.py": "z" * 1000})

    handle, size, _ = pack(tmp_path)
    try:
        assert handle.tell() == 0
        assert len(handle.read()) == size
    finally:
        handle.close()


def test_file_contents_survive_the_round_trip(tmp_path):
    build(tmp_path, {"app.py": "print('hello')\n", "sub/data.json": '{"a": 1}'})

    handle, _, _ = pack(tmp_path)
    try:
        with tarfile.open(fileobj=handle, mode="r:gz") as tar:
            extracted = tar.extractfile("sub/data.json").read()
    finally:
        handle.close()

    assert extracted == b'{"a": 1}'


# --------------------------------------------------------------------------
# Pruning is real (task 8.3)
# --------------------------------------------------------------------------


def test_an_excluded_directory_is_not_enumerated(tmp_path, monkeypatch):
    build(tmp_path, {"node_modules/a.js": "x", "node_modules/deep/b.js": "y", "app.py": "z"})

    scanned = []
    real_scandir = os.scandir

    def recording_scandir(path):
        scanned.append(str(path))
        return real_scandir(path)

    monkeypatch.setattr("freepod.archive.os.scandir", recording_scandir)
    Packer(tmp_path).members()

    assert not any("node_modules" in path for path in scanned), (
        "the excluded directory was walked and filtered rather than pruned"
    )


# --------------------------------------------------------------------------
# Reporting (task 8.8)
# --------------------------------------------------------------------------


def test_largest_reports_the_biggest_members_first(tmp_path):
    build(tmp_path, {"small.txt": "x", "big.txt": "y" * 5000, "mid.txt": "z" * 500})

    top = largest(Packer(tmp_path).members())

    assert [name for name, _ in top][:3] == ["big.txt", "mid.txt", "small.txt"]


def test_report_states_the_packed_size():
    messages = []
    report(2048, [("a.txt", None), ("b.txt", None)], echo=messages.append)

    assert "2 files" in messages[0]
    assert "2.0 KiB" in messages[0]
    assert len(messages) == 1, "the entry list is --verbose only"


def test_report_lists_the_largest_entries_under_verbose(tmp_path):
    build(tmp_path, {"small.txt": "x", "big.txt": "y" * 5000})
    members = Packer(tmp_path).members()

    messages = []
    report(1234, members, verbose=True, echo=messages.append)

    assert any("big.txt" in message for message in messages)
    assert messages[1].strip().endswith("big.txt"), "largest first"


def test_the_temporary_file_is_released_on_success(tmp_path):
    build(tmp_path, {"app.py": "z"})
    with packed_archive(tmp_path) as (handle, size, members):
        assert size > 0 and members
        captured = handle
    assert captured.closed


def test_the_temporary_file_is_released_on_failure(tmp_path):
    """A refused size check or a failed build must not leak the archive."""
    build(tmp_path, {"app.py": "z"})
    captured = {}

    with pytest.raises(RuntimeError):
        with packed_archive(tmp_path) as (handle, _size, _members):
            captured["handle"] = handle
            raise RuntimeError("size check refused it")

    assert captured["handle"].closed


def test_a_pack_that_fails_midway_closes_its_handle(tmp_path, monkeypatch):
    build(tmp_path, {"app.py": "z"})

    import freepod.archive as archive_module

    real_open = archive_module.tarfile.open

    def exploding(*args, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(archive_module.tarfile, "open", exploding)

    with pytest.raises(OSError):
        pack(tmp_path)

    monkeypatch.setattr(archive_module.tarfile, "open", real_open)


def test_human_renders_readable_sizes():
    assert human(512) == "512 B"
    assert human(2048) == "2.0 KiB"
    assert "MiB" in human(5 * 1024 * 1024)


def test_an_empty_project_still_packs(tmp_path):
    handle, size, members = pack(tmp_path)
    try:
        assert members == []
        assert size > 0  # a valid, empty gzip tar
    finally:
        handle.close()
