# pr-tracker

Connects your coding agent to [pr-tracker](https://github.com/wmxscott/pr-tracker), which records the pull requests each session opens, keeps their checks and reviews fresh in the background, and tells the session when they change. When CI goes red on a PR the agent opened ten minutes ago, the agent hears about it on its next tool call.

The plugin is a thin layer: hooks that call the CLI (in Pi, an extension), a skill, and a `prs` command. The CLI does the work.

## Install

The plugin needs pr-tracker 1.1.0 or later and its background service:

```sh
brew install wmxscott/tap/pr-tracker
brew services start pr-tracker
```

See the [pr-tracker README](https://github.com/wmxscott/pr-tracker) for other ways to install it. Without the CLI the plugin does nothing: every hook exits quietly. Older versions record PRs, but the skills can't tell which session they're in.

### Claude Code

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install pr-tracker@ai-toolkit
```

### Codex

```sh
codex plugin marketplace add wmxscott/ai-toolkit
codex plugin add pr-tracker@ai-toolkit
```

Codex runs a plugin's hooks only once you trust them. Start Codex, choose to review the new hooks when it asks (or open `/hooks`), and trust the three pr-tracker hooks with `t`. Until then they don't run, and Codex asks again whenever an update changes them.

### Pi

The [ai-toolkit Pi package](../../README.md#pi) brings the skills and the [`pr-tracker.ts` extension](../../pi/README.md#pr-trackerts), which does in Pi what the hooks below do elsewhere:

```sh
pi install git:github.com/wmxscott/ai-toolkit
```

The package also loads the other plugins' skills and the other Pi extensions. To keep every extension but only this plugin's skills, give the package's entry in `~/.pi/agent/settings.json` a filter:

```json
{
  "source": "git:github.com/wmxscott/ai-toolkit",
  "skills": ["plugins/pr-tracker/skills/*"]
}
```

Keep the `pr-tracker.ts` extension if you filter extensions: the skills alone don't record anything.

A child Pi started by a subagent extension such as pi-subagents has its own session, so a PR it opens is tracked under the child's session, not yours, and its events go to the child. `pr-tracker adopt` attaches it to yours.

OpenCode isn't supported, so the ai-toolkit OpenCode plugin leaves these skills out.

## Hooks

| Hook | Runs | Does |
|---|---|---|
| `PostToolUse` on `Bash` | `pr-tracker hook post-bash` | Records a PR the command created with `gh pr create`, `gh stack submit` or `gh stack push`, then delivers queued check and review changes into the agent's context |
| `PostToolUse` on `mcp__.*github.*__create_pull_request` | `pr-tracker hook post-mcp` | Records the PR a GitHub MCP server created, then delivers queued changes |
| `Stop` | `pr-tracker hook stop` | Shows you changes that haven't reached the agent yet, leaving them queued. Never blocks the turn |

Claude Code and Codex load the same `hooks/hooks.json`. Codex sends the same payload, with `Bash` as the shell tool's name, and the CLI records its sessions as `codex`. The MCP matcher also catches Codex's GitHub connector, `mcp__codex_apps__github__create_pull_request`. Codex shows the `Stop` message in its TUI only, not in `codex exec`. A Codex subagent's hooks carry the parent's session id, so a PR it opens belongs to the parent session, and its events reach the parent, never the subagent. Recording is offline and takes a few milliseconds. The CLI's README documents the [hook contract](https://github.com/wmxscott/pr-tracker#the-hook-contract).

Each hook goes through `scripts/hook.sh`, which:

- looks for `pr-tracker` on your `PATH`, then in `/opt/homebrew/bin`, `/usr/local/bin`, `/home/linuxbrew/.linuxbrew/bin` and `~/.local/bin`, because an agent started from a GUI app can hand hooks a `PATH` without Homebrew on it;
- exits 0 with no output when it finds no `pr-tracker`;
- always exits 0 and drops the CLI's stderr, so a broken or outdated CLI can never block a turn or put errors in the session.

To pause the hooks without uninstalling, set `PR_TRACKER_DISABLE=1`.

## Skills

| Skill | |
|---|---|
| `pr-tracker` | The agent loads it when it needs this session's PRs, or a PR the hooks didn't see: one opened in the browser, by another tool or by an earlier session. It runs `pr-tracker adopt`, `list`, `status` and `refresh` |
| `prs` | Lists this session's PRs as a table, with checks, reviews and stacks. Add `open` or `all` to widen it to every session. You run it; the agent doesn't |

Run `prs` as `/prs` in Claude Code, `$pr-tracker:prs` in Codex and `/skill:prs` in Pi, for example `/skill:prs all`.

The skills pass no session id: the CLI reads it from the environment each agent gives its shell (`CLAUDE_CODE_SESSION_ID`, `CODEX_SESSION_ID`, `PI_SESSION_ID`).

The interactive fzf picker can't run inside the agent's shell, so `prs` ends with the command to open it for this session in a terminal: `prs --session <id>`.
