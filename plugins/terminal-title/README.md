# terminal-title

Names your terminal tab after what Claude Code is working on, such as `login bug` or `auth flow`, so you can tell sessions apart at a glance.

Claude sets the title once the first task is clear, and again when the task changes to something substantially different. Until then the tab gets a random placeholder like `quiet feral otter`, never a blank default.

## Install

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install terminal-title@ai-toolkit
```

Needs `bash` and `jq`.

## Where the title goes

First match wins:

| Running inside | What gets renamed |
|---|---|
| Herdr (`$HERDR_TAB_ID` set) | The pane, and the tab too when it's the only pane in it |
| tmux (`$TMUX` set) | The window. Automatic renaming is turned off for it, so the shell doesn't rename it back |
| Anything else | The terminal window or tab, via an OSC escape sequence written to `/dev/tty`, never stdout. Skipped when there's no terminal. Works in Ghostty, iTerm2, Terminal.app, Alacritty and other xterm-compatible terminals |

Control characters are stripped and titles are cut to 80 characters.

## How it works

The `terminal-title` skill tells Claude when and how to set the title, by running `scripts/set_title.sh "<topic>"`. Skills can be missed, so three SessionStart hooks back it up:

| Hook | Runs on | Does |
|---|---|---|
| `session_start_context.sh` | `startup`, `clear`, `compact` | Puts the skill's full text in Claude's context, so it doesn't depend on Claude spotting the skill |
| `prime_title.sh` | `startup`, `clear`, `compact` | Sets the random placeholder title, unless this session already has a real one |
| `restore_title.sh` | every start, including `resume` | In Herdr, puts back the session's last title. A resumed session can land on a new pane, and Claude treats a resume as a follow-up, so it wouldn't set the title again |

In Herdr, `set_title.sh` remembers each session's title in `~/.cache/claude-terminal-title/<session id>` so the restore hook can find it.

## Permissions

The skill pre-approves `set_title.sh` for the turn in which Claude invokes it. When Claude runs the script straight from the session-start context instead, Claude Code may ask first. Approving with "don't ask again" lasts until the plugin updates, since the script's path includes the plugin version.

## Agent support

Claude Code only, for now.
