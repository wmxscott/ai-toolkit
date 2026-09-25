#!/bin/bash
# Validate the marketplace and each plugin it lists, treating warnings as
# errors like --strict, except "No version specified": plugins deliberately
# omit version so installs track the marketplace's commit SHA.
#
# When codex is installed, also install every Codex plugin into a throwaway
# CODEX_HOME and check Codex loads each of its skills and hooks, and lists
# each skill for the model unless its agents/openai.yaml says not to. Codex has
# no validate command, so loading the plugins is the check.
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

# Ask a throwaway `codex app-server` for the skills and hooks it loads from $sandbox.
codex_rpc() {
    local fifo="$sandbox/rpc.in" out="$sandbox/rpc.out" pid tries=0
    mkfifo "$fifo"
    (cd "$sandbox" && sandboxed_codex app-server <"$fifo" >"$out" 2>/dev/null) &
    pid=$!
    exec 3>"$fifo"
    printf '%s\n' \
        '{"id":0,"method":"initialize","params":{"clientInfo":{"name":"validate","version":"0"}}}' \
        '{"method":"initialized"}' \
        '{"id":1,"method":"skills/list","params":{}}' \
        '{"id":2,"method":"hooks/list","params":{}}' >&3
    until [ "$(jq -s '[.[] | select(.id == 1 or .id == 2)] | length' "$out" 2>/dev/null)" = 2 ]; do
        tries=$((tries + 1))
        if [ "$tries" -gt 300 ]; then
            break
        fi
        sleep 0.1
    done
    exec 3>&-
    wait "$pid" || true
    jq -s '{skills: [.[] | select(.id == 1) | .result.data[].skills[].name],
            hooks: [.[] | select(.id == 2) | .result.data[].hooks[] | .pluginId // empty]}' "$out"
}

validate_codex() {
    local marketplace plugin skill prompt loaded listed
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
    loaded=$(codex_rpc)
    while IFS= read -r plugin; do
        for skill in "plugins/$plugin/skills"/*/; do
            [ -d "$skill" ] || continue
            # A skill Codex may only run when asked for isn't in the prompt's list.
            listed=true
            if grep -qx '  allow_implicit_invocation: false' "$skill/agents/openai.yaml" 2>/dev/null; then
                listed=false
            fi
            skill=$(basename "$skill")
            if ! jq -e --arg s "$plugin:$skill" '.skills | index($s)' <<<"$loaded" >/dev/null; then
                echo "codex does not load skill $plugin:$skill" >&2
                status=1
            elif grep -qF -- "- $plugin:$skill:" <<<"$prompt"; then
                if [ "$listed" = true ]; then
                    echo "ok: codex loads $plugin:$skill"
                else
                    echo "codex offers $plugin:$skill to the model despite its openai.yaml" >&2
                    status=1
                fi
            elif [ "$listed" = true ]; then
                echo "codex does not list skill $plugin:$skill" >&2
                status=1
            else
                echo "ok: codex loads $plugin:$skill, for explicit use only"
            fi
        done
        if [ -f "plugins/$plugin/hooks/hooks.json" ]; then
            if jq -e --arg p "$plugin@$marketplace" '.hooks | index($p)' <<<"$loaded" >/dev/null; then
                echo "ok: codex loads $plugin's hooks"
            else
                echo "codex does not load $plugin's hooks" >&2
                status=1
            fi
        fi
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
