# ai-toolkit

[![CI](https://github.com/wmxscott/ai-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/wmxscott/ai-toolkit/actions/workflows/ci.yml)

Small plugins for AI coding agents. Each plugin does one thing and installs on its own.

The repository is a Claude Code plugin marketplace, a Codex one, and a Pi and OpenCode package, each for the plugins marked below. Support for Codex, Pi and OpenCode is added per plugin where the feature makes sense there.

## Plugins

| Plugin | What it does | Claude Code | Codex | Pi | OpenCode |
|---|---|:-:|:-:|:-:|:-:|
| [terminal-title](plugins/terminal-title) | Titles the terminal tab after the current task, in Herdr, tmux or any xterm-compatible terminal | ✓ | | | |
| [git-sync](plugins/git-sync) | Fast-forwards the current git branch to its upstream before work starts, and stops when it has diverged | ✓ | ✓ | | |
| [statusline](plugins/statusline) | Three-line NerdFont statusline: git, model, effort, context, cost and rate limits, in Catppuccin colours that follow the system theme | ✓ | | | |
| [prod-guard](plugins/prod-guard) | Runs a prompt against a production cloud account under a read-only guard that lasts for the rest of the conversation | ✓ | | | |
| [chat-style](plugins/chat-style) | Chat output style: Claude as a thinking partner for ideation, architecture and exploratory discussion, rather than a task executor | ✓ | | | |
| [security-key-git-signing](plugins/security-key-git-signing) | Checks a hardware security key is plugged in before git signs a commit or tag with GPG, and asks for it if not | ✓ | ✓ | | |
| [stacked-planning](plugins/stacked-planning) | Plans and lands work that spans several pull requests as ordered stacks, with a PR size gate and a stack overlap check | ✓ | ✓ | ✓ | ✓ |
| [theme-sync](plugins/theme-sync) | Switches Claude Code between its light and dark themes the moment the macOS appearance changes | ✓ | | | |

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

### Pi

The repository is a [Pi package](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md) that exposes the skills of every plugin with a Pi tick, and nothing else:

```sh
pi install git:github.com/wmxscott/ai-toolkit
```

`pi update` picks up new versions. To load only some plugins, filter the package's `skills` in `~/.pi/agent/settings.json`.

### OpenCode

The repository is also an [OpenCode plugin](https://opencode.ai/docs/plugins/) that registers the same skills. Add it to `opencode.json`, then restart OpenCode. OpenCode 1:

```json
{
  "plugin": ["ai-toolkit@git+https://github.com/wmxscott/ai-toolkit.git"]
}
```

OpenCode 2 (`opencode2`, 2.0.4 or later) names the key `plugins`:

```json
{
  "plugins": ["ai-toolkit@git+https://github.com/wmxscott/ai-toolkit.git"]
}
```

OpenCode caches the install. If a restart doesn't pick up a new version, clear its package cache (`~/.cache/opencode`).

## Layout

```
.claude-plugin/marketplace.json   the Claude Code marketplace: one entry per plugin
.agents/plugins/marketplace.json  the Codex marketplace: one entry per Codex plugin
plugins/<name>/                   one plugin, self-contained
  .claude-plugin/plugin.json      its Claude Code manifest
  plugin.json                     its Codex manifest, if it supports Codex
package.json                      the Pi package: lists each Pi and OpenCode plugin's skills
.opencode/plugins/ai-toolkit.js   the OpenCode plugin: registers those same skills
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
