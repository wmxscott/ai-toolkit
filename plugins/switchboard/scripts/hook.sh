#!/bin/bash
# Usage: hook.sh <event>, with the hook payload on stdin.
# Starts no Python outside tmux or without the CLI: this runs on every tool call.

if [ -z "${TMUX_PANE-}" ] || ! command -v switchboard >/dev/null 2>&1; then
    exit 0
fi

exec switchboard hook "$1"
