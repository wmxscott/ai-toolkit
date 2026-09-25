# Arbiter — Stop-hook quality gate framework

**Status:** Experimental. An idea under trial on the `experimental/arbiter`
branch, not on `main`, and it may never ship.

## Problem

Coding agents end their turn whenever they believe they are done. Nothing
verifies that belief. Lint may be broken, tests may fail, and a security-
sensitive change may never be reviewed by anything other than the model that
wrote it.

Arbiter is a Stop-hook framework that holds the turn open until a project's
declared quality gates pass. Projects declare their own gates in TOML, so the
framework stays language-agnostic: a Rust repo and a TypeScript repo differ only
in their config. Gates include deterministic commands (lint, test, build) and
LLM judges that review the change with fresh context, including cross-model
judges where Codex audits Claude's output.

## Scope

Claude Code only, for this iteration. Only Claude Code has a true blocking Stop
hook with a `decision: "block"` contract. OpenCode plugins receive `session.idle`,
Pi extensions use a different contract, and Codex has no stop surface at all.
The runner is a standalone CLI with no Claude-specific logic in its core, so
other hosts can be adapted later without redesign.

## Key decisions

| Decision | Choice |
|---|---|
| Host | Claude Code only, for now |
| Packaging | A Claude Code plugin: the Stop hook, the CLI on `bin/`, and built-in data |
| Task model | Uniform `[[task]]` array with a `runner` field |
| Judge invocation | Shell-out subprocess for every judge; no agent hooks |
| Change set | `git diff` vs merge-base with default branch, plus untracked files |
| Caching | Content hash of the change set keys a verdict cache |
| Config | Four layers: built-in → user → repo → local |
| Judge filesystem access | Read anywhere, write only to a per-run scratch dir |
| Judge output style | Inlined into the judge's system prompt, not selected by name |

## Verified constraints

These were established empirically against `claude 2.1.233` and `codex 0.146.0`.
They are recorded because several contradict the obvious assumption and would
otherwise be re-derived incorrectly.

**`claude --bare` is unusable under a subscription login.** It states that
"OAuth and keychain are never read" and requires `ANTHROPIC_API_KEY` or an
`apiKeyHelper`. With a keychain login, `claude --bare -p` fails with
`Not logged in · Please run /login`. `--bare` therefore cannot serve as either
the hermetic-context switch or the recursion guard.

**Judge spawn overhead.** A trivial prompt through `claude -p` loaded 32,446
tokens of system prompt, CLAUDE.md, plugins and skills (10.3s, $0.066 on Haiku).
The lean flag set below reduces that to 21,458 tokens and 5.6s. The remainder is
built-in tool definitions and cannot be trimmed without `--bare`.

**Codex is the cheaper judge.** `codex exec` completed the same prompt in 1.7s
using 10,435 tokens — roughly 3x faster and half the tokens of a lean
`claude -p`.

**Both CLIs fire their own Stop hooks.** `codex exec` emits `hook: Stop` on
completion. A judge subprocess that re-enters an arbiter-gated agent is a fork
bomb, so a recursion guard is mandatory and must cover both runners.

**`turns` is not enforceable anywhere.** `claude 2.1.233` has no `--max-turns`
flag, `codex exec` has no turn limit, and native agent hooks fix it at 50. The
key is omitted from the schema rather than shipped as a no-op.

**Stop hooks fail open on timeout.** A timed-out hook "is canceled and renders
no decision. The turn ends normally." The default ceiling is 600s. Arbiter must
therefore reserve headroom and treat its own timeout as a visible failure rather
than a silent pass.

## Architecture

Arbiter is a single CLI. The Stop hook is a thin invocation of it, so the entire
engine is exercisable from a terminal without triggering a stop event.

