"""`freepod skill` — the packaged agent instructions, and where they land.

Two things are worth pinning here. The packaging assertions matter more than
they look: the skill is data inside the wheel, and the failure mode of getting
that wrong is silent — the module imports, the command exists, and only an end
user on a fresh `pip install` discovers the file is not there.

The rest is the agent table. Those paths are external conventions this package
does not control, so the tests assert the *shape* — one directory per agent,
`<dir>/<name>/SKILL.md`, detection by configuration directory — rather than
freezing strings that will legitimately change. The strings that are asserted
are the ones confirmed against a real installation of that agent.
"""

from __future__ import annotations

import pathlib

import pytest

from freepod import EXIT_OK, EXIT_USAGE, UsageError
from freepod.cli import main
from freepod.skill import (
    SKILL_NAME,
    agent_keys,
    agents,
    detected,
    install,
    read_skill,
    select,
    target_for,
    write,
)


@pytest.fixture(autouse=True)
def no_agent_home_overrides(monkeypatch):
    """Neutralize the per-agent home variables a developer may have set.

    `isolated_home` in conftest redirects HOME and XDG_CONFIG_HOME, but
    `CLAUDE_CONFIG_DIR` and `CODEX_HOME` outrank both by design, and a
    developer who has one set would otherwise see this suite write into their
    real configuration directory.
    """
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)


def make_config_dirs(*keys):
    """Create the configuration directories that make those agents 'installed'."""
    for agent in agents():
        if agent.key in keys:
            agent.config_dir.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------- the content


def test_the_skill_ships_inside_the_package():
    """Read through `importlib.resources`, the way an installed copy is read."""
    text = read_skill()
    assert text.startswith("---\n")
    assert f"name: {SKILL_NAME}" in text


def test_the_frontmatter_carries_a_one_line_description():
    """Every supported agent selects on the description; a wrapped one truncates."""
    _, frontmatter, _ = read_skill().split("---", 2)
    described = [ln for ln in frontmatter.splitlines() if ln.startswith("description:")]

    assert len(described) == 1
    assert len(described[0]) > 80


@pytest.mark.parametrize(
    "fact",
    [
        "0.0.0.0:$PORT",       # the failure that produces a healthy, unreachable app
        "S3_BUCKET",           # the one name no SDK supplies on its own
        "Procfile",            # how the start command stops being a guess
        "freepod login",       # the step an agent cannot do for the user
    ],
)
def test_the_skill_states_the_load_bearing_facts(fact):
    """Each of these was, or would have been, a wasted build cycle."""
    assert fact in read_skill()


# ----------------------------------------------------------- the agent table


def test_every_agent_the_readme_promises_is_supported():
    assert set(agent_keys()) == {
        "claude",
        "codex",
        "opencode",
        "amp",
        "gemini",
        "qwencode",
        "vibe",
    }


def test_each_agent_installs_to_its_own_directory():
    """Distinct destinations, or the report would credit one agent for another."""
    user = [agent.user_skills for agent in agents()]
    project = [agent.project_skills for agent in agents()]

    assert len(set(user)) == len(user)
    assert len(set(project)) == len(project)


@pytest.mark.parametrize("agent", agents(), ids=lambda agent: agent.key)
def test_the_layout_is_the_cross_agent_one(agent):
    """`<skills dir>/<skill name>/SKILL.md`, which is what all six read."""
    for project in (False, True):
        target = target_for(agent, project)
        assert target.name == "SKILL.md"
        assert target.parent.name == SKILL_NAME


def test_project_destinations_are_relative_to_the_working_directory():
    for agent in agents():
        assert not agent.project_skills.is_absolute()


@pytest.mark.parametrize(
    ("key", "suffix"),
    [
        # Confirmed against a real installation of each.
        ("claude", ".claude/skills"),
        ("codex", ".codex/skills"),
        ("opencode", "opencode/skills"),
        # Amp reads user skills from ~/.config/agents/skills, not from its own
        # configuration directory — the one row where the two differ.
        ("amp", "agents/skills"),
        ("gemini", ".gemini/skills"),
        # Qwen Code is a Gemini CLI fork whose skills layout mirrors it.
        ("qwencode", ".qwen/skills"),
    ],
)
def test_the_confirmed_paths(key, suffix):
    agent = next(a for a in agents() if a.key == key)
    assert str(agent.user_skills).endswith(suffix)


def test_the_agent_home_variables_outrank_the_home_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "elsewhere"))
    codex = next(agent for agent in agents() if agent.key == "codex")

    assert codex.user_skills == tmp_path / "elsewhere" / "skills"
    assert codex.config_dir == tmp_path / "elsewhere"


# ------------------------------------------------------------- the detection


def test_nothing_is_detected_in_an_empty_home():
    assert detected() == []


