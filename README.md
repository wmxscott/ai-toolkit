# ai-toolkit

[![CI](https://github.com/wmxscott/ai-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/wmxscott/ai-toolkit/actions/workflows/ci.yml)

Small plugins for AI coding agents. Each plugin does one thing and installs on its own.

The repository is a Claude Code plugin marketplace, and a Codex one for the plugins marked below. Support for Codex, Pi and OpenCode is added per plugin where the feature makes sense there.

## Plugins

| Plugin | What it does | Claude Code | Codex | Pi | OpenCode |
|---|---|:-:|:-:|:-:|:-:|
| [terminal-title](plugins/terminal-title) | Titles the terminal tab after the current task, in Herdr, tmux or any xterm-compatible terminal | ✓ | | | |
| [git-sync](plugins/git-sync) | Fast-forwards the current git branch to its upstream before work starts, and stops when it has diverged | ✓ | ✓ | | |
| [statusline](plugins/statusline) | Three-line NerdFont statusline: git, model, effort, context, cost and rate limits, in Catppuccin colours that follow the system theme | ✓ | | | |
| [prod-guard](plugins/prod-guard) | Runs a prompt against a production cloud account under a read-only guard that lasts for the rest of the conversation | ✓ | | | |
| [chat-style](plugins/chat-style) | Chat output style: Claude as a thinking partner for ideation, architecture and exploratory discussion, rather than a task executor | ✓ | | | |

## Install

### Claude Code

Add the marketplace once, then install the plugins you want:

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install <plugin>@ai-toolkit
```

Or from inside a session: `/plugin marketplace add wmxscott/ai-toolkit`, then `/plugin install <plugin>@ai-toolkit`.

`claude plugin marketplace update ai-toolkit` picks up new versions.

### Codex

Installs without the TUI:

```sh
codex plugin marketplace add wmxscott/ai-toolkit
codex plugin add <plugin>@ai-toolkit
```

Or add the marketplace as above, then pick the plugin in `/plugins` inside a session. Start a new thread to load it.

To update, run `codex plugin marketplace upgrade ai-toolkit`, then `codex plugin add <plugin>@ai-toolkit` again.

## Layout

```
.claude-plugin/marketplace.json   the Claude Code marketplace: one entry per plugin
.agents/plugins/marketplace.json  the Codex marketplace: one entry per Codex plugin
plugins/<name>/                   one plugin, self-contained
  .claude-plugin/plugin.json      its Claude Code manifest
  plugin.json                     its Codex manifest, if it supports Codex
  README.md                       what it does and how to use it
  tests/                          its tests
tests/                            checks across the whole repository
scripts/validate.sh               validates the marketplace and every plugin
```

Each plugin's README covers its requirements and behaviour.

## Contributing

Issues and pull requests are welcome. Development needs [uv](https://docs.astral.sh/uv/):

```sh
uv run pytest
uv run ruff check && uv run ruff format --check
git ls-files -co --exclude-standard '*.sh' | xargs uv run shellcheck
scripts/validate.sh                 # needs the claude CLI and jq; uses codex too if installed
```

[CLAUDE.md](CLAUDE.md) has the conventions, including how to add a plugin.

## License

[MIT](LICENSE)
