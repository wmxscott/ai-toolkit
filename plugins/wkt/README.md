# wkt

Teaches coding agents to give every piece of work its own git worktree, through [wkt](https://github.com/wmxscott/wkt), so parallel work never trips over one checkout. Inside [Herdr](https://herdr.dev), the agent opens a worktree as its own Herdr workspace only when a separate workspace is wanted.

The `worktrees` skill has the agent start work with `wkt new`, rename a branch with `wkt rename`, set up a fresh clone with `wkt setup` and, when you ask, convert an existing clone with `wkt adopt`.

## Install

The skill needs [wkt](https://github.com/wmxscott/wkt):

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

Inside Herdr, `wkt new` and `wkt rename` open or update a Herdr workspace unless given `--no-herdr`. The agent passes `--no-herdr` by default, including for worktrees it works in itself, and leaves it off only when you ask for a workspace or the work is meant to carry on in one.

| Task | Command |
|---|---|
| Start new work | `wkt new -b <branch> [-s <source>] [-n <label>] [--no-herdr]`: creates or reopens the branch's worktree, and opens it as a Herdr workspace when that's wanted. A new branch starts from a freshly fetched default branch and doesn't track it |
| Rename the current branch | `wkt rename -b <new-branch> [-n <label>] [--no-herdr]`: renames the branch locally and on origin, moves the folder and, if the worktree has one, updates its workspace. The agent asks before a rename that would close an open pull request |
| Set up a repository | `wkt setup <repo-url>` in an empty folder: clones into a `.bare` layout with a worktree for the default branch |
| Convert a clone | `wkt adopt` at the top of a clone: turns it into a `.bare` layout in place. Only when you ask, since every path changes |

Worktrees of normal clones go under `~/.herdr/worktrees/<org>/<repo>/<branch>`, or `$WKT_ROOT` if you set it. In a `.bare` layout they sit next to `.bare/`. `wkt` picks the path; the agent doesn't.

Without `wkt`, the agent suggests installing it, then creates the worktree with `git worktree add --no-track` in the same place and, only when a workspace is wanted, opens it with `herdr worktree open`. It won't rename a branch by hand.

## Agent support

| Agent | Manifest |
|---|---|
| Claude Code | `.claude-plugin/plugin.json` |
| Codex | `plugin.json` ([Agent Plugins](https://agent-plugins.org) format) |

Both load the same `skills/` directory.
