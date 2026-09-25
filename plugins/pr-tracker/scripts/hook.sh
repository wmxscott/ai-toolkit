#!/bin/bash
# Runs `pr-tracker hook <mode>` on the hook payload from stdin. Does nothing when
# the CLI isn't installed. Always exits 0: a nonzero status, such as argparse's 2
# from a CLI too old to know <mode>, would block a Stop hook.
#
# Hooks inherit Claude Code's PATH, which is minimal when it was started from a
# GUI, so the usual install locations are tried after it.
# PR_TRACKER_HOOK_FALLBACK_PATH replaces those locations, for tests.

fallback=${PR_TRACKER_HOOK_FALLBACK_PATH-/opt/homebrew/bin:/usr/local/bin:/home/linuxbrew/.linuxbrew/bin:$HOME/.local/bin}
if [ -n "$fallback" ]; then
    PATH="${PATH:+$PATH:}$fallback"
    export PATH
fi

if ! command -v pr-tracker >/dev/null 2>&1; then
    cat >/dev/null
    exit 0
fi

pr-tracker hook "$@" 2>/dev/null
exit 0
