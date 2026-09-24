#!/bin/bash
# Usage: set_title.sh "<topic>"
# Renames the Herdr pane/tab, else the tmux window, else the terminal (OSC 0).

STATE_DIR="$HOME/.cache/claude-terminal-title"

if [ -z "$1" ]; then
    exit 0
fi

TITLE=$(printf '%s' "$1" | tr -d '\000-\037' | head -c 80)

if [ -z "$TITLE" ]; then
    exit 0
fi

if [ -n "$HERDR_TAB_ID" ] && command -v herdr >/dev/null 2>&1; then
    PANE_COUNT=1
    if command -v jq >/dev/null 2>&1; then
        PANE_COUNT=$(herdr tab get "$HERDR_TAB_ID" 2>/dev/null | jq -r '.result.tab.pane_count // 1')
    fi
    case "$PANE_COUNT" in
        ''|*[!0-9]*) PANE_COUNT=1 ;;
    esac

    # Durable rename, not `pane report-metadata`: metadata tokens are
    # display-only and are lost when the herdr server restarts.
    herdr pane rename "$HERDR_PANE_ID" "$TITLE" >/dev/null 2>&1
    # A shared tab's name belongs to all of its panes, so only rename a solo tab.
    if [ "$PANE_COUNT" -le 1 ]; then
        herdr tab rename "$HERDR_TAB_ID" "$TITLE" >/dev/null 2>&1
    fi

    # restore_title.sh replays this on resume: herdr issues new pane ids when
    # panes move between tabs, so the label above doesn't follow the session.
    if [ -n "$CLAUDE_CODE_SESSION_ID" ]; then
        mkdir -p "$STATE_DIR" 2>/dev/null
        printf '%s' "$TITLE" > "$STATE_DIR/$CLAUDE_CODE_SESSION_ID" 2>/dev/null
    fi
    exit 0
fi

if [ -n "$TMUX" ] && command -v tmux >/dev/null 2>&1; then
    # -t is required: a script has no "current window" to default to.
    # automatic-rename off, or tmux reverts the name at the next prompt.
    tmux set-window-option -t "$TMUX_PANE" automatic-rename off >/dev/null 2>&1
    tmux rename-window -t "$TMUX_PANE" "$TITLE" >/dev/null 2>&1
    exit 0
fi

printf '\033]0;%s\007' "$TITLE"