```
Stop hook fires → bash ${CLAUDE_PLUGIN_ROOT}/bin/arbiter hook
  │
  ├─ 1. Recursion guard: ARBITER_CHILD set? → {} immediately
  ├─ 2. Resolve config: walk up to git root, merge the layers
  │       no user or repo config → {} (silent no-op)
  ├─ 3. Compute change set: merge-base diff + untracked files
  ├─ 4. Hash change set → cache key
  ├─ 5. Select tasks: glob match against change set; drop cache hits
  ├─ 6. Execute remaining tasks concurrently, each with its own timeout
  ├─ 7. Persist verdicts keyed by hash
  └─ 8. All required tasks passed → {}
         otherwise → {"decision": "block", "reason": <findings>}
```

The hook always exits 0 and always writes one JSON object to stdout. Blocking
through `decision: "block"` rather than exit 2 lets the same channel carry a
`systemMessage` to the user when arbiter lets a turn end over a problem: the
loop guard releasing, or an internal error.

### Components

- **Config resolver** — locates and merges the layers, validates the schema,
  resolves `agent` / `prompt_file` / `output_style` references to files.
- **Change set** — computes the file list and content hash.
- **Task selector** — glob gating and cache filtering.
- **Runners** — `shell`, `claude`, `codex`. One interface: given a task and a
  change set, return a verdict. This is the only extension point; adding a
  runner is not a redesign.
- **State store** — verdict cache and block counter under `.arbiter/`.
- **Reporter** — renders findings for the block reason or a terminal.

## Configuration

Four layers, merged by task name, later layer wins:

1. `<plugin>/config/defaults.toml` — built-in baseline, every task disabled
2. `~/.config/arbiter/defaults.toml` — the user's baseline for every repo
3. `<repo>/arbiter.toml` — project gates, committed and shared
4. `<repo>/arbiter.local.toml` — personal overrides, gitignored

The built-in layer joins only when at least one of the others exists. With no
user or repo config, arbiter is a silent no-op, so the plugin is safe to enable
everywhere. `XDG_CONFIG_HOME` replaces `~/.config`.

### Task schema

```toml
[[task]]
name = "test"                    # required, unique; merge key across layers
runner = "shell"                 # required: shell | claude | codex
command = "cargo test"           # required for runner = "shell"
paths = ["**/*.rs"]              # optional; omit = always runs
timeout = 300                    # optional, seconds; default 120
required = true                  # optional; default true. false = advisory
enabled = true                   # optional; default true

[[task]]
name = "security"
runner = "claude"
agent = "security-reviewer"      # optional; resolved to a persona file
prompt = "Review for auth bypass and injection."   # optional, inline
output_style = "verdict"         # optional; default "verdict"
model = "opus"                   # optional; runner default otherwise
effort = "high"                  # optional; reasoning effort, validated per runner

[[task]]
name = "scale-check"
runner = "codex"
prompt_file = "judges/scale.md"  # optional; mutually exclusive with prompt
paths = ["**/*.sql", "migrations/**"]
```

**Field rules:**

- `prompt` and `prompt_file` are mutually exclusive. Declaring both is a config
  error reported at load time, not a silent precedence rule.
- `agent` is optional. When present it resolves to a persona file, searched in
  the repo (`.arbiter/judges/`, then `judges/`), then `~/.config/arbiter/judges/`,
  then the built-in set.
- `output_style` is optional and defaults to `verdict`, a built-in style that
  constrains judges to terse, structured findings. It is resolved like a persona
  (`<repo>/.arbiter/output-styles/`, then `~/.config/arbiter/output-styles/`,
  then built in) and applies to `runner = "claude"` only; Codex has no
  equivalent concept and ignores it. An empty string disables it.
- Judge runners require at least one of `agent`, `prompt`, or `prompt_file`.
- `effort` is judge-only and validated against the runner's accepted set:
  `low|medium|high|xhigh|max` for Claude, which enumerates them in `--effort`,
  and `minimal|low|medium|high|xhigh` for Codex, which has no flag at all and
  takes `-c model_reasoning_effort` instead. Codex accepts any string there and
  defers rejection to the provider — verified, it echoed back both `xhigh` and
  `none` — so arbiter validates locally to turn a typo into a config error
  rather than a failure halfway through a judge. Setting it on a `shell` task is
  an error, not a silent no-op.
