import json
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
HOOKS = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]

# The events switchboard's `hook` handles, each with the matcher that limits it to the calls
# that can change an agent's state. None runs it on every occurrence.
EXPECTED = {
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


def test_each_event_runs_the_script_with_its_name():
    found = {}
    for event, groups in HOOKS.items():
        [group] = groups
        [hook] = group["hooks"]
        assert hook["type"] == "command"
        assert hook["command"] == f'bash "${{CLAUDE_PLUGIN_ROOT}}/scripts/hook.sh" {event}'
        assert hook["timeout"] <= 5
        assert not {"async", "asyncRewake"} & hook.keys()
        found[event] = group.get("matcher")
    assert found == EXPECTED


def test_matchers_are_exact_names():
    """Only letters, digits, `_` and `|` keep a matcher off Claude Code's unanchored regex
    path, for every event."""
    for matcher in filter(None, EXPECTED.values()):
        assert re.fullmatch(r"\w+(\|\w+)*", matcher, re.ASCII), matcher


def test_manifest_leaves_hooks_to_hooks_json():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert "hooks" not in manifest
    assert "version" not in manifest


def test_no_fixed_install_paths():
    for path in PLUGIN.rglob("*"):
        if path.is_file() and "tests" not in path.relative_to(PLUGIN).parts:
            text = path.read_text()
            assert ".agents/" not in text, path
            assert not re.search(r"/(?:Users|home)/\w", text), path
