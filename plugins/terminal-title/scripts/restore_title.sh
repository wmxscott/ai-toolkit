#!/bin/bash
# SessionStart (any source): replay this session's cached title onto the
# herdr pane it runs in now. A resumed session may land on a new pane id, and
# a resume is a follow-up, so the skill wouldn't set the title again.

STATE_DIR="$HOME/.cache/claude-terminal-title"

INPUT=$(cat)

[ "$(echo "$INPUT" | jq -r '.hook_event_name // ""')" = "SessionStart" ] || exit 0
[ -z "$(echo "$INPUT" | jq -r '.agent_id // ""')" ] || exit 0

SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // ""')
if [ -z "$SESSION_ID" ]; then
    exit 0
fi

if [ -z "$HERDR_TAB_ID" ] || ! command -v herdr >/dev/null 2>&1; then
    exit 0
fi

STATE_FILE="$STATE_DIR/$SESSION_ID"
if [ ! -f "$STATE_FILE" ]; then
    exit 0
fi

TITLE=$(cat "$STATE_FILE" 2>/dev/null)
if [ -z "$TITLE" ]; then
    exit 0
fi

bash "$(dirname "$0")/set_title.sh" "$TITLE"
