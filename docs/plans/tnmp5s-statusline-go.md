# Plan — Statusline as a Go binary with a shared git cache

| | |
|---|---|
| **Status** | in progress · next: A4 |
| **Updated** | 2026-10-28 |
| **Tracker** | — |
| **Related** | `plugins/statusline/`, [Claude Code statusline docs](https://code.claude.com/docs/en/statusline) |

## Goal

With dozens of Claude Code sessions open, the statusline plugin keeps about 2 CPU cores busy, starting about 260 processes a second at 24 sessions. Replace the Python script with a prebuilt Go binary that costs one process and about 10 ms per redraw. It runs git once per worktree per change or every 5 seconds, however many sessions share that worktree, and redraws every 15 seconds plus on Claude Code's own events. The three lines look the same as today. **Falsifiable sentence:** after this plan lands, a statusline redraw on a supported machine starts exactly one process and spends no more than 10 ms of wall time when the worktree's git cache is fresh.

### Done when

- [ ] `/statusline:setup` on a clean macOS machine writes the new command with `refreshInterval: 15`, downloads the binary, and the statusline appears in a real Claude Code session.
- [ ] `scripts/bench_statusline.py` at 24 sessions shows, for the new binary compared with today's `statusline.py`, fewer than 10% of the processes started per second and fewer than 10% of the CPU. Results are posted in the final PR.
- [ ] A GitHub release `statusline-v<version>` exists with four binaries whose SHA-256 sums match `plugins/statusline/checksums.txt` on `main`.
- [ ] An existing setup still running `python3 ".../statusline.py"` sees the "run /statusline:setup" notice at session start, and setup then replaces the old block without the conflict prompt.
- [ ] Go golden tests pass: byte-for-byte the same output as the Python script on the recorded inputs.
- [ ] Every check in `CLAUDE.md` "Checks", plus the new Go checks, passes in CI.

## Settled — do not re-derive

- **S1 (fact)** Today's cost per redraw is ~230 ms wall, ~85 ms CPU and ~11 processes: shell, a pyenv shim chain of ~6, Python, and 5 `git`. This was measured on an Apple Silicon Mac with `python3` as a pyenv shim. The pyenv shim alone costs ~150 ms. At `refreshInterval: 1` and 24 sessions that is ~2 cores. **Corrected by B1's benchmark (#21):** the process count was ~7× too low. pyenv's bash scripts fork a subshell for every `$(...)`, so the shim chain alone starts ~75 processes. Today's statusline at 24 sessions measured a median of 285 ms per redraw, 2.6 cores, and ~80 process starts per redraw (~1,900/s). Without the shim: 91 ms, 1.95 cores, ~6 per redraw.
- **S2 (fact)** The plugin never runs `ps`; the "ps flood" guess was wrong. Sampling every process for 10 s found none except the sampler. theme-sync runs `ps` only at session start.
- **S3 (fact)** Per redraw through `sh -c`, measured: floor (`/usr/bin/true`) 6.4 ms; Go 7.6 ms (~1 ms CPU); Rust 6.3 ms; Swift 7.8 ms; leanest direct Python 18.6 ms (~11 ms CPU). Each `git` call is 12–15 ms, nearly all process start-up.
- **S4 (decision)** Go, standard library only. Rejected:
  - Lean Python (~22 ms, ~12 ms CPU): the user chose Go knowing its edge is ~10× CPU but small in absolute terms (~0.15 vs ~0.01 core at 24 busy sessions).
  - Swift built locally: Mac only.
  - Rust: harder to cross-compile.
- **S5 (decision)** No background controller, daemon or socket. A per-worktree cache file shares the only shared data (git) with nothing to start or stop. Rejected: a socket controller (~7 ms via `nc -U`) needs lifecycle management for no remaining gain. Also, macOS caps Unix socket paths at 104 bytes.
- **S6 (decision)** Repo root, path inside the repo and branch come from reading `.git` directly, with no process. Rejected: one combined `rev-parse` call as the main path (3 processes become 1 instead of 0). It stays as the fallback: `git rev-parse --show-toplevel --show-prefix --abbrev-ref HEAD`.
- **S7 (decision)** Line counts keep real git: `git diff --shortstat HEAD` and `git ls-files -z --others --exclude-standard`, plus counting lines in untracked files ≤10 MB, with `GIT_OPTIONAL_LOCKS=0` and a timeout. Rejected: go-git and libgit2. There is no official Go git library; go-git has historically been slow at status on big repos, has no line-count API, and can disagree with git's ignore rules; `git2go` needs cgo, which breaks cross-builds. No benchmark needed (the user said so).
- **S8 (decision)** The line counts are cached per worktree and shared by all sessions. Refresh at once when the mtime of `HEAD` or `index` in the worktree's own git dir differs from the recorded value, else when the cache is ≥5 s old. Rejected: time limit only (branch switches lag); every redraw (no sharing).
- **S9 (fact)** Claude Code reruns the command on session start and resume, each new assistant message, `/compact`, permission-mode change, vim toggle, a `command` change, a `refreshInterval` tick, a rate-limit `resets_at`, and a warm prompt cache's `expires_at`. It debounces at 300 ms and **cancels an in-flight run** when a new update fires. `refreshInterval` is a fixed timer on top of events, minimum 1. Source: the Claude Code statusline docs.
- **S10 (decision)** `refreshInterval: 15`. The user wanted "events, plus a redraw if nothing for 15 s". There's no idle timer (S9), so a fixed 15 is the nearest fit.
- **S11 (decision)** Every cache write is atomic (write a temp file, then rename), because of S9's cancellation. A cancelled refresh leaves the old cache, and the next run retries.
- **S12 (decision)** Binaries come from GitHub release downloads for `darwin/arm64`, `darwin/amd64`, `linux/arm64` and `linux/amd64`, built reproducibly by CI. Rejected: committing binaries (~5 MB of history per Go change); building locally (most users lack `go`).
- **S13 (decision)** Blank until ready: with no binary (first install, offline, an unsupported platform), print nothing. Rejected: a Python fallback renderer (two implementations) and a shell fallback.
- **S14 (decision)** The SHA-256 of each binary is committed in `plugins/statusline/checksums.txt`. The hook verifies downloads against it, not against anything next to the release.
- **S15 (decision)** Existing setups are told to rerun setup, and only setup edits `settings.json`. The hook shows a notice; setup treats the old command as its own. Rejected: the hook rewriting `settings.json`; a README note only.
- **S16 (decision)** Versioning starts at `2.0.0`, in `.claude-plugin/plugin.json` only. Once set, CI fails when anything under `plugins/statusline/` differs from `main` without a version bump, and every bump publishes a release (even with byte-identical binaries).
- **S17 (decision)** Output parity: byte-for-byte for every input Claude Code really sends. *Amended during A1:* string inputs get only the common forms. ISO strings must be `YYYY-MM-DD{T| }HH:MM:SS[.f]` plus `Z`, `±HH:MM` or nothing, and numeric strings go through `strconv.ParseFloat`. A byte-level port of CPython's `fromisoformat` and `float()` was built and dropped as over-reach: it pushed A1 past the size cap for inputs Claude Code never sends. Go's tests list the forms Python accepts and Go rejects. Not emulated:
  - Python's exception text in the per-line error;
  - Python's acceptance of `NaN` and `Infinity` in JSON (Go treats them as invalid, i.e. `{}`).

  Matched:
  - a detached HEAD shows a 7-character short ID (or `core.abbrev` when the repo sets a fixed number);
  - the working directory is resolved through symlinks before walking up.
- **S18 (decision)** Out of scope:
  - Codex, Pi and OpenCode: none runs an outside command for its status line (research, 2026-10-28). Pi and OpenCode use in-process plugins; Codex has built-in items only.
  - GPU acceleration: the terminal draws the text.
  - Windows.
- **S19 (fact)** Claude Code copies a plugin from the repo at a commit. The data dir (`$CLAUDE_PLUGIN_DATA`, here `~/.claude/plugins/data/statusline-ai-toolkit`) survives updates; the install dir doesn't. So the old binary in the data dir keeps working until a new one lands.
- **S20 (decision)** `setup_statusline.py` stays Python: it runs once, not per redraw.
- **S21 (decision)** The benchmark lives outside the plugin, at `scripts/bench_statusline.py`, so S16's version rule never applies to it and its stack stays independent.

## The Go program

### Layout and build contract

- A Go module in `plugins/statusline/` (`go.mod` with `toolchain` pinned to the version used to produce `checksums.txt`; module path `github.com/wmxscott/ai-toolkit/plugins/statusline`). Package layout is the builder's call.
- Reproducible build: `CGO_ENABLED=0 go build -trimpath -buildvcs=false -ldflags "-s -w -buildid="` for each `GOOS/GOARCH` in S12. Binary names: `statusline-<os>-<arch>`.
- Standard library only. No work at package init.

### Input and rendering

- Reads all of stdin. Invalid JSON, or JSON that isn't an object, becomes `{}`.
- Ports `scripts/statusline.py` in full:
  - the dark (Catppuccin Macchiato) and light (Latte) palettes, the icons, the effort and vim badges, and model-name shortening;
  - `number()` semantics: numbers or numeric strings, booleans rejected;
  - `fmt_resets`: epoch seconds, epoch milliseconds (≥1e10) or ISO 8601;
  - token, cost and duration formats, and the 60%/85% thresholds;
  - each line rendered separately, with a failing line replaced by `statusline error: <err>` in the critical colour;
  - empty lines dropped, with a trailing newline.
- `now` is injectable, for tests.

### Theme

The first source that gives an answer wins:
1. `CLAUDE_STATUSLINE_THEME` set to `dark` or `light`.
2. `~/.local/share/theme-monitor/theme-change.trigger`.
3. On macOS, `defaults read -g AppleInterfaceStyle` (exit 0 with `Dark` means dark, otherwise light). Cache that answer for 5 s in the cache directory.
4. Otherwise dark.

### Reading `.git`

1. Resolve the working directory (`workspace.current_dir`, else `cwd`, else the process cwd) through symlinks.
2. If `GIT_DIR` or `GIT_WORK_TREE` is set, use the S6 fallback.
3. Walk up to the first directory containing `.git`. If `.git` is a directory, that's the git dir. If it's a file, read `gitdir: <path>` (relative paths are resolved against the file's directory). Anything else malformed or unreadable uses the S6 fallback. No `.git` up to `/`: not a repo, and line 1 shows the path with `~` as today.
4. Branch: `<gitdir>/HEAD` is either `ref: refs/heads/<name>` (that's the branch) or a full SHA. For a SHA, abbreviate to 7 characters, or `core.abbrev` if `<gitdir>/config` or `commondir`'s config sets a fixed number.
5. Repo name: the basename of the root. Prefix: the path from the root to the working directory, with no trailing slash.

### Git line-count cache

- Directory: `os.UserCacheDir()/ai-toolkit-statusline/`. One file per worktree root, named by a hash of the root path. It holds `added`, `deleted`, `written_at`, `head_mtime` and `index_mtime` (format: the builder's call).
- Fresh: the file exists, both recorded mtimes equal the current ones, and it's <5 s old. A fresh cache is used as is.
- Stale or missing: try an exclusive lock (`flock`, or an `O_EXCL` lock file with a 10 s stale timeout). With the lock, run the S7 commands, write the result atomically (S11), then release. Without the lock, use the stale cache, or zero counts if there is none.
- Any failure (unwritable cache dir, a git timeout) is silent: render with whatever is available.

## Release and download

### Checksums and CI

- `scripts/build_statusline.sh` (repo root; bash 3.2-safe) builds all four binaries into a temp dir and rewrites `plugins/statusline/checksums.txt` (lines of `<sha256>  statusline-<os>-<arch>`). `--check` rebuilds and fails on any difference.
- A CI job (ubuntu, `actions/setup-go` from `go.mod`) runs `gofmt -l` (must be empty), `go vet ./...`, `go test ./...` and `scripts/build_statusline.sh --check`.
- Version check: when `plugin.json` on the PR's base has a `version`, fail if anything under `plugins/statusline/` changed but `version` didn't.
- Release workflow: on a push to `main`, if `plugin.json`'s version has no `statusline-v<version>` tag, build, `--check`, then create the tag and a release with the four binaries (`contents: write`).

### Hook: `scripts/link_statusline.sh`

Fail-safe; exits 0 every time and fast. On every SessionStart:

1. **Upgrade notice (S15).** Find `settings.json` (`$CLAUDE_CONFIG_DIR` or `~/.claude`, through a symlink). If its text contains `statusline-ai-toolkit/statusline.py`, print the JSON `{"systemMessage": "statusline: run /statusline:setup to switch to the faster version"}`. Don't edit anything.
2. Read the version from `$CLAUDE_PLUGIN_ROOT/.claude-plugin/plugin.json` (no `jq`). No version: exit 0.
3. Map `uname -s` and `uname -m` to `darwin|linux` and `arm64|amd64` (`aarch64` → `arm64`, `x86_64` → `amd64`). Anything else: exit 0.
4. If `$CLAUDE_PLUGIN_DATA/bin/statusline-<version>-<os>-<arch>` exists, swap the link `$CLAUDE_PLUGIN_DATA/statusline` to point at it (temp link, then `mv`, as today) and exit.
5. Otherwise run the download, detached in the background (`--foreground` runs it inline for setup):
   - take a lock (`mkdir` lock dir with a stale timeout);
   - `curl -fsSL --max-time 30 https://github.com/wmxscott/ai-toolkit/releases/download/statusline-v<version>/statusline-<os>-<arch>` into a temp file;
   - verify it against `checksums.txt` (`shasum -a 256` or `sha256sum`), and on a mismatch delete it;
   - `chmod +x`, rename into `bin/`, swap the link, and delete other versions' binaries in `bin/`.
   - Child stdout and stderr go to `/dev/null`.

### Setup: `scripts/setup_statusline.py`

- `desired` becomes:
  - `command`: `"$HOME/.claude/plugins/data/statusline-ai-toolkit/statusline"`, quoted and `$HOME`-relative, as `shell_command` does today, minus `python3`;
  - `padding: 0`;
  - `refreshInterval: 15`;
  - plus the existing extra keys.
- Setup runs the hook with `--foreground` before writing. If the binary still isn't there, it writes the settings anyway and says the statusline appears once the download completes.
- A current block whose `command` matches the old plugin command (`python3 "…/statusline-ai-toolkit/statusline.py"`) counts as setup's own: it's replaced without exit 3. Then the old `statusline.py` link is removed.

## Benchmark: `scripts/bench_statusline.py`

- Python standard library only, passing ruff. Arguments: a statusline command, `--sessions` (24), `--worktrees` (4, scratch repos it creates with a few tracked and untracked changes), `--seconds` (30) and `--interval` (1.0).
- Each simulated session pipes realistic session JSON into `sh -c <command>` on its interval, in its own thread.
- Reports:
  - redraw wall time (median and p95);
  - total child CPU from `resource.getrusage(RUSAGE_CHILDREN)` before and after;
  - processes started per second machine-wide, measured without root (e.g. by spawning a throwaway process before and after to read the PID counter's advance, minus an idle baseline taken first; the method is the builder's call), labelled as approximate.
- A pytest test runs it for 2 s with 2 sessions against a stub command and checks the report's shape.

## Stacks and phases

Two stacks. B (benchmark) touches only `scripts/bench_statusline.py` and its test, which nothing in A reads, so they can be implemented **concurrently**.

### Stack A — Go statusline

- **Base:** `main`
- **Owns:** `plugins/statusline/**`, `scripts/build_statusline.sh`, `scripts/check_plugin_versions.sh`,
  `.github/workflows/**`, `CLAUDE.md`, `tests/test_build_statusline.py`, `tests/test_check_plugin_versions.py`,
  `docs/plans/tnmp5s-statusline-go.md`
- **Independent of:** B
- **Depends on:** —

| Phase | Lands | Depends on |
|---|---|---|
| A1 | Go module, palettes and formatting helpers, golden fixtures recorded from Python (lands as two PRs at its split seam: goldens, then Go) | — |
| A2 | Rendering of lines 2–3 and non-repo line 1, stdin parsing, theme, `main` | A1 |
| A3 | `.git` reading, line-count cache, line 1 with git | A2 |
| A4 | Reproducible build script, `checksums.txt`, Go CI job, version check, release workflow | A3 |
| A5 | Hook download and upgrade notice, setup changes, `version: 2.0.0` | A4 |
| A6 | Remove `statusline.py` and its tests, README and `CLAUDE.md` docs, `version: 2.0.1` | A5 |

- [ ] A1 — Go module and helpers
- [ ] A2 — Rendering and theme
- [ ] A3 — Git reading and cache
- [ ] A4 — Build, checksums and CI
- [ ] A5 — Download hook and setup
- [ ] A6 — Retire Python and docs

**A1 — Go module and helpers**
`go.mod` and a package with the palettes, icons and constants, and the helpers `number`, `fmtTokens`, `fmtCost`, `fmtDuration`, `fmtResets`, `pctColor` and `progressCircle`, with table tests ported from `tests/test_statusline.py`. Also a generator (under `plugins/statusline/tests/`, Python) that runs today's `statusline.py` on a set of recorded inputs (no git, fixed `now`, both themes) and writes golden files to `plugins/statusline/testdata/golden/`. Cites S4, S17, Input and rendering, Layout and build contract.
*Shippable when:* `go vet` and `go test` pass locally, the existing pytest suite still passes, and the golden files are committed.
*Split seam:* the golden generator and fixtures on their own first.

**A2 — Rendering and theme**
`line1` (vim badge plus the non-repo path only; the git part is stubbed to "not a repo"), `line2`, `line3`, `render`, stdin parsing, theme detection with the cached `defaults` answer, and `main`. The golden tests compare byte for byte. Cites S17, Input and rendering, Theme.
*Shippable when:* the golden tests for all non-git inputs pass, and `echo '<json>' | go run .` prints the same as the Python script.
*Split seam:* theme detection (with its cache) as its own PR after the rendering.

**A3 — Git reading and cache**
`.git` reading with the `rev-parse` fallback, the line-count cache with lock and atomic writes, and line 1 with git. Go tests cover:
- a normal repo, a linked worktree, a submodule, a detached HEAD, a repo with no commits, `GIT_DIR` set, and a symlinked working directory;
- the cache: reused when fresh, refreshed on a `HEAD`/`index` mtime change and at 5 s, the lock held (stale counts served), and a write cancelled mid-way leaving the old file.

Golden line-1 cases are recorded from Python against scratch repos and compared. Cites S6, S7, S8, S11, S17, Reading `.git`, Git line-count cache.
*Shippable when:* the tests pass, and in a repo the binary starts no `git` process when the cache is fresh (checked by a test with a `git` shim on `PATH` that logs calls).
*Split seam:* `.git` reading in one PR, the cache in the next.

**A4 — Build, checksums and CI**
`scripts/build_statusline.sh` with `--check`, `plugins/statusline/checksums.txt`, the Go CI job, the version check and the release workflow. `CLAUDE.md` "Checks" gains the Go commands and the build check. Cites S12, S14, S16, Checksums and CI.
*Shippable when:* CI passes on the PR, including `--check` on Linux, which proves the macOS-built checksums are reproducible there. The release workflow does nothing yet, because `plugin.json` has no version.
*Split seam:* the release workflow and version check after the build script and CI job.

**A5 — Download hook and setup**
The hook changes, the setup changes, the updated `tests/test_link.py`, `tests/test_setup.py` and `tests/test_plugin.py` (`curl`, `uname` and the SHA tools stubbed on `PATH`, no real `$HOME`), and `version: "2.0.0"` in `plugin.json`. Merging cuts the first release. Cites S10, S13, S14, S15, S19, S20, Hook, Setup.
*Shippable when:*
- the tests pass;
- after merge, the release `statusline-v2.0.0` exists with binaries matching `checksums.txt`;
- `/statusline:setup` in a real session shows the Go statusline.

*Split seam:* the setup changes as a separate PR after the hook (the version bump goes with the later of the two).

**A6 — Retire Python and docs**
Delete `scripts/statusline.py`, `tests/test_statusline.py`, `tests/test_git_info.py`, `tests/test_theme.py`, and any conftest fixtures only they used. Rewrite the plugin README:
- requirements: `curl` and a SHA-256 tool, no `python3` at run time;
- how the binary arrives, and blank until the first download;
- the new setup block and refresh behaviour;
- the cache directory, and "Upgrading from 1.x".

Add a `CLAUDE.md` note in "Adding a plugin" on versioned plugins and the bump rule. Bump to `2.0.1`. Run the benchmark against `git show main~N:plugins/statusline/scripts/statusline.py` and the new binary, and post the results (with no machine identifiers) in the PR description. Cites S16, S21.
*Shippable when:* CI passes, the `2.0.1` release exists, and the benchmark results meet the Done-when threshold.
*Split seam:* the docs as their own PR, after the deletions.

### Stack B — Benchmark

- **Base:** `main`
- **Owns:** `scripts/bench_statusline.py`, `tests/test_bench_statusline.py`
- **Independent of:** A
- **Depends on:** —

| Phase | Lands | Depends on |
|---|---|---|
| B1 | Benchmark script and its smoke test | — |

- [ ] B1 — Benchmark

**B1 — Benchmark**
As in "Benchmark: `scripts/bench_statusline.py`". Cites S1, S3, S21.
*Shippable when:* ruff and pytest pass, and a run against today's statusline at 24 sessions reproduces S1's order of magnitude (hundreds of processes a second, about 2 cores of CPU). Paste that output in the PR.
*Split seam:* none expected; if needed, scratch-repo creation as its own PR.

## Forest from the trees

### Challenge

The advisor tool is unavailable in this session, so here is my own case against the sequence.

- **Strongest case it's wrong:** A1–A4 land roughly 1,000 lines of Go and CI that no user runs until A5. If parity breaks on real input, nobody notices until the switch. Answer: the golden tests are recorded from the real Python script, so parity is checked from A1 on, and A2's shippable check runs the binary on real JSON. Kept.
- **Second case:** making A6 bump to `2.0.1` only to delete files looks like ceremony. The alternative, deleting Python inside A5, pushes A5 well past the size cap (`statusline.py` alone is ~400 lines of deletions, all production). Kept, because S16 says an installed-file change must bump anyway.
- **Third case:** B could be done after A, so the measurement compares the finished pair. It's cheaper first: it confirms S1 independently before ~1,000 lines are built on it. Concurrent with A, and nothing changed.
- **Gap this surfaced:** between A5 and A6, the README still describes the Python version. Accepted for one PR's lifetime, so A6 should follow A5 promptly.

### Drift test

1. If every remaining phase were cancelled after this PR, does `main` still give every user a working statusline, and is something from the Goal (fewer processes, shared git, or parity proof) more true than before?
2. Does this PR add anything a redraw does on every run, rather than only when the cache is stale? If so, which Settled entry allows it?

## Not doing

- Other agents (Codex, Pi, OpenCode): deferred to a later project (S18).
- A background controller or socket: rejected (S5).
- go-git or libgit2: rejected (S7).
- A Python or shell fallback renderer: rejected (S13).
- The hook editing `settings.json`: rejected (S15).
- Windows: out of scope.

## Log

- 2026-10-28 — phase B1 landed as #21
- 2026-10-28 — plan amended: S1 corrected from B1's measurements; S17 narrowed to common string forms; A1 split at its named seam into two PRs (goldens, then Go module) to fit the size cap
- 2026-10-28 — phase A1 landed as #22 (goldens) and #23 (Go module)
- 2026-10-28 — phase A2 landed as #24
- 2026-10-28 — phase A3 landed as #25
- 2026-10-28 — plan amended: build adds `-buildvcs=false` (go build stamps the commit by default, so checksums never matched across commits); stack A owns the version-check script and the two repo-level tests A4 added
