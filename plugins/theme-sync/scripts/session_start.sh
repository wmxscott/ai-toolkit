#!/bin/bash
# SessionStart: sync the theme file once and make sure a watcher is running.
# Silent, quick, and never blocks the session.

root=${CLAUDE_PLUGIN_ROOT:-}
data=${CLAUDE_PLUGIN_DATA:-}
[ -n "$root" ] && [ -n "$data" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

python3 "$root/scripts/theme_sync.py" start "$data" </dev/null >/dev/null 2>&1
exit 0
