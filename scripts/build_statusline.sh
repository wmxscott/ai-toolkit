#!/bin/bash
# Build the statusline binaries reproducibly and write their SHA-256 sums to
# plugins/statusline/checksums.txt, which the plugin verifies downloads against.
#
# Usage: build_statusline.sh [--check] [--out DIR] [--checksums FILE]
#   --check           compare with the checksums file instead of rewriting it
#   --out DIR         keep the binaries in DIR
#   --checksums FILE  use FILE instead of plugins/statusline/checksums.txt
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
src="$root/plugins/statusline"

check=0
out=
sums="$src/checksums.txt"
while [ $# -gt 0 ]; do
    case "$1" in
        --check) check=1 ;;
        --out)
            out=${2:?--out needs a directory}
            shift
            ;;
        --checksums)
            sums=${2:?--checksums needs a file}
            shift
            ;;
        *)
            echo "usage: $0 [--check] [--out DIR] [--checksums FILE]" >&2
            exit 2
            ;;
    esac
    shift
done

if ! command -v go >/dev/null 2>&1; then
    echo "build_statusline.sh: go is not installed (see plugins/statusline/go.mod for the version)" >&2
    exit 1
fi
if command -v shasum >/dev/null 2>&1; then
    sha256() { shasum -a 256 "$@"; }
else
    sha256() { sha256sum "$@"; }
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
if [ -z "$out" ]; then
    out="$tmp/bin"
fi
mkdir -p "$out"
out=$(cd "$out" && pwd)

cd "$src"
for target in darwin/amd64 darwin/arm64 linux/amd64 linux/arm64; do
    name="statusline-${target%/*}-${target#*/}"
    CGO_ENABLED=0 GOOS=${target%/*} GOARCH=${target#*/} \
        go build -trimpath -buildvcs=false -ldflags "-s -w -buildid=" -o "$out/$name" ./cmd/statusline
done

(cd "$out" && sha256 statusline-darwin-amd64 statusline-darwin-arm64 \
    statusline-linux-amd64 statusline-linux-arm64) >"$tmp/checksums.txt"

if [ "$check" = 1 ]; then
    if ! diff -u "$sums" "$tmp/checksums.txt"; then
        echo "build_statusline.sh: binaries differ from $sums; run scripts/build_statusline.sh and commit it" >&2
        exit 1
    fi
    echo "ok: binaries match $sums"
else
    cp "$tmp/checksums.txt" "$sums"
    echo "wrote $sums"
fi
