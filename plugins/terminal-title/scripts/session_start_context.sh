#!/bin/bash
# SessionStart (startup|clear|compact): inline SKILL.md as additionalContext so
# the instructions don't depend on the model spotting the skill in its list.
# The text is inlined raw, so resolve the plugin root placeholder here.

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILL_MD="$PLUGIN_ROOT/skills/terminal-title/SKILL.md"

skill_content=$(cat "$SKILL_MD" 2>&1 || echo "Error reading terminal-title skill")
placeholder="\${CLAUDE_PLUGIN_ROOT}"
# Quoted so both sides are literal, even with bash 5.2's patsub_replacement.
skill_content=${skill_content//"$placeholder"/"$PLUGIN_ROOT"}

escape_for_json() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    printf '%s' "$s"
}

skill_escaped=$(escape_for_json "$skill_content")
context="<IMPORTANT>\nYou have a 'terminal-title' skill. Its full instructions are inlined below so this reminder can't be missed:\n\n${skill_escaped}\n\nOnce the user's first message makes the task clear, follow the How section above and set the title before your first substantive response. Skip only for follow-ups or clarifying questions on the same task.\n</IMPORTANT>"

printf '{\n  "hookSpecificOutput": {\n    "hookEventName": "SessionStart",\n    "additionalContext": "%s"\n  }\n}\n' "$context"

exit 0