def test_only_agents_with_a_configuration_directory_are_detected():
    make_config_dirs("claude", "gemini")

    assert {agent.key for agent in detected()} == {"claude", "gemini"}


def test_selection_falls_back_to_what_is_installed():
    make_config_dirs("opencode")

    assert [agent.key for agent in select((), everything=False)] == ["opencode"]


def test_all_selects_every_agent_including_undetected_ones():
    assert [agent.key for agent in select((), everything=True)] == agent_keys()


def test_named_agents_are_selected_whether_detected_or_not():
    chosen = select(("codex", "amp"), everything=False)

    assert [agent.key for agent in chosen] == ["codex", "amp"]


def test_a_repeated_name_is_selected_once():
    assert len(select(("codex", "codex"), everything=False)) == 1


def test_an_unknown_agent_names_the_ones_that_exist():
    with pytest.raises(UsageError, match="opencode"):
        select(("cursor",), everything=False)


# ---------------------------------------------------------------- the writes


def test_it_installs_for_every_detected_agent(tmp_path):
    make_config_dirs("claude", "codex")
    results = install(detected(), project=False)

    assert [outcome for _, _, outcome in results] == ["installed", "installed"]
    for _agent, target, _outcome in results:
        assert target.read_text(encoding="utf-8") == read_skill()


def test_an_edited_copy_is_replaced_without_asking(tmp_path):
    """No `--force`: the client owns this path and a newer skill must win."""
    target = tmp_path / "SKILL.md"
    write(target)
    target.write_text("a stale skill from an older release\n", encoding="utf-8")

    assert write(target) == "installed"
    assert target.read_text(encoding="utf-8") == read_skill()


def test_an_unchanged_copy_is_reported_rather_than_rewritten(tmp_path):
    target = tmp_path / "SKILL.md"

    assert write(target) == "installed"
    assert write(target) == "current"


def test_missing_parents_are_created(tmp_path):
    target = tmp_path / "a" / "b" / "c" / "SKILL.md"
    write(target)

    assert target.exists()


def test_agents_sharing_a_destination_are_reported_once(monkeypatch, tmp_path):
    """Several agents read each other's directories; a redirect can collide too."""
    shared = tmp_path / "shared"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(shared))
    monkeypatch.setenv("CODEX_HOME", str(shared))

    results = install(select(("claude", "codex"), everything=False), project=False)

    assert [agent.key for agent, _, _ in results] == ["claude"]


# --------------------------------------------------------------- the command


def test_install_writes_for_the_detected_agents(capsys):
    make_config_dirs("claude", "gemini")

    assert main(["skill", "install"]) == EXIT_OK
    captured = capsys.readouterr()
    assert len(captured.out.strip().splitlines()) == 2
    assert "Claude Code" in captured.err and "Gemini CLI" in captured.err


def test_install_reports_which_agents_were_not_detected(capsys):
    make_config_dirs("claude")
    main(["skill", "install"])

    assert "Not detected" in capsys.readouterr().err


def test_install_with_nothing_detected_is_a_usage_error(capsys):
    assert main(["skill", "install"]) == EXIT_USAGE
    assert "--all" in capsys.readouterr().err


def test_agent_and_all_together_are_refused():
    assert main(["skill", "install", "--agent", "codex", "--all"]) == EXIT_USAGE


def test_project_scope_writes_below_the_working_directory(tmp_path, monkeypatch, capsys):
    make_config_dirs("claude")
    monkeypatch.chdir(tmp_path)
    main(["skill", "install", "--project"])

    written = capsys.readouterr().out.strip()
    assert not pathlib.Path(written).is_absolute()
    assert (tmp_path / written).read_text(encoding="utf-8") == read_skill()


def test_dest_writes_exactly_where_it_is_told(tmp_path, capsys):
    target = tmp_path / "anywhere" / "freepod.md"

    assert main(["skill", "install", "--dest", str(target)]) == EXIT_OK
    assert capsys.readouterr().out.strip() == str(target)
    assert target.read_text(encoding="utf-8") == read_skill()


def test_dest_refuses_to_share_the_command_with_a_selector(tmp_path):
    argv = ["skill", "install", "--dest", str(tmp_path / "x.md"), "--all"]

    assert main(argv) == EXIT_USAGE


# ---------------------------------------------------------------- the streams


def test_only_paths_reach_stdout(capsys):
    make_config_dirs("claude", "codex", "gemini")
    main(["skill", "install"])

    captured = capsys.readouterr()
    for line in captured.out.strip().splitlines():
        assert line.endswith(f"{SKILL_NAME}/SKILL.md")
    assert "Installed" in captured.err


def test_show_writes_the_skill_to_stdout(capsys):
    assert main(["skill", "show"]) == EXIT_OK

    captured = capsys.readouterr()
    assert captured.out == read_skill()
    assert captured.err == ""
