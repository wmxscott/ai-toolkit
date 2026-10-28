#!/bin/bash
# SessionStart: point $CLAUDE_PLUGIN_DATA/statusline at this version's binary,
# downloading it from the GitHub release in the background when it's missing.
# The data dir survives plugin updates, so settings.json can run a stable path
# while the versioned install path changes underneath it. Always exits 0 at
# once; --foreground downloads inline instead (setup uses it). Nothing but the
# upgrade notice ever goes to stdout.

settings="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"
if grep -q 'statusline-ai-toolkit/statusline\.py' "$settings" 2>/dev/null; then
    echo '{"systemMessage": "statusline: run /statusline:setup to switch to the faster version"}'
fi

root=${CLAUDE_PLUGIN_ROOT:-}
data=${CLAUDE_PLUGIN_DATA:-}
[ -n "$root" ] && [ -n "$data" ] || exit 0

version=$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
    "$root/.claude-plugin/plugin.json" 2>/dev/null | head -n 1)
case $version in
    "" | *[!0-9A-Za-z.+-]*) exit 0 ;;
esac

case $(uname -s 2>/dev/null) in
    Darwin) os=darwin ;;
    Linux) os=linux ;;
    *) exit 0 ;;
esac
case $(uname -m 2>/dev/null) in
    arm64 | aarch64) arch=arm64 ;;
    x86_64 | amd64) arch=amd64 ;;
    *) exit 0 ;;
esac

name="statusline-$os-$arch"
bin="$data/bin"
binary="$bin/statusline-$version-$os-$arch"
link="$data/statusline"
url="https://github.com/wmxscott/ai-toolkit/releases/download/statusline-v$version/$name"

relink() {
    [ -L "$link" ] && [ "$(readlink "$link")" = "$binary" ] && return 0
    # Build the link beside the old one and rename it into place, so a
    # statusline refresh never finds the path missing.
    local new="$link.$$.tmp"
    if ln -s "$binary" "$new"; then
        mv -f "$new" "$link" || rm -f "$new"
    fi
}

download() {
    lock="$bin/.download.lock"
    expected=$(awk -v n="$name" '$2 == n { print $1 }' "$root/checksums.txt")
    [ -n "$expected" ] || return 0
    command -v curl >/dev/null || return 0
    if command -v shasum >/dev/null; then
        sha256() { shasum -a 256 "$1"; }
    elif command -v sha256sum >/dev/null; then
        sha256() { sha256sum "$1"; }
    else
        return 0
    fi

    mkdir -p "$bin" || return 0
    if [ -n "$(find "$lock" -maxdepth 0 -mmin +2)" ]; then
        rmdir "$lock"
    fi
    mkdir "$lock" || return 0
    trap 'rm -f "$tmp"; rmdir "$lock"' EXIT
    if [ -f "$binary" ]; then
        relink
        return 0
    fi

    tmp=$(mktemp "$bin/.download.XXXXXX") || return 0
    curl -fsSL --max-time 30 -o "$tmp" "$url" || return 0
    actual=$(sha256 "$tmp") || return 0
    [ "${actual%% *}" = "$expected" ] || return 0
    chmod +x "$tmp" && mv -f "$tmp" "$binary" || return 0
    relink
    for f in "$bin"/statusline-*; do
        [ "$f" = "$binary" ] || rm -f "$f"
    done
}

if [ -f "$binary" ]; then
    relink >/dev/null 2>&1
    exit 0
fi

if [ "${1:-}" = --foreground ]; then
    (download) </dev/null >/dev/null 2>&1
else
    (
        trap '' HUP
        download
    ) </dev/null >/dev/null 2>&1 &
fi
exit 0
