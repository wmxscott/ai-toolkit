# pr-tracker

Connects Claude Code to [pr-tracker](https://github.com/wmxscott/pr-tracker), which records the pull requests each session opens, keeps their checks and reviews fresh in the background, and tells the session when they change. When CI goes red on a PR Claude opened ten minutes ago, Claude hears about it on its next tool call.

The plugin is a thin layer: hooks that call the CLI, a skill, and a `/prs` command. The CLI does the work.

## Install

The plugin needs the pr-tracker CLI and its background service:

```sh
brew install wmxscott/tap/pr-tracker
brew services start pr-tracker
```

See the [pr-tracker README](https://github.com/wmxscott/pr-tracker) for other ways to install it. Then the plugin:

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install pr-tracker@ai-toolkit
```

Without the CLI the plugin does nothing: every hook exits quietly.

## Hooks

| Hook | Runs | Does |
|---|---|---|
| `PostToolUse` on `Bash` | `pr-tracker hook post-bash` | Records a PR the command created with `gh pr create`, `gh stack submit` or `gh stack push`, then delivers queued check and review changes into Claude's context |
| `PostToolUse` on `mcp__.*github.*__create_pull_request` | `pr-tracker hook post-mcp` | Records the PR a GitHub MCP server created, then delivers queued changes |
| `Stop` | `pr-tracker hook stop` | Shows you changes that haven't reached Claude yet, leaving them queued. Never blocks the turn |

Recording is offline and takes a few milliseconds. The CLI's README documents the [hook contract](https://github.com/wmxscott/pr-tracker#the-hook-contract).

Each hook goes through `scripts/hook.sh`, which:

- looks for `pr-tracker` on your `PATH`, then in `/opt/homebrew/bin`, `/usr/local/bin`, `/home/linuxbrew/.linuxbrew/bin` and `~/.local/bin`, because Claude Code started from a GUI app can hand hooks a `PATH` without Homebrew on it;
- exits 0 with no output when it finds no `pr-tracker`;
- always exits 0 and drops the CLI's stderr, so a broken or outdated CLI can never block a turn or put errors in the session.

To pause the hooks without uninstalling, set `PR_TRACKER_DISABLE=1`.

## Skills

| Skill | |
|---|---|
| `pr-tracker` | Claude loads it when it needs this session's PRs, or a PR the hooks didn't see: one opened in the browser, by another tool or by an earlier session. It runs `pr-tracker adopt`, `list`, `status` and `refresh` |
| `/prs` | Lists this session's PRs as a table, with checks, reviews and stacks. `/prs open` or `/prs all` widens it to every session. You run it; Claude doesn't |

The interactive fzf picker can't run inside Claude's shell, so `/prs` ends with the command to open it for this session in a terminal: `prs --session <id>`.

## Agent support

Claude Code only. Other agents can call the CLI's hook commands themselves: see the pr-tracker README.
