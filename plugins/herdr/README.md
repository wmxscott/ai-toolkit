# herdr

Teaches coding agents to work the [Herdr](https://herdr.dev) way: every piece of work gets its own git worktree, opened as its own Herdr workspace, so agents never trip over each other's checkouts.

The `herdr-worktrees` skill has the agent start work with `wkt new`, rename a branch with `wkt rename` and set up a fresh clone with `wkt setup`, all from [herdr-wkt](https://github.com/wmxscott/herdr-wkt).

## Install

The skill needs:

- [Herdr](https://herdr.dev), to run the workspaces.
- [herdr-wkt](https://github.com/wmxscott/herdr-wkt), which provides `wkt`:

  ```sh
  brew install wmxscott/tap/herdr-wkt
  ```

Then the plugin. Claude Code:

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install herdr@ai-toolkit
```

Codex:

```sh
codex plugin marketplace add wmxscott/ai-toolkit
codex plugin add herdr@ai-toolkit
```

## What the agent does

| Task | Command |
|---|---|
| Start new work | `wkt new -b <branch> [-s <source>] [-n <label>]`: creates or reopens the branch's worktree and opens it as a Herdr workspace. A new branch starts from a freshly fetched default branch and doesn't track it |
| Rename the current branch | `wkt rename -b <new-branch> [-n <label>]`: renames the branch locally and on origin, moves the folder and updates the workspace. The agent asks before a rename that would close an open pull request |
| Set up a repository | `wkt setup <repo-url>` in an empty folder: clones into a `.bare` layout with a worktree for the default branch |

Worktrees of normal clones go under `~/.herdr/worktrees/<org>/<repo>/<branch>`, or `$HERDR_WKT_ROOT` if you set it. In a `.bare` layout they sit next to `.bare/`. `wkt` picks the path; the agent doesn't.

Without `wkt`, the agent suggests installing it, then creates the worktree with `git worktree add --no-track` in the same place and opens it with `herdr worktree open`. It won't rename a branch by hand.

## Agent support

| Agent | Manifest |
|---|---|
| Claude Code | `.claude-plugin/plugin.json` |
| Codex | `plugin.json` ([Agent Plugins](https://agent-plugins.org) format) |

Both load the same `skills/` directory.
