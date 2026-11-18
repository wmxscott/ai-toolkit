# switchboard

Connects Claude Code and Codex to [switchboard](https://github.com/wmxscott/switchboard), a tmux session switcher that shows which agents are working, which are done and which need you. The plugin's hooks tell the CLI when an agent's state changes, and the CLI keeps that state in tmux for the switcher and the status bar.

The plugin is only the hooks. The CLI does the work.

## Install

The plugin needs tmux and the switchboard CLI. Codex needs switchboard 1.1.0 or later; older versions ignore its hooks.

```sh
brew install wmxscott/tap/switchboard
```

Outside tmux, or without `switchboard` on your `PATH`, the plugin does nothing: every hook exits at once, without starting the CLI.

The tmux side is set up separately: the key binding that opens the switcher, the `client-session-changed` hook that marks finished agents seen, and the status-bar segment. The [switchboard README](https://github.com/wmxscott/switchboard) has the lines to add to your tmux config.

### Claude Code

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install switchboard@ai-toolkit
```

### Codex

```sh
codex plugin marketplace add wmxscott/ai-toolkit
codex plugin add switchboard@ai-toolkit
```

Codex runs a plugin's hooks only once you trust them. Start Codex, choose to review the new hooks when it asks (or open `/hooks`), and trust the switchboard hooks with `t`. Until then they don't run, and Codex asks again whenever an update changes them.

switchboard tracks only Codex sessions started with `codex --no-daemon`. By default Codex runs its sessions in a shared background daemon, whose hooks see the tmux pane of whichever terminal started the daemon, not the one the session is in. switchboard can't place such a session, so it ignores it rather than show it in the wrong pane.

Codex started from inside a Claude Code session isn't tracked either: it inherits Claude's pane.

## Hooks

Claude Code reads `hooks/hooks.json`:

| Hook | Matches | Tells switchboard |
|---|---|---|
| `SessionStart` | every source | A session started, so it shows as idle before its first prompt |
| `UserPromptSubmit` | | A turn started |
| `PreToolUse` | `AskUserQuestion`, `ExitPlanMode` | An agent is waiting for your answer |
| `PermissionRequest` | every tool | An agent is waiting for your permission |
| `Notification` | `permission_prompt`, `elicitation_dialog`, `elicitation_url_dialog` | An agent is waiting for you |
| `Notification` | `idle_prompt` | The session is idle |
| `PostToolUse`, `PostToolUseFailure` | every tool | The agent is working again |
| `Stop`, `StopFailure`, `TeammateIdle` | | The turn ended |
| `SubagentStop` | every agent | A subagent finished |
| `SessionEnd` | every reason | The session ended, or was cleared or switched with `/clear` or `/resume` |

Codex reads `hooks/codex.json`, which its manifest names in place of `hooks/hooks.json`, with only the events Codex has:

| Hook | Matches | Tells switchboard |
|---|---|---|
| `SessionStart` | every source | A session started |
| `UserPromptSubmit` | | A turn started, or a subagent got its task |
| `PreToolUse` | `request_user_input` | The agent is waiting for your answer |
| `PermissionRequest` | every tool | The agent is waiting for your permission |
| `PostToolUse` | every tool | The agent is working again |
| `Stop` | | The turn ended |
| `SubagentStop` | every agent | A subagent finished |
| `Interrupt` | | You interrupted the turn |
| `SessionEnd` | | The session ended |

Codex has no hook for a failed turn, so one shows as working until your next prompt, and none for an MCP server asking you something, so that never shows as waiting. Its `PermissionRequest` fires before Codex's auto-reviewer decides, so a call it approves can show as waiting for a moment.

Each hook runs `scripts/hook.sh <event>`, or `scripts/hook.sh <event> codex` from Codex. The script exits 0 at once when `$TMUX_PANE` is unset, `switchboard` isn't on `PATH`, or, for Codex, `CLAUDECODE` is set. Otherwise it hands the payload to `switchboard hook <event>`, or `switchboard hook --agent codex <event>`. It drops the CLI's stderr and always exits 0, so a failing CLI can't deny a tool or keep a turn going. Each hook times out after 5 seconds, or 3 for Codex's `SessionEnd` and `Interrupt`, the most Codex allows them; an update usually takes a few tens of milliseconds.
