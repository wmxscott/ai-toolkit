---
name: prs
description: List the pull requests tracked for this session, with their checks and reviews
disable-model-invocation: true
argument-hint: "[open|all]"
allowed-tools: Bash(pr-tracker list *)
---

Show the user the pull requests pr-tracker has for this session. Arguments: `$ARGUMENTS`

Run:

```bash
pr-tracker list --scope session --session "${CLAUDE_SESSION_ID}"
```

If the arguments are `open` or `all`, run `pr-tracker list --scope open` or `pr-tracker list --scope all` instead, and say the list covers every session.

If this session has no PRs, say so, then run `pr-tracker list --scope open` and show those as every session's open PRs.

The output is JSON with the PRs under `prs`, each stack in order. Render a compact table: number linked to its `url`, title, state (say draft when `is_draft` is set), checks (`checks_rollup` with the pass, fail and pending counts), and `review_state`. Indent each PR by its `depth`, so stacked PRs sit under their base, and flag any PR whose `orphan` is `true` as having lost its base branch. Don't show `body`.

Don't call `gh` for this: only pr-tracker knows which PRs belong to this session.

If `pr-tracker` isn't installed, say the plugin needs the pr-tracker CLI:

```sh
brew install wmxscott/tap/pr-tracker
brew services start pr-tracker
```

Finish with one line: for the interactive picker, run `prs --session ${CLAUDE_SESSION_ID}` in a terminal.
