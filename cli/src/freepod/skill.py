"""`freepod skill` — install the packaged agent instructions for this client.

The skill is shipped as package data rather than as documentation in the
repository, because the copy an agent reads has to be versioned with the client
it drives. Instructions describing a `deploy` that no longer behaves that way
are worse than no instructions at all, and a hand-copied file becomes exactly
that on the first release. `pip install --upgrade freepod` is the whole
update story: `sync` replaces installed copies on the next command.

`SKILL.md` with YAML frontmatter is a cross-agent format: Claude Code, Codex,
OpenCode, Amp, Gemini and Qwen Code all read the same file, differing only in
where they look for it. So one document serves every agent and this module is
only a table of directories.

**That table is the part that will go stale.** Each agent's path is recorded
below with where it was confirmed from, because these conventions are young and
still moving — `.agents/skills/` is visibly emerging as a shared location and
some agents already read several. When one moves, correct the row; `--dest`
exists so that a user is never blocked waiting for that release.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple

from . import FreepodError, UsageError
from .config import config_dir, ensure_config_dir

SKILL_NAME = "deploy-to-freepod"
SKILL_FILE = "SKILL.md"
RECORD_FILE = "skill.json"
OPT_OUT_VAR = "FREEPOD_NO_SKILL"


class Agent(NamedTuple):
    """One coding agent: how to notice it, and where its skills live."""

    key: str
    label: str
    #: Presence of this directory is what "installed on this machine" means. It
    #: is the agent's configuration directory, not its skills directory: an
    #: agent the user has run but never given a skill to still counts.
    config_dir: Path
    user_skills: Path
    #: Relative to the project root, for `--project`.
    project_skills: Path


def _config_home() -> Path:
    """`$XDG_CONFIG_HOME`, or the `~/.config` it defaults to."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _dir_from_env(variable: str, fallback: Path) -> Path:
    value = os.environ.get(variable)
    return Path(value) if value else fallback


def agents() -> List[Agent]:
    """The supported agents, in a stable order.

    Built per call rather than at import so the environment variables and the
    home directory are read when the command runs — which is what lets the
    tests point `HOME` somewhere harmless.
    """
    home = Path.home()
    config = _config_home()

    # Amp is the one row whose install path is not under its own config
    # directory: it reads user-level skills from `~/.config/agents/skills`
    # (ampcode.com/news/agent-skills), while `~/.config/amp` is what tells us
    # Amp is installed at all.
    return [
        Agent(
            key="claude",
            label="Claude Code",
            config_dir=_dir_from_env("CLAUDE_CONFIG_DIR", home / ".claude"),
            user_skills=_dir_from_env("CLAUDE_CONFIG_DIR", home / ".claude") / "skills",
            project_skills=Path(".claude/skills"),
        ),
        Agent(
            key="codex",
            label="Codex",
            # `$CODEX_HOME/skills/<name>`, per Codex's own bundled
            # skill-installer skill.
            config_dir=_dir_from_env("CODEX_HOME", home / ".codex"),
            user_skills=_dir_from_env("CODEX_HOME", home / ".codex") / "skills",
            project_skills=Path(".codex/skills"),
        ),
        Agent(
            key="opencode",
            label="OpenCode",
            config_dir=config / "opencode",
            user_skills=config / "opencode" / "skills",
            project_skills=Path(".opencode/skills"),
        ),
        Agent(
            key="amp",
            label="Amp",
            config_dir=config / "amp",
            user_skills=config / "agents" / "skills",
            project_skills=Path(".agents/skills"),
        ),
        Agent(
            key="gemini",
            label="Gemini CLI",
            config_dir=home / ".gemini",
            user_skills=home / ".gemini" / "skills",
            project_skills=Path(".gemini/skills"),
        ),
        # A fork of Gemini CLI whose layout mirrors it: personal skills in
        # `~/.qwen/skills/`, project skills in `.qwen/skills/`, per its own
        # skills documentation and `skill-manager.ts` in qwen-code.
        Agent(
            key="qwencode",
            label="Qwen Code",
            config_dir=home / ".qwen",
            user_skills=home / ".qwen" / "skills",
            project_skills=Path(".qwen/skills"),
        ),
        Agent(
            key="vibe",
            label="Mistral Vibe",
            config_dir=home / ".vibe",
            user_skills=home / ".vibe" / "skills",
            project_skills=Path(".vibe/skills"),
        ),
    ]


def agent_keys() -> List[str]:
    return [agent.key for agent in agents()]


def detected() -> List[Agent]:
    """The agents whose configuration directory exists on this machine."""
    return [agent for agent in agents() if agent.config_dir.is_dir()]


def select(names: Sequence[str], everything: bool) -> List[Agent]:
    """Resolve `--agent`/`--all` to a list, or fall back to what is installed."""
    known = {agent.key: agent for agent in agents()}

    if everything:
        return agents()

    if names:
        chosen: List[Agent] = []
        for name in names:
            key = name.strip().lower()
            if key not in known:
                raise UsageError(
                    f"unknown agent '{name}'. Known agents: {', '.join(known)}."
                )
            if known[key] not in chosen:
                chosen.append(known[key])
        return chosen

    return detected()


