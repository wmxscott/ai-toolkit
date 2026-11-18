# switchboard

Connects Claude Code to [switchboard](https://github.com/wmxscott/switchboard), a tmux session switcher that shows which Claude Code agents are working, which are done and which need you. The plugin's hooks tell the CLI when an agent's state changes, and the CLI keeps that state in tmux for the switcher and the status bar.

The plugin is only the hooks. The CLI does the work.

## Install

The plugin needs tmux and the switchboard CLI:

```sh
brew install wmxscott/tap/switchboard
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install switchboard@ai-toolkit
```

Outside tmux, or without `switchboard` on your `PATH`, the plugin does nothing: every hook exits at once, without starting the CLI.

The tmux side is set up separately: the key binding that opens the switcher, the `client-session-changed` hook that marks finished agents seen, and the status-bar segment. The [switchboard README](https://github.com/wmxscott/switchboard) has the lines to add to your tmux config.

Claude Code only.

## Hooks

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

Each hook runs `scripts/hook.sh <event>`, which exits 0 at once when `$TMUX_PANE` is unset or `switchboard` isn't on `PATH`, and otherwise hands the payload to `switchboard hook <event>`. It drops the CLI's stderr and always exits 0, so a failing CLI can't deny a tool or keep a turn going. Each hook times out after 5 seconds; an update usually takes a few tens of milliseconds.