- `paths` are glob patterns matched against change-set paths relative to the
  repo root.
- `[arbiter] budget` must stay below the hook's 600s timeout; a larger value is
  a config error, since it would turn exhaustion back into a silent fail-open.

## Change set and caching

The change set is the diff against the merge-base with the repository's default
branch, plus untracked files from `git ls-files --others --exclude-standard`.
Merge-base rather than `HEAD` so that work already committed on the branch is
still gated, which matches a worktree-per-branch workflow.

The cache key is a content hash over the change set — file paths plus contents.
Content hashing rather than a file list alone means a judge that passed is
re-run when a file it reviewed is edited, but not when an unrelated file
changes.

Verdicts are stored under `.arbiter/state/<hash>.json`.

### Idle turns

A cache hit means the tree is byte-identical to when the verdict was rendered,
so the hash doubles as the "did this turn change anything" signal — no separate
dirty-tracking, and it is agnostic to how the change was made, which a
`PostToolUse` flag on edit tools would not be (a `sed -i` or a code generator
would slip past).

In hook mode both passing *and* failing verdicts are replayed from cache, so a
turn that produced no changes runs no gates at all: a blocked gate stays blocked
without spending a judge to re-derive the same answer. The block counter still
increments, so three idle turns still trip the loop guard.

Manual `arbiter run` replays passes but re-runs failures, because asking to run
is asking to re-run — that is the path for retrying a flaky gate. `--no-cache`
forces everything.

**Caveat:** a gate that writes a non-gitignored file into the repository
invalidates the cache with its own output and will re-run on every stop.
Gitignored artifacts are unaffected, since untracked files come from
`git ls-files --others --exclude-standard`. This was found the hard way: a test
gate instrumented to count its own executions wrote its counter into the repo
and never hit cache.

### Loop guard

A Stop hook that blocks is re-triggered when the agent finishes its next turn.
If arbiter blocks three consecutive times on an identical change-set hash, the
agent is not making progress; arbiter releases the turn with a `systemMessage`
warning rather than trapping the session. An invalid config is counted the same
way, keyed by its error.

`stop_hook_active` is present in the hook input but is not relied upon. Counting
consecutive blocks per content hash distinguishes "spinning" from "iterating",
which the boolean cannot.

## Judge isolation

Judges must read the repository and write scratch files — temp scripts, notes —
without being able to modify the code under review. Both runners enforce this at
the OS level, not by instruction.

Each run creates a scratch directory **outside the repository**, at
`~/.local/state/arbiter/scratch/<repo>-<slug>/<hash>/<task>/` (honoring
`XDG_STATE_HOME`).

This placement is forced, not stylistic. A judge's sandbox denies writes to the
repository root, and a nested `allowWrite` does **not** override that deny —
verified: with scratch at `<repo>/.arbiter/scratch/...`, the Claude judge's own
scratch write was refused with `operation not permitted`, leaving it unable to
write the temp files it is explicitly permitted. Moving scratch outside the repo
makes the deny and allow regions disjoint. It also keeps judge artifacts out of
the working tree entirely.

**Both runners execute with the scratch directory as their working directory**,
never the repository. Each agent CLI scaffolds its own bookkeeping beside its
cwd — Claude Code creates a `.claude/.cc-writes/` directory — and that must not
land in the tree under review. Judges are told both paths explicitly and reach
the repository through shell commands (`git -C <root> diff`).

The Claude runner deliberately passes no `--add-dir` for the repository. It is
unnecessary, because the sandbox restricts writes but not reads, so shell
commands reach the repo regardless; and it is harmful, because `--add-dir`
makes Claude Code scaffold `.claude/` inside the added directory. Verified: with
`--add-dir` the judged repo gained an empty `.claude/.cc-writes/`; without it
the repo is untouched and the bookkeeping stays in scratch.

### Known limitation