def target_for(agent: Agent, project: bool) -> Path:
    root = agent.project_skills if project else agent.user_skills
    return root / SKILL_NAME / SKILL_FILE


def read_skill() -> str:
    """Return the packaged SKILL.md.

    `importlib.resources` rather than `__file__` arithmetic, so this keeps
    working from a zipimport or any other non-filesystem loader.
    """
    try:
        from importlib.resources import files
    except ImportError:  # pragma: no cover - Python < 3.9, excluded by requires-python
        raise FreepodError("reading packaged data needs Python 3.9 or newer.")

    try:
        return (files("freepod") / "assets" / SKILL_FILE).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise FreepodError(
            f"the packaged skill is missing from this installation ({exc}). "
            f"Reinstalling the client should restore it: pip install --force-reinstall freepod"
        ) from exc


def write(target: Path, content: Optional[str] = None) -> str:
    """Write the skill to `target`, overwriting whatever is there.

    There is no confirmation and no `--force`, by design: this path belongs to
    the client, the file is generated rather than authored, and the upgrade
    story only works if a newer client can replace an older skill without
    ceremony. An unchanged file is reported rather than rewritten, so a re-run
    is quiet and the mtime keeps meaning something.
    """
    content = read_skill() if content is None else content

    if target.exists():
        try:
            if target.read_text(encoding="utf-8") == content:
                return "current"
        except OSError:
            # Unreadable but present: fall through and replace it.
            pass

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise FreepodError(f"cannot write {target}: {exc}") from exc

    return "installed"


def install(chosen: Iterable[Agent], *, project: bool) -> List[Tuple[Agent, Path, str]]:
    """Install for every agent in `chosen`, skipping duplicate destinations.

    Two agents can resolve to one directory — several already read each other's
    locations for compatibility, and a redirected `CLAUDE_CONFIG_DIR` can do it
    outright. Writing twice would be harmless but reporting twice would not be,
    so the first agent to claim a path owns it.
    """
    content = read_skill()
    seen: Dict[Path, Agent] = {}
    results: List[Tuple[Agent, Path, str]] = []

    for agent in chosen:
        target = target_for(agent, project)
        resolved = target.parent.resolve()
        if resolved in seen:
            continue
        seen[resolved] = agent
        results.append((agent, target, write(target, content)))

    return results


# ------------------------------------------------------------- the auto-sync


def _key(target: Path) -> str:
    """One spelling per destination, so a symlinked skills directory is one entry."""
    return str(target.parent.resolve() / target.name)


def record_path() -> Path:
    return config_dir() / RECORD_FILE


def load_record() -> Set[str]:
    """The destinations this client has installed to. Unreadable means none."""
    try:
        data = json.loads(record_path().read_text(encoding="utf-8"))
        return {str(path) for path in data["paths"]}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def save_record(paths: Set[str]) -> None:
    directory = ensure_config_dir()
    temporary = directory / f".{RECORD_FILE}.tmp"
    temporary.write_text(json.dumps({"paths": sorted(paths)}, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, record_path())


def remember(targets: Iterable[Path]) -> None:
    """Add `targets` to the record, so `sync` keeps them current.

    Best effort: the skill is already written, and failing the command over
    the bookkeeping would report a success as an error.
    """
    record = load_record()
    added = {_key(target) for target in targets} - record
    if added:
        try:
            save_record(record | added)
        except OSError:
            pass


def opted_out() -> bool:
    return os.environ.get(OPT_OUT_VAR, "").strip().lower() not in ("", "0", "false", "no")


def sync() -> List[Tuple[str, Path, str]]:
    """Bring the skill up to date without being asked; return what changed.

    Two jobs, both keyed on the record. A recorded copy that differs from the
    packaged skill is rewritten, and a recorded copy that is gone stays gone:
    the user deleted it. A detected agent with no recorded destination gets the
    skill installed, which is how a newly installed agent is picked up. Only
    user-level destinations are ever discovered here; `--project` copies live
    in a checkout and are left to the command that wrote them.

    A destination that cannot be written is skipped and left unrecorded, so the
    next run tries it again. Each result is (who, path, "installed"|"updated").
    """
    content = read_skill()
    record = load_record()
    labels = {_key(target_for(agent, False)): agent.label for agent in agents()}
    results: List[Tuple[str, Path, str]] = []

    for key in sorted(record):
        target = Path(key)
        if not target.is_file():
            continue
        try:
            outcome = write(target, content)
        except FreepodError:
            continue
        if outcome != "current":
            results.append((labels.get(key, key), target, "updated"))

    discovered: Set[str] = set()
    for agent in detected():
        target = target_for(agent, False)
        key = _key(target)
        if key in record or key in discovered:
            continue
        existed = target.exists()
        try:
            outcome = write(target, content)
        except FreepodError:
            continue
        discovered.add(key)
        if outcome != "current":
            results.append((agent.label, target, "updated" if existed else "installed"))

    if discovered:
        save_record(record | discovered)

    return results
