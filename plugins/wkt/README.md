# wkt

Teaches coding agents to give every piece of work its own git worktree, through [wkt](https://github.com/wmxscott/wkt), so parallel work never trips over one checkout. The agent opens a worktree as a tmux session or [Herdr](https://herdr.dev) workspace only when you ask.

The `worktrees` skill has the agent start work with `wkt new`, rename a branch with `wkt rename`, remove its finished worktrees with `wkt rm`, set up a fresh clone with `wkt setup` and, when you ask, convert an existing clone with `wkt adopt`.

## Install

The skill needs [wkt](https://github.com/wmxscott/wkt) 2.0 or later:

```sh
brew install wmxscott/tap/wkt
```

Then the plugin. Claude Code:

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install wkt@ai-toolkit
```

Codex:

```sh
codex plugin marketplace add wmxscott/ai-toolkit
codex plugin add wkt@ai-toolkit
```

## What the agent does

`wkt new` opens nothing unless given `--tmux` or `--herdr`. The agent runs plain `wkt new -b <branch>`, including for worktrees it works in itself, and adds `--tmux` or `--herdr` only when you ask for the work opened that way. Inside tmux, `--tmux` switches your screen to the new session, so the agent never passes it unasked.

| Task | Command |
|---|---|
| Start new work | `wkt new -b <branch> [-s <source>] [-n <name>] [--tmux \| --herdr]`: creates or reopens the branch's worktree and prints its path, opening it as a tmux session or Herdr workspace when you ask. A new branch starts from a freshly fetched default branch and doesn't track it |
| Rename the current branch | `wkt rename -b <new-branch> [-n <name>]`: renames the branch locally and on origin, moves the folder, and updates the worktree's tmux session and Herdr workspace if it has them. The agent asks before a rename that would close an open pull request |
| Remove a finished worktree | `wkt rm -b <branch>`: removes the worktree, closes its tmux session and Herdr workspace, and deletes the local branch only when nothing on it would be lost. The agent uses it on its own merged work, never adds `-f` unless you ask, and reports a refusal instead of forcing it |
| Clean up merged worktrees | `wkt rm --merged`: removes every merged worktree in the repository. Only when you ask, and only after you've seen what it would remove |
| Set up a repository | `wkt setup <repo-url>` in an empty folder: clones into a `.bare` layout with a worktree for the default branch |
| Convert a clone | `wkt adopt` at the top of a clone: turns it into a `.bare` layout in place. Only when you ask, since every path changes |

Worktrees of normal clones go under `~/.herdr/worktrees/<org>/<repo>/<branch>`, or `$WKT_ROOT` if you set it. In a `.bare` layout they sit next to `.bare/`. `wkt` picks the path; the agent doesn't.

Without `wkt`, the agent suggests installing it, then creates the worktree with `git worktree add --no-track` in the same place and, only when you ask for a Herdr workspace, opens it with `herdr worktree open`. It removes a merged worktree with `git worktree remove` and leaves the branch to you. It won't rename a branch by hand.

## Agent support

| Agent | Manifest |
|---|---|
| Claude Code | `.claude-plugin/plugin.json` |
| Codex | `plugin.json` ([Agent Plugins](https://agent-plugins.org) format) |

Both load the same `skills/` directory.
