#!/bin/bash
# Usage: hook.sh <event> [agent], with the hook payload on stdin. No agent means Claude Code.
# Starts no Python outside tmux or without the CLI: this runs on every tool call.

if [ -z "${TMUX_PANE-}" ] || ! command -v switchboard >/dev/null 2>&1; then
    exit 0
fi

# Codex started from inside Claude Code inherits Claude's pane, which isn't its own.
if [ "${2-}" = codex ] && [ -n "${CLAUDECODE-}" ]; then
    exit 0
fi

# A nonzero status could deny a tool or keep a turn going, so a failing CLI is ignored.
switchboard hook ${2:+--agent "$2"} "$1" 2>/dev/null
exit 0
