# CLAUDE.md

Guidance for AI coding agents working in this repository. `AGENTS.md` is a symlink to this file.

## What this is

A public plugin marketplace for AI coding agents, named `ai-toolkit`. Claude Code is the primary target; Codex, Pi and OpenCode support is added per plugin where it fits. One feature per plugin, so users install only what they want: `claude plugin install <plugin>@ai-toolkit`.

## Layout

```
.claude-plugin/marketplace.json   Claude Code marketplace, one entry per plugin
.agents/plugins/marketplace.json  Codex marketplace, one entry per Codex plugin
package.json                      Pi package: `pi.skills` lists each Pi/OpenCode plugin's skills; `pi.extensions`, `pi.themes` the files in pi/
.opencode/plugins/ai-toolkit.js   OpenCode plugin: adds those same skill directories
plugins/<name>/
  .claude-plugin/plugin.json      Claude Code plugin manifest
  plugin.json                     Codex plugin manifest, only if the plugin supports Codex
  .codex-plugin/plugin.json       Codex plugin manifest instead, for a plugin with hooks
  skills/<skill>/SKILL.md         skills, if any
  skills/<skill>/scripts/         files a skill runs, if it must work outside Claude Code
  hooks/hooks.json                hooks, if any (loaded automatically; don't list it in plugin.json)
  scripts/                        scripts used by hooks and skills
  README.md                       user-facing docs
  tests/                          pytest tests for this plugin
pi/extensions/, pi/themes/        Pi extensions and themes, not tied to any plugin (see "Pi extensions")
pi/README.md                      their user-facing docs
tests/                            repository-wide checks (marketplace, Codex, Pi and OpenCode)
scripts/validate.sh               validates the marketplace and every plugin
pyproject.toml                    dev tooling only (pytest, ruff, shellcheck), managed with uv
```

## Adding a plugin

1. Create `plugins/<name>/` with `.claude-plugin/plugin.json`: `name` (kebab-case, same as the directory), `description`, `author: {"name": "wmxscott"}`, `homepage`, `repository`, `license: "MIT"`, `keywords`. Don't set `version`: the marketplace falls back to the commit SHA. If you do start versioning a plugin, set it in `plugin.json` only, never in the marketplace entry too.
2. Add an entry to `.claude-plugin/marketplace.json`: `name`, `source: "./plugins/<name>"`, `description`.
3. Add a row to the plugin table in `README.md`, marking which agents it supports.
4. Write `plugins/<name>/README.md` and tests in `plugins/<name>/tests/`.
5. Reference bundled files through `${CLAUDE_PLUGIN_ROOT}` (hooks, skills) or `${CLAUDE_SKILL_DIR}` (skills). Never hard-code an install path: the plugin is copied into a versioned cache directory that changes on every update. A skill that other agents load must not use either variable: see "Pi and OpenCode support".
6. Run everything under "Checks" below.

`tests/test_marketplace.py` fails if a plugin directory, its marketplace entry and its README row get out of sync.

## Codex support

Add it only when the plugin works in Codex without its Claude-only parts. Skills carry over. Hooks can too: Codex reads `hooks/hooks.json` in Claude's format, sets `CLAUDE_PLUGIN_ROOT` for hook commands, names its shell tool `Bash` and sends a Claude-shaped payload. It runs a plugin's hooks only after the user trusts them in `/hooks`, so say so in the plugin's README.

