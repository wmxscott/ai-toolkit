# ai-toolkit

[![CI](https://github.com/wmxscott/ai-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/wmxscott/ai-toolkit/actions/workflows/ci.yml)

Small plugins for AI coding agents. Each plugin does one thing and installs on its own.

The repository is a Claude Code plugin marketplace. Support for Codex, Pi and OpenCode is added per plugin where the feature makes sense there.

## Plugins

| Plugin | What it does | Claude Code | Codex | Pi | OpenCode |
|---|---|:-:|:-:|:-:|:-:|

## Install

### Claude Code

Add the marketplace once, then install the plugins you want:

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install <plugin>@ai-toolkit
```

Or from inside a session: `/plugin marketplace add wmxscott/ai-toolkit`, then `/plugin install <plugin>@ai-toolkit`.

`claude plugin marketplace update ai-toolkit` picks up new versions.

## Layout

```
.claude-plugin/marketplace.json   the marketplace: one entry per plugin
plugins/<name>/                   one plugin, self-contained
  .claude-plugin/plugin.json      its manifest
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
scripts/validate.sh                 # needs the claude CLI and jq
```

[CLAUDE.md](CLAUDE.md) has the conventions, including how to add a plugin.

## License

[MIT](LICENSE)
