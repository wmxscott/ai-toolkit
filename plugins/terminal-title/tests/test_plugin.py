import json
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
HOOKS = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]


def hook_commands():
    for group in HOOKS["SessionStart"]:
        for hook in group["hooks"]:
            yield group["matcher"], hook


def test_hooks_match_the_intended_session_starts():
    assert set(HOOKS) == {"SessionStart"}
    scripts = {}
    for matcher, hook in hook_commands():
        assert hook["type"] == "command"
        assert hook["timeout"] == 10
        match = re.fullmatch(
            r'bash "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/([a-z_]+\.sh)"', hook["command"]
        )
        assert match, hook["command"]
        assert (PLUGIN / "scripts" / match[1]).is_file()
        scripts[match[1]] = matcher
    assert scripts == {
        "restore_title.sh": "*",
        "prime_title.sh": "startup|clear|compact",
        "session_start_context.sh": "startup|clear|compact",
    }


def test_skill_runs_the_bundled_script_and_preapproves_it():
    skill = (PLUGIN / "skills" / "terminal-title" / "SKILL.md").read_text()
    command = "bash ${CLAUDE_PLUGIN_ROOT}/scripts/set_title.sh"
    assert f"allowed-tools: Bash({command} *)" in skill
    assert f'{command} "login bug"' in skill


def test_no_fixed_install_paths():
    for path in PLUGIN.rglob("*"):
        if path.is_file() and "tests" not in path.relative_to(PLUGIN).parts:
            text = path.read_text()
            assert ".agents/" not in text, path
            assert not re.search(r"/(?:Users|home)/\w", text), path
