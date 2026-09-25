---
name: pr-tracker
description: Use when a pull request this session opened needs to be found, listed, or attached to the session — including when a PR was created by a path the hooks do not see (a web UI, a different tool, an earlier session), or when the user asks what PRs are open, how their checks look, or which of them are stacked.
allowed-tools: Bash(pr-tracker list *) Bash(pr-tracker status)
---

# pr-tracker

The plugin's hooks record every PR this session opens with `gh pr create`, `gh stack submit`, `gh stack push` or a GitHub MCP `create_pull_request` tool. A background service refreshes their checks and reviews, and any change arrives in your context on your next tool call. None of that needs you.

This skill covers what the hooks can't see, and reading the current state.

This session's id is `${CLAUDE_SESSION_ID}`. Pass it with `--session` as shown: your shell doesn't have it in the environment the CLI reads.

If `pr-tracker` isn't on `PATH`, tell the user the plugin needs the pr-tracker CLI (`brew install wmxscott/tap/pr-tracker && brew services start pr-tracker`) and stop.

## Adopt a PR the hooks missed

A PR opened in the GitHub web UI, by another tool, or by an earlier session isn't attached to this one. Attach it:

```bash
pr-tracker adopt <url|number> --session "${CLAUDE_SESSION_ID}"
```

With no URL or number it adopts the current branch's PR. A number or branch resolves through `gh` in the current directory, so run it inside the repository, or add `--cwd <repo>`.

## Read the current state

```bash
pr-tracker list --scope session --session "${CLAUDE_SESSION_ID}"
```

This session's PRs as JSON, stacked PRs after their base. `--scope open` lists every open PR across sessions, `--scope all` merged and closed ones too. The fields that matter:

| Field | |
|---|---|
| `number`, `title`, `url`, `repo` | The PR |
| `state`, `is_draft` | `open`, `merged` or `closed` |
| `checks_rollup`, `checks_pass`, `checks_fail`, `checks_pending`, `checks_skip` | CI verdict (`SUCCESS`, `FAILURE`, `PENDING` or `NONE`) and counts |
| `review_state` | Review verdict: `approved`, `changes_requested`, `review_required` or `none` |
| `depth` | 0 for a lone PR or the bottom of a stack, 1 for the PR on top of it, and so on |
| `orphan` | `true` when the PR's base branch is gone |
| `last_refreshed_at` | Unix time of the last good refresh |

Skip `body` unless the user asks about a PR's description.

```bash
pr-tracker status
```

Shows the ledger, the last refresh, and any repository whose refreshes are failing.

Prefer these to `gh pr list` when the question is what *this session* opened: only pr-tracker knows which session opened which PR.

## Refresh now

Refreshes run every five minutes. To refresh straight away, which calls GitHub:

```bash
pr-tracker refresh --force
```

It prints nothing outside a terminal. Run `list` afterwards to see the result.

## Stop tracking a PR

```bash
pr-tracker untrack <url|owner/repo#number> --session "${CLAUDE_SESSION_ID}"
```

## Don't

- Poll in a loop. Changes to checks and reviews arrive on their own.
- Write to the ledger's database directly. Use `adopt` and `untrack`.
- Treat an old `last_refreshed_at` as an error in the PR. It means refreshes are failing, usually because `gh` isn't logged in or the network is down, and the values are the last known good ones. `pr-tracker status` says which.
