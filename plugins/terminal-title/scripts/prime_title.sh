#!/bin/bash
# SessionStart (startup|clear|compact): set a random placeholder title so the
# tab is never blank before the real task is known. Skips sessions that
# already have a cached title, since clear and compact keep the session id.

STATE_DIR="$HOME/.cache/claude-terminal-title"

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // ""' 2>/dev/null)

if [ -n "$SESSION_ID" ] && [ -f "$STATE_DIR/$SESSION_ID" ]; then
    exit 0
fi

ADJECTIVES=(quiet restless curious stubborn feral plucky drowsy brisk lucky sly giddy scrappy nimble wistful jolly cryptic spry wry bold tidy)
NOUNS=(otter comet lantern raccoon walrus falcon ember thicket marble compass beacon badger meadow kestrel anchor puzzle orbit satchel wren)

a1=${ADJECTIVES[$((RANDOM % ${#ADJECTIVES[@]}))]}
a2=${ADJECTIVES[$((RANDOM % ${#ADJECTIVES[@]}))]}
while [ "$a2" = "$a1" ]; do
    a2=${ADJECTIVES[$((RANDOM % ${#ADJECTIVES[@]}))]}
done
n=${NOUNS[$((RANDOM % ${#NOUNS[@]}))]}

bash "$(dirname "$0")/set_title.sh" "$a1 $a2 $n"
