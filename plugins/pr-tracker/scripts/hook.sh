#!/bin/bash
# Runs `pr-tracker hook [<mode>]` on the hook payload from stdin. Does nothing when
# the CLI isn't installed. Exits 0, since a nonzero status would block a Stop hook,
# except for `wait`: it runs as an asyncRewake hook, where its exit 2 wakes the
# idle session with the events it printed.
#
# Hooks inherit the agent's PATH, which is minimal when it was started from a
# GUI, so the usual install locations are tried after it. Claude Code and Codex
# both run this, and it needs nothing from either beyond the payload.
# PR_TRACKER_HOOK_FALLBACK_PATH replaces those locations, for tests.

fallback=${PR_TRACKER_HOOK_FALLBACK_PATH-/opt/homebrew/bin:/usr/local/bin:/home/linuxbrew/.linuxbrew/bin${HOME:+:$HOME/.local/bin}}
if [ -n "$fallback" ]; then
    PATH="${PATH:+$PATH:}$fallback"
    export PATH
fi

if ! command -v pr-tracker >/dev/null 2>&1; then
    cat >/dev/null
    exit 0
fi

pr-tracker hook "$@" 2>/dev/null
status=$?
if [ "${1-}" = wait ] && [ "$status" -eq 2 ]; then
    exit 2
fi
exit 0