1. Write the Codex manifest. Copy `name`, `description`, `author`, `homepage`, `repository`, `license` and `keywords` from the Claude manifest verbatim, and add `interface` (`displayName`, `shortDescription`, `developerName: "wmxscott"`, `category`, `capabilities`, `websiteURL`).
   - Without hooks: `plugins/<name>/plugin.json` in the [Agent Plugins](https://agent-plugins.org) format (`"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"`), which Codex prefers, with `interface` under `extensions."com.openai"`.
   - With hooks: `plugins/<name>/.codex-plugin/plugin.json`, Codex's own format, with `interface` at the top level. Codex (0.156.1) loads no hooks for an Agent Plugins manifest.
   - Never both: Codex reads the root manifest first, so a second one would only drift.
2. Add an entry to `.agents/plugins/marketplace.json`: `name`, `source: {"source": "local", "path": "./plugins/<name>"}`, `policy: {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}`, `category`.
3. Tick the Codex column in the `README.md` table.

The two manifests don't collide. Claude Code reads only `.claude-plugin/`. Codex reads `.agents/plugins/marketplace.json` in preference to `.claude-plugin/marketplace.json`, and a plugin's root `plugin.json`, then `.codex-plugin/plugin.json`, in preference to `.claude-plugin/plugin.json`. So a Claude-only plugin stays out of Codex as long as it has no Codex marketplace entry.

Leave `version` out of both manifests (the tests require them to agree). Codex then reports the plugin as `1.0.0` (or `local` for a `.codex-plugin` manifest), but `codex plugin add` still recopies it on reinstall.

Codex ignores `disable-model-invocation`. To keep it from running a skill on its own, add `skills/<skill>/agents/openai.yaml` with `policy:` / `allow_implicit_invocation: false`; users still run it as `$<plugin>:<skill>`. Codex doesn't substitute `$ARGUMENTS` either, so a skill that reads it must say where the arguments are otherwise: the rest of the user's message.

`tests/test_codex.py` checks the Codex marketplace and manifests: format, schema, entry shape, agreement with the Claude manifest, and the README column.

## Pi and OpenCode support

Pi and OpenCode have no marketplace; from the plugins, both load plain [Agent Skills](https://agentskills.io/specification) and nothing else. So a plugin supports both or neither, and only when its skills work without Claude-only parts. Such a plugin must support Codex too.

The exception is a plugin whose skills rely on its hooks, which Pi can run as an extension in `pi/` (see "Pi extensions") and OpenCode can't: pr-tracker. List its skills in `pi.skills` and in `PI_ONLY` in `.opencode/plugins/ai-toolkit.js`, and tick only the Pi column.

1. Add `./plugins/<name>/skills` to `pi.skills` in the root `package.json`. That list is the skills `pi install git:github.com/wmxscott/ai-toolkit` loads, and `.opencode/plugins/ai-toolkit.js` (the package's `main`, loaded through `"plugin": ["ai-toolkit@git+https://github.com/wmxscott/ai-toolkit.git"]`) reads the same list. The module's default export carries both OpenCode plugin shapes: `server`, whose config hook adds the directories to `skills.paths` (OpenCode 1, config key `plugin`), and `setup`, which adds each skill through `ctx.skill.transform` (OpenCode 2, config key `plugins`). `setup` returns early when the context has no skill domain; OpenCode 1 doesn't call it. OpenCode 2 resolves a git or npm install through the package `main`, so keep it pointing at the module. Keep the package `private`, with no dependencies, and add no root `skills/`, `extensions/`, `prompts/` or `themes/`: Pi would load them from every install.
2. Tick the Pi and OpenCode columns in the `README.md` table (Pi alone for a `PI_ONLY` plugin), and give the plugin's README an install section per agent.
3. Make the skills portable:
   - Frontmatter is `name` (the directory name) and `description` (at most 1024 characters, strict YAML: no `: ` in a plain scalar, or a strict parser drops the skill).
   - Reference bundled files relative to the skill's own directory, and say so in the skill: "`scripts/` is relative to the directory holding this `SKILL.md`". Every agent reports that directory when it loads a skill: Claude Code and OpenCode print "Base directory for this skill", Codex and Pi give the `SKILL.md` path. None of the others expands `${CLAUDE_PLUGIN_ROOT}` or `${CLAUDE_SKILL_DIR}`, and in a shell an unset variable turns the path into a wrong one silently. For a command, use a placeholder such as `<scripts>` that the skill defines once; run literally, it fails loudly.
   - A file shared by several skills lives in one of them and the others reach it as `../<skill>/...`. Pi and OpenCode load the skills in place and Claude Code and Codex copy the whole plugin, so sibling paths hold in all four.
   - Run scripts through their interpreter (`uv run --script x.py`, `python3 x.py`) rather than relying on the executable bit.

`tests/test_agents.py` checks the package, the OpenCode module under fake OpenCode 1 and 2 contexts (with node), that Claude, Codex and Pi load the same skills, and the README columns against `pi.skills` and `PI_ONLY`.

## Pi extensions

`pi/` holds Pi [extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md) and [themes](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/themes.md). They aren't plugins: no other agent can load them, and `plugins/` is one Claude Code plugin per directory. An extension can stand in for a plugin's hooks, as `pr-tracker.ts` does for pr-tracker's: Pi doesn't read `hooks.json`, but its `tool_result` and `agent_settled` events do the same job. The same Pi package installs them with the skills, and users drop either side with a package filter in their Pi settings (`"skills": []`, or `"extensions": [], "themes": []`), documented in the README.

1. Put the file in `pi/extensions/<name>.ts` (a single file) or `pi/themes/<name>.json` (`name` inside must match), and list its path in `pi.extensions` or `pi.themes` in `package.json`. Pi loads only what those lists name.
2. Import only `node:*` builtins and the packages Pi supplies (`@earendil-works/pi-coding-agent`, `pi-ai`, `pi-agent-core`, `pi-tui`, `typebox`). The package has no dependencies, and adding any would also install them for OpenCode.
3. Follow Pi's lifecycle: start watchers and timers in `session_start`, stop them in `session_shutdown`, and guard terminal-only code with `ctx.mode === "tui"`. Silence child-process stderr, or it scribbles over the TUI.
4. Keep third-party code's copyright and licence notice at the top of the file, and credit it in `pi/README.md`.
5. Add a row to the extension table in `README.md` and a section to `pi/README.md`.

`tests/test_pi.py` checks the lists match `pi/`, the themes against Pi's schema (`tests/schemas/pi-0.87.1-theme.schema.json`), imports, attribution and the READMEs. It parses each extension with node's own TypeScript stripper when node is 22.13 or later. When `pi` is on `PATH`, it also loads the package with Pi in a throwaway home, with and without the skills filter. For a full type-check, install `@earendil-works/pi-coding-agent` (the version of your Pi), `typescript` and `@types/node` in a scratch directory outside the repository. Give it a `tsconfig.json` with `strict`, `noEmit`, `moduleResolution: "Bundler"`, `paths: {"*": ["./node_modules/*"]}` and `include` pointing at `pi/extensions/*.ts`, then run `tsc -p`.

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

`scripts/validate.sh` runs `claude plugin validate` on the marketplace and on every plugin it lists. It fails on any error or warning, like `--strict`, except the missing-version warning (see "Adding a plugin"). It needs `jq` and the `claude` CLI, but no login. Codex has no validate command, so when `codex` is installed the script installs every Codex plugin into a throwaway `CODEX_HOME` and checks that Codex loads each skill and hook and lists each skill for the model, except one whose `agents/openai.yaml` forbids implicit use; it never touches `~/.codex`. Tests that drive shell scripts build their environment from scratch and stub external tools on `PATH`, so they never touch the real terminal, multiplexer or `$HOME`.

## Style

- Shell scripts are bash, must pass shellcheck, and must still run on macOS's `/bin/bash` 3.2.
- Hook scripts fail safe: exit 0 and do nothing when a dependency or input is missing. A hook must never block a session.
- Comments are sparse. Write one only for what the code can't say: a non-obvious reason, a workaround, a constraint. No narration.
- Docs are concise and plain. No filler.

## Public repository: no personal data

Everything here is public, including commit messages and history. Never commit personal data: real names, usernames other than the project handle, email addresses, home directory paths, host or machine names, employer or work details, device serial numbers, IP addresses, or tokens. Use `~` or `$HOME` and generic examples (`login bug`, `~/src/project`). The only identity in the repo is the project handle `wmxscott` and its GitHub URLs; manifests carry no email. Run gitleaks before committing, and read your diff for anything personal it can't catch.
