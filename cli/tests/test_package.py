"""The package's shape.

The clean-install check itself lives outside pytest — it needs an isolated
environment, and is run by the CI job from task 14.2. What is asserted here is
everything that can regress inside this tree.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import freepod

SOURCE_ROOT = pathlib.Path(freepod.__file__).parent

#: The modules design D1 lays out.
EXPECTED_MODULES = {
    "__init__",
    "__main__",
    "cli",
    "copy",
    "config",
    "auth",
    "api",
    "project",
    "values",
    "archive",
    "build",
    "deploy",
    "initialize",
    "link",
    "apply",
    "fields",
    "delete",
    "history",
    "skill",
}


def source_files():
    return sorted(SOURCE_ROOT.glob("*.py"))


def test_every_module_from_the_design_exists():
    present = {path.stem for path in source_files()}
    assert EXPECTED_MODULES <= present, f"missing: {EXPECTED_MODULES - present}"


def test_the_console_script_target_is_importable():
    from freepod.cli import main

    assert callable(main)


def test_nothing_imports_the_api_server():
    """The client depends on the public REST API, not on the server's source.

    `api/`'s package is imported as `app`, so an accidental `from app...` is
    the shape this catches.
    """
    forbidden = {"app", "caelus", "sqlmodel", "fastapi"}
    offenders = []

    for path in source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]] if node.level == 0 else []
            else:
                continue
            for name in names:
                if name in forbidden:
                    offenders.append(f"{path.name}:{node.lineno} imports {name}")

    assert offenders == []


def test_the_runtime_dependencies_are_the_declared_four():
    """Every import must resolve to the standard library or a declared dep.

    The dependency budget is part of the distribution contract: each addition
    lengthens a Homebrew formula's vendored resources and can cost the
    universal-wheel guarantee. `prompt_toolkit` is `freepod link`'s picker.
    """
    declared = {"click", "httpx", "pathspec", "prompt_toolkit"}
    local = EXPECTED_MODULES | {"freepod"}
    stdlib = set(sys.stdlib_module_names)

    unexpected = set()
    for path in source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]] if node.level == 0 else []
            else:
                continue
            for name in names:
                if name and name not in stdlib and name not in declared and name not in local:
                    unexpected.add(f"{path.name}: {name}")

    assert unexpected == set()


def test_the_package_declares_a_version():
    assert freepod.__version__


def test_every_error_class_carries_an_exit_code():
    from freepod import (
        AuthenticationError,
        BuildFailed,
        FreepodError,
        PermissionError_,
        RolloutFailed,
        UsageError,
    )

    assert FreepodError.exit_code == 1
    assert UsageError.exit_code == 2
    assert AuthenticationError.exit_code == 3
    assert BuildFailed.exit_code == 4
    assert RolloutFailed.exit_code == 5
    # A permission error is a plain failure, not a credential prompt.
    assert PermissionError_.exit_code == 1
    assert not issubclass(PermissionError_, AuthenticationError)
