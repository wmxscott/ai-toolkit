# arbiter

> [!WARNING]
> **Highly experimental. This is an idea, not a finished plugin.** It lives only on the unmerged `experimental/arbiter` branch, is not on `main`, and may never ship. Expect breaking changes or deletion without notice.
>
> Once enabled, arbiter can **hold Claude's turn open** until your gates pass, for up to 9 minutes per stop, and its judge gates **spend model calls** (Claude and Codex) on every stop that has something new to review. It does nothing in a repository until you configure it.

Declarative quality gates that hold a coding agent's turn open until the work passes.

Claude Code ends its turn whenever it believes it is done. Nothing checks that belief. Arbiter adds a `Stop` hook that runs a project's declared gates before the turn may end: lint, tests, build, and LLM judges that review the change with fresh context, including cross-model judges where Codex audits Claude's work.

Gates are declared in TOML, so arbiter works with any language. A Rust repository and a TypeScript one differ only in their config.

The reasoning behind each decision is in [docs/design.md](docs/design.md).

## Install

Claude Code only. Needs `git`, and Python 3.11 or later or [uv](https://docs.astral.sh/uv/). Judge gates also need the `claude` or `codex` CLI, logged in.

The plugin is only in the marketplace on this branch, so add the marketplace at the branch:

```sh
claude plugin marketplace add 'https://github.com/wmxscott/ai-toolkit.git#experimental/arbiter'
claude plugin install arbiter@ai-toolkit
```

This replaces a marketplace already added from `main` under the same name. To go back, remove it and add `wmxscott/ai-toolkit` again.

The plugin registers the `Stop` hook and puts `arbiter` on the PATH of Claude's Bash tool. In your own shell, run `bin/arbiter` from a clone of this branch, or from the plugin's install directory under `~/.claude/plugins/cache/`, which changes on every update.

Arbiter is a silent no-op in any repository with no config, so it is safe to leave enabled everywhere.

## Quick start

```sh
arbiter init                  # list the templates
arbiter init typescript       # write arbiter.toml at the repository root
arbiter plan                  # check what it gates before trusting it
arbiter run                   # run the gates now, without a stop event
```

## Configuration

Four layers, merged by task name. A later layer wins, field by field:

| Layer | Path | Purpose |
|---|---|---|
| Built-in | `config/defaults.toml` in the plugin | baseline gates, all disabled |
| User | `~/.config/arbiter/defaults.toml` | your baseline for every repository |
| Project | `<repo>/arbiter.toml` | project gates, committed |
| Local | `<repo>/arbiter.local.toml` | personal overrides, gitignored |

The built-in layer only applies when one of the others exists. `XDG_CONFIG_HOME` replaces `~/.config`.

A minimal project config:

```toml
[[task]]
name = "test"
runner = "shell"
command = "cargo test"
paths = ["**/*.rs"]

[[task]]
name = "security"       # the built-in task, switched on
enabled = true
paths = ["**/auth/**", "**/*.sql"]
```

### Overriding the built-in data

`~/.config/arbiter/` mirrors the plugin's `config/` directory. A file there takes the place of the built-in one of the same name:

| Path under `~/.config/arbiter/` | Overrides |
|---|---|
| `defaults.toml` | adds the user layer on top of the built-in defaults |
| `judges/<name>.md` | a judge persona |
| `output-styles/<name>.md` | a judge output style |
| `templates/<name>.toml` | an `arbiter init` template, or adds a new one |
| `schema/verdict.schema.json` | the schema Codex judges answer in |

A repository can also hold personas in `.arbiter/judges/` or `judges/`, and output styles in `.arbiter/output-styles/`. Those win over both.

### Task fields

| Field | Default | Notes |
|---|---|---|
| `name` | required | unique; the merge key across layers |
| `runner` | required | `shell`, `claude` or `codex` |
| `command` | none | required for `runner = "shell"` |
| `paths` | all files | globs matched against the change set; omit to always run |
| `timeout` | `120` | seconds |
| `required` | `true` | `false` reports the result without ever blocking |
| `enabled` | `true` | `false` in a later layer switches a gate off |
| `agent` | none | judge persona, resolved to a file |
| `prompt` | none | inline judge instruction |
| `prompt_file` | none | judge instruction from a file, relative to the repository |
| `output_style` | `verdict` | judge output style; `claude` runner only; `""` for none |
| `model` | runner default | passed through to the judge |
| `effort` | runner default | `low`, `medium`, `high`, `xhigh`, `max` for `claude`; `minimal`, `low`, `medium`, `high`, `xhigh` for `codex` |

`prompt` and `prompt_file` are mutually exclusive. A judge needs at least one of `agent`, `prompt` or `prompt_file`. `effort` on a `shell` task is an error.

`[arbiter] budget` caps a whole run, 540 seconds by default. It must stay below the hook's 600-second timeout.

### The verdict output style

Claude judges answer in the built-in `verdict` style: one JSON object, only findings it can point at. Arbiter inlines the style into the judge's system prompt rather than selecting it by name, so it works whether or not the plugin is enabled in the judge's own session, and it never shows up in your `/output-style` menu. See [docs/design.md](docs/design.md#output-style).

## Usage

```sh
arbiter init [template]  # scaffold arbiter.toml from a template (--force to replace)
arbiter run              # run gates against the current change set
arbiter run --task NAME  # run one task
arbiter run --no-cache   # ignore cached verdicts
arbiter plan             # show what would run and why, without running it
arbiter status           # cached verdicts for the current change set
arbiter clean            # clear the cache and judge scratch
arbiter hook             # Stop-hook entry point; reads hook JSON on stdin
```

## How it behaves

**Change set.** The diff against the branch's merge-base with the default branch, plus untracked files. Work already committed on the branch is still gated.

**Blocking.** When a required gate fails, the hook answers `{"decision": "block"}` with the findings as the reason, and Claude keeps working. It always exits 0 and always prints one JSON object.

**Caching.** Verdicts are keyed by a content hash of the change set, stored in `<repo>/.arbiter/` (which ignores itself in git). A passed gate is skipped until a file in the change set changes. On a stop with no changes, failures are replayed too, so an idle turn spends nothing. `arbiter run` re-runs failures; use it to retry a flaky gate.

A gate that writes a file git doesn't ignore changes the change set on every run, so it never hits the cache.

**Loop guard.** After three blocks in a row on an identical change set, arbiter lets the turn end and warns you instead of trapping the session. An invalid config is treated the same way.

**Judge isolation.** Judges can read the repository but write only to a scratch directory under `~/.local/state/arbiter/scratch/` (or `$XDG_STATE_HOME`). The OS sandbox enforces this on both runners. Judges also run from the scratch directory, so neither CLI's bookkeeping lands in the repository.

> **Limitation:** Codex's sandbox treats `/tmp` and `$TMPDIR` as writable regardless of workspace, so a repository under a temp directory is not protected from a Codex judge.

**Recursion guard.** Judges run with `ARBITER_CHILD=1`, and the hook does nothing when it sees it. Both CLIs fire their own `Stop` hooks, so without this a judge would re-enter the gate.

**Failing safe.** Arbiter never blocks a turn over its own faults. An internal error, or no usable Python, lets the turn end with a warning. An invalid config does block, because a gate that silently stops gating looks exactly like one that passes.

## Costs

Rough figures for a trivial prompt:

| Runner | Wall clock | Tokens |
|---|---|---|
| `codex exec` | ~1.7s | ~10k |
| `claude -p` (lean flags) | ~5.6s | ~21k |

Judges run concurrently, each with its own timeout, inside the run budget.
