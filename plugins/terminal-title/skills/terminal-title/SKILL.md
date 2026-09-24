---
name: terminal-title
description: Sets the terminal tab/window title to reflect the current task, as "login bug". Use at the start of a Claude Code session once the first task is clear, and again whenever the task changes to something substantially different. Skip for follow-ups, small tweaks, or clarifying questions on the same task.
allowed-tools: Bash(bash ${CLAUDE_PLUGIN_ROOT}/scripts/set_title.sh *)
---

Keep the terminal tab identifiable across multiple Claude Code sessions by setting its title to the current task.

## Title format

`<topic>`

- `topic` — lower case, 2-6 words, no filler. Examples: `auth flow`, `login bug`, `api reference`, `payment module`, `dotfiles cleanup`.

No project/folder prefix — the multiplexer or window manager already shows that.

## When to set it

- At the start of a session, once the user's first prompt makes the task clear.
- When switching to a substantially different task (different module, moving from debugging to building something new, etc.).
- Not for follow-ups, small tweaks, or clarifications on the same task.

## How

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/set_title.sh "login bug"
```

The script picks the right target on its own, first match wins:

- Inside Herdr (`$HERDR_TAB_ID` set) — renames the Herdr pane, and the tab too when this is its only pane. The terminal itself is left alone.
- Inside tmux (`$TMUX` set) — renames the tmux window via `tmux rename-window`. The terminal itself is left alone.
- Otherwise — sets the terminal window/tab title directly by writing an OSC escape sequence to `/dev/tty` (skipped when there is no terminal). Works in Ghostty, iTerm2, Terminal.app, Alacritty, and other xterm-compatible terminals.

Exits silently if no title is given, or if it's empty after sanitization (fail-safe — never blocks on this).

## Reliability

The plugin's SessionStart hooks (`hooks/hooks.json`) back this skill up, since invoking it can still be missed in some sessions:

- `scripts/session_start_context.sh` (`startup|clear|compact`) — injects this file's full text as `additionalContext` at session start, with the script path resolved, so these instructions are already in context instead of depending on a skill-list lookup.
- `scripts/prime_title.sh` (`startup|clear|compact`) — sets an immediate placeholder title, three random creative words (e.g. `quiet feral otter`), so the tab is never left on a blank/default title while the real task is still unclear. `set_title.sh` overwrites it as soon as the real topic is known.

Neither runs on `resume`: a resume is a follow-up, not a new task. Instead `scripts/restore_title.sh` (every session start) replays the last real title in Herdr, where a resumed session can land on a new pane.
