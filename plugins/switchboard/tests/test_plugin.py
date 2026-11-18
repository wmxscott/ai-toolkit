import json
import re
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
HOOKS = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
CODEX_HOOKS = json.loads((PLUGIN / "hooks" / "codex.json").read_text())["hooks"]
CODEX_MANIFEST = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())

# The events switchboard's `hook` handles, each with the matcher that limits it to the calls
# that can change an agent's state. None runs it on every occurrence.
EXPECTED = {
    "SessionStart": None,
    "UserPromptSubmit": None,
    "PreToolUse": "AskUserQuestion|ExitPlanMode",
    "PostToolUse": None,
    "PostToolUseFailure": None,
    "PermissionRequest": None,
    "Notification": "permission_prompt|idle_prompt|elicitation_dialog|elicitation_url_dialog",
    "Stop": None,
    "StopFailure": None,
    "SubagentStop": None,
    "TeammateIdle": None,
    "SessionEnd": None,
}

CODEX_EXPECTED = {
    "SessionStart": None,
    "UserPromptSubmit": None,
    "PreToolUse": "request_user_input",
    "PermissionRequest": None,
    "PostToolUse": None,
    "Stop": None,
    "SubagentStop": None,
    "Interrupt": None,
    "SessionEnd": None,
}

# HookEventsToml in Codex 0.170.0.
CODEX_EVENTS = {
    "PreModelRequest",
    "PostModelRequest",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PreCompact",
    "PostCompact",
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "SubagentStart",
    "SubagentStop",
    "Stop",
    "Interrupt",
}
# Codex clamps these events' timeouts to 3 seconds.
CODEX_CAPPED = {"SessionEnd", "Interrupt"}


def matchers(hooks, command):
    found = {}
    for event, groups in hooks.items():
        [group] = groups
        [hook] = group["hooks"]
        assert hook["type"] == "command"
        assert hook["command"] == command(event)
        assert not {"async", "asyncRewake"} & hook.keys()
        found[event] = group.get("matcher")
    return found


def test_each_event_runs_the_script_with_its_name():
    found = matchers(HOOKS, lambda e: f'bash "${{CLAUDE_PLUGIN_ROOT}}/scripts/hook.sh" {e}')
    assert found == EXPECTED
    for groups in HOOKS.values():
        assert groups[0]["hooks"][0]["timeout"] <= 5


def test_each_codex_event_runs_the_script_with_its_name_and_codex():
    found = matchers(
        CODEX_HOOKS, lambda e: f'bash "${{CLAUDE_PLUGIN_ROOT}}/scripts/hook.sh" {e} codex'
    )
    assert found == CODEX_EXPECTED


@pytest.mark.parametrize("event", CODEX_EXPECTED)
def test_codex_timeouts_stay_within_codex_caps(event):
    [group] = CODEX_HOOKS[event]
    [hook] = group["hooks"]
    assert hook["timeout"] == (3 if event in CODEX_CAPPED else 5)


def test_codex_hooks_only_use_codex_events():
    assert set(CODEX_HOOKS) <= CODEX_EVENTS
    assert not {"Notification", "PostToolUseFailure", "StopFailure", "TeammateIdle"} & set(
        CODEX_HOOKS
    )


def test_matchers_are_exact_names():
    """Only letters, digits, `_` and `|` keep a matcher off Claude Code's unanchored regex
    path, for every event. Codex reads such a matcher as exact names too."""
    for matcher in filter(None, [*EXPECTED.values(), *CODEX_EXPECTED.values()]):
        assert re.fullmatch(r"\w+(\|\w+)*", matcher, re.ASCII), matcher


def test_manifest_leaves_hooks_to_hooks_json():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert "hooks" not in manifest
    assert "version" not in manifest


def test_codex_manifest_names_codex_json():
    """Codex reads the manifest's `hooks` in place of hooks/hooks.json, not as well."""
    assert CODEX_MANIFEST["hooks"] == "./hooks/codex.json"
    assert "version" not in CODEX_MANIFEST


def test_no_fixed_install_paths():
    for path in PLUGIN.rglob("*"):
        if path.is_file() and "tests" not in path.relative_to(PLUGIN).parts:
            text = path.read_text()
            assert ".agents/" not in text, path
            assert not re.search(r"/(?:Users|home)/\w", text), path