Codex's sandbox treats `/tmp` and `$TMPDIR` as writable regardless of workspace
configuration. A repository located under a temp directory is therefore **not**
protected from a Codex judge — verified: an identical probe escaped and modified
a fixture repo under `/private/tmp`, and was blocked once the same fixture lived
under `$HOME`. Checkouts normally live under `$HOME`, so this does not affect
normal use, but it invalidates any isolation test run against a fixture in
`/tmp`.

### Codex

```
codex exec --sandbox workspace-write --cd <scratch> \
           --skip-git-repo-check --ephemeral \
           --output-schema <verdict-schema.json> \
           -o <verdict.json>
```

The repository is read-only by virtue of being outside the workspace.
`--sandbox read-only` is deliberately not used: it also blocks scratch writes,
which defeats the temp-script requirement.

Verified: repo read succeeded, scratch write succeeded, temp script written and
executed, repo modification blocked with `operation not permitted`.

### Claude

```
claude -p --settings <generated.json> \
          --output-format json --no-session-persistence \
          --strict-mcp-config --disable-slash-commands \
          --permission-mode auto \
          --system-prompt <preamble + persona + output style> \
          [--model <model>] [--effort <effort>]
```

The generated settings file carries the sandbox policy:

```json
{
  "sandbox": {
    "enabled": true,
    "allowUnsandboxedCommands": false,
    "filesystem": { "denyWrite": ["<repo>"], "allowWrite": ["<scratch>"] }
  },
  "permissions": { "deny": ["Edit(//<repo>/**)"], "defaultMode": "auto" },
  "outputStyle": "default"
}
```

`allowUnsandboxedCommands: false` is strict mode: the model cannot retry a
blocked command unsandboxed.

Verified: repo read succeeded, scratch write succeeded, Bash append to the repo
blocked with `operation not permitted`, edit tool blocked by permission
settings, target file confirmed unmodified.

**Two syntax traps**, both encountered during verification:

- `Write(path)` deny rules are ignored by file permission checks. Only
  `Edit(path)` rules apply, and they cover all file-editing tools.
- Sandbox filesystem paths use plain absolute paths (`/tmp/x`). Read and Edit
  permission rules use a `//` prefix for absolute paths. The two syntaxes differ
  within the same settings file.

### Output style

The judge output style is inlined into the `--system-prompt`, not selected by
name through `outputStyle`. Claude Code resolves a style name from the user's
and project's `output-styles/` directories and from enabled plugins, where a
plugin's styles are namespaced (`arbiter:verdict`). Selecting it by name would
make every judge depend on the plugin being enabled in the judge's own session,
and the docs do not say whether a named style still applies once
`--system-prompt` replaces the default prompt. Inlining has neither dependency.

For the same reason the style file does not live in the plugin's root
`output-styles/`: there it would appear in every user's `/output-style` menu,
where selecting it for an interactive session would make Claude answer in bare
JSON. It lives under `config/output-styles/` instead, and the generated settings
pin `outputStyle` to `default` so a style the user chose for their own sessions
cannot reshape a judge.

## Recursion guard

Arbiter exports `ARBITER_CHILD=1` before spawning any judge subprocess. The hook
entry point exits immediately with `{}` when it sees that variable. This covers
both runners, which matters because the judge's own session loads the same
plugins, arbiter included, and Codex fires its own Stop hook too.

This is the primary guard. `--bare`, which would have provided a second layer
for the Claude runner, is unavailable under a subscription login.

## Execution and failure modes

Tasks run concurrently, each with its own timeout, defaulting to 120s.

The engine reserves headroom under the Stop hook's 600s ceiling. A hook timeout
renders no decision and the turn ends normally, so exceeding the ceiling is a
silent fail-open. Arbiter caps its own total wall clock at 540s by default and
reports exhaustion as an explicit failure.

