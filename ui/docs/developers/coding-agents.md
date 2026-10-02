---
title: Coding agents
---

# Coding agents

The client includes a skill: instructions that teach a coding agent how to build and deploy applications for Freepod, including the [runtime contract](runtime.mdx), storage, authentication and debugging.

```bash
freepod skill install
```

installs it for every supported agent whose configuration directory exists on the machine, and prints the installed paths.

| Agent | `--agent` |
| --- | --- |
| Claude Code | `claude` |
| Codex | `codex` |
| OpenCode | `opencode` |
| Amp | `amp` |
| Gemini CLI | `gemini` |
| Qwen Code | `qwencode` |
| Mistral Vibe | `vibe` |

| Option | Effect |
| --- | --- |
| `--agent NAME` | Install for this agent even if it is not detected. Repeatable. |
| `--all` | Install for every supported agent |
| `--project` | Install into the current project's agent directories instead of the home directory |
| `--dest PATH` | Write the skill file to this path, for other agents |

`freepod skill show` prints the skill.

The skill is versioned with the client. After upgrading `freepod`, run `freepod skill install` again.

Signing in needs a person at a browser. Run `freepod login` yourself before asking an agent to deploy.
