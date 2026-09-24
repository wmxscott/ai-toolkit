# CLAUDE.md

Guidance for AI coding agents working in this repository. `AGENTS.md` is a symlink to this file.

## What this is

A public plugin marketplace for AI coding agents, named `ai-toolkit`. Claude Code is the primary target; Codex, Pi and OpenCode support is added per plugin where it fits. One feature per plugin, so users install only what they want: `claude plugin install <plugin>@ai-toolkit`.

## Layout

```
.claude-plugin/marketplace.json   marketplace manifest, one entry per plugin
plugins/<name>/
  .claude-plugin/plugin.json      plugin manifest
  skills/<skill>/SKILL.md         skills, if any
  hooks/hooks.json                hooks, if any (loaded automatically; don't list it in plugin.json)
  scripts/                        scripts used by hooks and skills
  README.md                       user-facing docs
  tests/                          pytest tests for this plugin
tests/                            repository-wide checks (marketplace consistency)
scripts/validate.sh               validates the marketplace and every plugin
pyproject.toml                    dev tooling only (pytest, ruff, shellcheck), managed with uv
```

## Adding a plugin

1. Create `plugins/<name>/` with `.claude-plugin/plugin.json`: `name` (kebab-case, same as the directory), `description`, `author: {"name": "wmxscott"}`, `homepage`, `repository`, `license: "MIT"`, `keywords`. Don't set `version`: the marketplace falls back to the commit SHA. If you do start versioning a plugin, set it in `plugin.json` only, never in the marketplace entry too.
2. Add an entry to `.claude-plugin/marketplace.json`: `name`, `source: "./plugins/<name>"`, `description`.
3. Add a row to the plugin table in `README.md`, marking which agents it supports.
4. Write `plugins/<name>/README.md` and tests in `plugins/<name>/tests/`.
5. Reference bundled files through `${CLAUDE_PLUGIN_ROOT}` (hooks, skills) or `${CLAUDE_SKILL_DIR}` (skills). Never hard-code an install path: the plugin is copied into a versioned cache directory that changes on every update.
6. Run everything under "Checks" below.

`tests/test_marketplace.py` fails if a plugin directory, its marketplace entry and its README row get out of sync.

## Checks

CI runs all of these on every push to `main` and every pull request:

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
git ls-files -co --exclude-standard '*.sh' | xargs uv run shellcheck
scripts/validate.sh
gitleaks dir . && gitleaks git .
```

`scripts/validate.sh` runs `claude plugin validate` on the marketplace and on every plugin it lists. It fails on any error or warning, like `--strict`, except the missing-version warning (see "Adding a plugin"). It needs `jq` and the `claude` CLI, but no login. Tests that drive shell scripts build their environment from scratch and stub external tools on `PATH`, so they never touch the real terminal, multiplexer or `$HOME`.

## Style

- Shell scripts are bash, must pass shellcheck, and must still run on macOS's `/bin/bash` 3.2.
- Hook scripts fail safe: exit 0 and do nothing when a dependency or input is missing. A hook must never block a session.
- Comments are sparse. Write one only for what the code can't say: a non-obvious reason, a workaround, a constraint. No narration.
- Docs are concise and plain. No filler.

## Public repository: no personal data

Everything here is public, including commit messages and history. Never commit personal data: real names, usernames other than the project handle, email addresses, home directory paths, host or machine names, employer or work details, device serial numbers, IP addresses, or tokens. Use `~` or `$HOME` and generic examples (`login bug`, `~/src/project`). The only identity in the repo is the project handle `wmxscott` and its GitHub URLs; manifests carry no email. Run gitleaks before committing, and read your diff for anything personal it can't catch.
