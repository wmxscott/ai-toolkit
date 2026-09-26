# ai-toolkit

[![CI](https://github.com/wmxscott/ai-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/wmxscott/ai-toolkit/actions/workflows/ci.yml)

Small plugins for AI coding agents. Each plugin does one thing and installs on its own.

The repository is a Claude Code plugin marketplace, a Codex one, and a Pi and OpenCode package, each for the plugins marked below. Support for Codex, Pi and OpenCode is added per plugin where the feature makes sense there. The Pi package also carries a few [Pi extensions](#pi-extensions) of its own.

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
| [pr-tracker](plugins/pr-tracker) | Tracks the pull requests a session opens and tells it when their checks or reviews change, through the [pr-tracker](https://github.com/wmxscott/pr-tracker) CLI | ✓ | ✓ | ✓ | |
| [herdr](plugins/herdr) | Starts each piece of work in its own git worktree, opened as its own [Herdr](https://herdr.dev) workspace, with [herdr-wkt](https://github.com/wmxscott/herdr-wkt) | ✓ | ✓ | | |

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

The repository is a [Pi package](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md) that exposes the skills of every plugin with a Pi tick, plus the [Pi extensions](#pi-extensions) and their themes:

```sh
pi install git:github.com/wmxscott/ai-toolkit
```

`pi update --extensions` picks up new versions. To load only part of the package, see [Choosing what loads](#choosing-what-loads).

### OpenCode

The repository is also an [OpenCode plugin](https://opencode.ai/docs/plugins/) that registers the skills of every plugin with an OpenCode tick. Add it to `opencode.json`, then restart OpenCode. OpenCode 1:

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

## Pi extensions

[Pi](https://github.com/earendil-works/pi) extensions and themes, installed by the same Pi package as the skills above. [pi/README.md](pi/README.md) has the details.

| Extension | What it does |
|---|---|
| [statusline](pi/README.md#statuslinets) | Three-line NerdFont footer: git, model, effort, context, tokens and cost, in Catppuccin colours that follow the system theme |
| [theme-switcher](pi/README.md#theme-switcherts) | Switches Pi between Catppuccin Latte and Macchiato the moment the macOS appearance changes, through [theme-monitor](https://github.com/wmxscott/theme-monitor) |
| [pr-tracker](pi/README.md#pr-trackerts) | Runs the [pr-tracker plugin](plugins/pr-tracker)'s hooks in Pi: records the PRs a session opens and hands their check and review changes back to it, waking it when it's idle |
| [display](pi/README.md#displayts) | Draws code blocks in replies inside a frame labelled with their language. Adapted from [pix-display](https://github.com/xynogen/pix-mono/tree/main/packages/pix-display) by xynogen (MIT) |

The themes are `catppuccin-latte` and `catppuccin-macchiato`.

```sh
pi install git:github.com/wmxscott/ai-toolkit
```

### Choosing what loads

`pi install` loads everything in the package. To narrow it, replace the package's entry in `~/.pi/agent/settings.json` with the object form, which filters each resource type. Only the extensions and themes, no skills:

```json
{
  "packages": [
    {
      "source": "git:github.com/wmxscott/ai-toolkit",
      "skills": []
    }
  ]
}
```

Every extension and theme, and of the skills only pr-tracker's:

```json
{
  "packages": [
    {
      "source": "git:github.com/wmxscott/ai-toolkit",
      "skills": ["plugins/pr-tracker/skills/*"]
    }
  ]
}
```

Skill patterns match each skill's directory: write them without a leading `./`, and keep the `/*`, since `plugins/pr-tracker/skills` alone matches nothing.

Only the skills: `"extensions": [], "themes": []`. A list keeps the matching files, with paths relative to the repository root and `!` to exclude, so `"extensions": ["!pi/extensions/display.ts"]` loads every extension except display. `pi config` toggles the same resources interactively. See Pi's [package filtering](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md#select-package-resources).

## Layout

```
.claude-plugin/marketplace.json   the Claude Code marketplace: one entry per plugin
.agents/plugins/marketplace.json  the Codex marketplace: one entry per Codex plugin
plugins/<name>/                   one plugin, self-contained
  .claude-plugin/plugin.json      its Claude Code manifest
  plugin.json                     its Codex manifest, if it supports Codex
  .codex-plugin/plugin.json       or this one instead, if the plugin has hooks
  README.md                       what it does and how to use it
  tests/                          its tests
package.json                      the Pi package: each Pi and OpenCode plugin's skills, and pi/
.opencode/plugins/ai-toolkit.js   the OpenCode plugin: registers those same skills
pi/                               Pi extensions and themes
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
