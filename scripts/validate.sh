#!/bin/bash
# Validate the marketplace and each plugin it lists, treating warnings as
# errors like --strict, except "No version specified": plugins deliberately
# omit version so installs track the marketplace's commit SHA.
set -euo pipefail
cd "$(dirname "$0")/.."

status=0

validate() {
    local report issues
    if ! report=$(claude plugin validate --json "$1"); then
        status=1
    fi
    issues=$(printf '%s' "$report" | jq -r '
        [.manifest, (.contents // [])[]] | map(select(. != null))[] as $f
        | (($f.errors // []) + (($f.warnings // []) | map(select(.message | test("^No version specified") | not))))[]
        | "\($f.file): \(.path): \(.message)"')
    if [ -n "$issues" ] || [ "$(printf '%s' "$report" | jq -r '.success')" != true ]; then
        printf '%s\n' "${issues:-$report}" >&2
        status=1
    else
        echo "ok: $1"
    fi
}

validate .
while IFS= read -r source; do
    validate "$source"
done < <(jq -r '.plugins[] | select(.source | type == "string") | .source' .claude-plugin/marketplace.json)

exit "$status"
