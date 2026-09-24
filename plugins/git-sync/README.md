# git-sync

Brings the current branch up to date with its upstream before the agent starts work, so it never edits or reviews code against a stale base.

The `fast-forward-sync` skill runs at the start of a task in a git repository. It fetches, compares the branch with its upstream, and fast-forwards only when the branch is strictly behind. It never merges, rebases, stashes or resets.

## Install

Claude Code:

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install git-sync@ai-toolkit
```

Codex:

```sh
codex plugin marketplace add wmxscott/ai-toolkit
codex plugin add git-sync@ai-toolkit
```

Needs `git`. Nothing else: the plugin is a single skill, with no hooks or scripts.

## What it does

| Branch state | Result |
|---|---|
| No upstream, or detached `HEAD` | Skipped |
| Up to date | Nothing to do |
| Behind only | `git merge --ff-only '@{u}'` |
| Ahead only | Nothing to pull |
| Diverged | Stops and asks you to choose between merge and rebase |

If uncommitted changes would be overwritten, `--ff-only` refuses and the agent reports it; your working tree is left as it was. If `git fetch` fails, for example offline, the agent says so and carries on.

It uses `git fetch` plus `git merge --ff-only` rather than `git pull`, whose result depends on your `pull.rebase` and `pull.ff` settings.

## Agent support

| Agent | Manifest |
|---|---|
| Claude Code | `.claude-plugin/plugin.json` |
| Codex | `plugin.json` ([Agent Plugins](https://agent-plugins.org) format) |

Both load the same `skills/` directory.
