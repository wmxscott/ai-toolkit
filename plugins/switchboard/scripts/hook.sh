#!/bin/bash
# Usage: hook.sh <event>, with the hook payload on stdin.
# Starts no Python outside tmux or without the CLI: this runs on every tool call.

if [ -z "${TMUX_PANE-}" ] || ! command -v switchboard >/dev/null 2>&1; then
    exit 0
fi

# A nonzero status could deny a tool or keep a turn going, so a failing CLI is ignored.
switchboard hook "$1" 2>/dev/null
exit 0
