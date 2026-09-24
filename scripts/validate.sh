#!/bin/bash
# Validate the marketplace and each plugin it lists, treating warnings as
# errors like --strict, except "No version specified": plugins deliberately
# omit version so installs track the marketplace's commit SHA.
#
# When codex is installed, also install every Codex plugin into a throwaway
# CODEX_HOME and check Codex lists each of its skills. Codex has no validate
# command, so loading the plugins is the check.
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

sandboxed_codex() {
    HOME="$sandbox" CODEX_HOME="$sandbox/codex" command codex "$@"
}

validate_codex() {
    local marketplace plugin skill prompt
    sandbox=$(mktemp -d)
    trap 'rm -rf "$sandbox"' EXIT
    mkdir "$sandbox/codex"
    marketplace=$(jq -r .name .agents/plugins/marketplace.json)
    sandboxed_codex plugin marketplace add "$PWD" >/dev/null
    while IFS= read -r plugin; do
        if ! sandboxed_codex plugin add "$plugin@$marketplace" >/dev/null; then
            echo "codex could not install $plugin" >&2
            status=1
        fi
    done < <(jq -r '.plugins[].name' .agents/plugins/marketplace.json)
    prompt=$(cd "$sandbox" && sandboxed_codex debug prompt-input)
    while IFS= read -r plugin; do
        for skill in "plugins/$plugin/skills"/*/; do
            [ -d "$skill" ] || continue
            skill=$(basename "$skill")
            if grep -qF -- "- $plugin:$skill:" <<<"$prompt"; then
                echo "ok: codex loads $plugin:$skill"
            else
                echo "codex does not list skill $plugin:$skill" >&2
                status=1
            fi
        done
    done < <(jq -r '.plugins[].name' .agents/plugins/marketplace.json)
}

validate .
while IFS= read -r source; do
    validate "$source"
done < <(jq -r '.plugins[] | select(.source | type == "string") | .source' .claude-plugin/marketplace.json)

if command -v codex >/dev/null 2>&1; then
    validate_codex
else
    echo "skip: codex not installed, Codex plugins not loaded"
fi

exit "$status"
