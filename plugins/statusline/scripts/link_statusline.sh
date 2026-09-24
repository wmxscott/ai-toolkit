#!/bin/bash
# SessionStart: point $CLAUDE_PLUGIN_DATA/statusline.py at this version's
# script. The data dir survives plugin updates, so settings.json can run a
# stable path while the versioned install path changes underneath it.

root=${CLAUDE_PLUGIN_ROOT:-}
data=${CLAUDE_PLUGIN_DATA:-}
[ -n "$root" ] && [ -n "$data" ] || exit 0

target="$root/scripts/statusline.py"
link="$data/statusline.py"
[ -f "$target" ] || exit 0
[ -L "$link" ] && [ "$(readlink "$link")" = "$target" ] && exit 0

mkdir -p "$data" 2>/dev/null || exit 0
# Build the link beside the old one and rename it into place, so a statusline
# refresh never finds the path missing.
tmp="$link.$$.tmp"
if ln -s "$target" "$tmp" 2>/dev/null; then
    mv -f "$tmp" "$link" 2>/dev/null || rm -f "$tmp"
fi
exit 0
