#!/bin/bash
# Fail when a plugin that has a version where HEAD forked from BASE changed
# since then without a version bump. Plugins without a version are skipped.
#
# Usage: check_plugin_versions.sh BASE
set -euo pipefail
base=${1:?usage: $0 BASE}
cd "$(git rev-parse --show-toplevel)"
git rev-parse --verify --quiet "$base^{commit}" >/dev/null || {
    echo "check_plugin_versions.sh: unknown ref $base" >&2
    exit 2
}
mb=$(git merge-base "$base" HEAD)

version() {
    git show "$1:$2/.claude-plugin/plugin.json" 2>/dev/null | jq -r '.version // empty' || true
}

status=0
for dir in $(git ls-tree -d --name-only "$mb" plugins/); do
    old=$(version "$mb" "$dir")
    [ -n "$old" ] || continue
    git diff --quiet "$mb" HEAD -- "$dir" && continue
    if [ "$(version HEAD "$dir")" = "$old" ]; then
        echo "$dir changed but its version is still $old; bump it in $dir/.claude-plugin/plugin.json" >&2
        status=1
    fi
done
exit $status