| Condition | Hook output (exit 0 throughout) |
|---|---|
| All required tasks pass | `{}` |
| A required task fails | `decision: block`, findings as the reason |
| An advisory task fails | reported with a blocking failure, never blocks alone |
| A task times out | treated as a failure for that task |
| Engine budget exhausted | remaining tasks fail with an explicit budget message |
| Config invalid | `decision: block` with the parse error; never fails open silently |
| No user or repo config | `{}` |
| No enabled tasks, or no changes | `{}` |
| `ARBITER_CHILD` set | `{}` |
| Not a git repository | `{}` |
| Same block 3x in a row | `systemMessage` warning, turn ends |
| No Python 3.11+ or uv | `{}`, with a `systemMessage` if config exists |
| Internal error | `systemMessage` warning, turn ends |

## Plugin layout

```
plugins/arbiter/
├── .claude-plugin/plugin.json
├── hooks/hooks.json                  # Stop → bin/arbiter hook, timeout 600
├── bin/arbiter                       # launcher; on Claude's PATH via the plugin
├── lib/arbiter/                      # the implementation, stdlib only
│   ├── __init__.py  __main__.py  cli.py  commands.py
│   ├── constants.py  errors.py  patterns.py
│   ├── repository.py                 # Repository: git + change set
│   ├── config.py                     # Task, Config, ConfigLoader, data lookup
│   ├── state.py                      # State: cache, blocks, scratch
│   ├── verdicts.py                   # Verdict, Finding, extract_json
│   ├── prompts.py                    # shared judge instruction
│   ├── engine.py                     # Engine, Budget
│   ├── reporting.py                  # Reporter
│   └── runners/                      # registry, Runner ABC, shell, claude, codex
├── config/                           # the built-in layer: data, not code
│   ├── defaults.toml
│   ├── judges/                       # security-reviewer, scalability-reviewer
│   ├── output-styles/verdict.md
│   ├── schema/verdict.schema.json    # codex --output-schema
│   └── templates/typescript.toml
├── docs/design.md
└── tests/
```

`bin/arbiter` is a bash launcher that finds Python 3.11 or later (for
`tomllib`), falling back to `uv`, and runs the package in isolated mode (`-I`),
so neither `PYTHONPATH` nor the judged repository's files can shadow it. Nothing
it sets leaks into the gates it runs.

`Runner` is the only extension point. A new backend — another agent CLI, a local
model, a remote service — is a subclass plus a registry entry; the engine does
not change.

## CLI

```
arbiter init [template]  # scaffold arbiter.toml from a template
arbiter run              # run gates against the current change set
arbiter run --task NAME  # run one task
arbiter hook             # Stop-hook entry point; reads hook JSON on stdin
arbiter plan             # show what would run and why, without running it
arbiter status           # cached verdicts for the current change set
arbiter clean            # clear cache and scratch
```

Templates are scaffolding, deliberately not another config layer. A template
takes effect only once `init` copies it into a repository, so adding one can
never start running gates in projects that never asked for them. Templates come
from `~/.config/arbiter/templates/` and the built-in set; a user template
shadows a built-in one of the same name. `init` writes to the git root rather
than the current directory, because that is where config is resolved from, and
refuses to overwrite an existing `arbiter.toml` without `--force`.

`arbiter run` works standalone with no hook integration, which makes the engine
testable without triggering a stop event.

## Testing

### Automated

`plugins/arbiter/tests/` covers config merging across all four layers, schema
validation, glob gating, the content-hash cache, the loop guard, the recursion
guard, the no-config, non-git and no-change no-ops, the hook's JSON output and
exit codes, `init`, `clean`'s refusals, verdict parsing, and the exact commands
the Claude and Codex runners build — against stub `claude` and `codex`
executables, in fixture repositories under an isolated `HOME`.

### Verified by hand only

Judge isolation on both runners, and both judge runners end-to-end against a
deliberately vulnerable fixture, need the real CLIs and a login, so they are not
automated. They were verified by hand before the move into this plugin: repo
writes blocked at the OS level with `operation not permitted`, scratch writes
succeeded, target file unmodified by checksum, and each judge found a planted
SQL injection with file, line and severity.

## Out of scope

- Hosts other than Claude Code.
- Enforcing `turns`, which no available surface supports.
- Any git hook integration; arbiter gates turn end, not commits.
