import json
import os
import re
import subprocess
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
HOOKS = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
SKILL = (PLUGIN / "skills" / "setup" / "SKILL.md").read_text()


def frontmatter(text):
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match
    return dict(line.split(": ", 1) for line in match[1].splitlines())


def test_session_start_hook_links_on_every_start():
    assert set(HOOKS) == {"SessionStart"}
    [group] = HOOKS["SessionStart"]
    assert group["matcher"] == "*"
    [hook] = group["hooks"]
    assert hook["type"] == "command"
    assert hook["timeout"] == 10
    assert hook["command"] == 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/link_statusline.sh"'


def test_setup_skill_runs_the_bundled_script_and_preapproves_it():
    meta = frontmatter(SKILL)
    assert meta["name"] == "setup"
    assert meta["disable-model-invocation"] == "true"
    command = "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup_statusline.py"
    assert meta["allowed-tools"] == f"Bash({command} *)"
    assert f'{command} "${{CLAUDE_PLUGIN_DATA}}"' in SKILL
    assert "--force" in SKILL


def test_scripts_are_executable():
    for script in (PLUGIN / "scripts").glob("*.*"):
        assert os.access(script, os.X_OK), script


def shipped_files():
    listed = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "--", "."],
        cwd=PLUGIN,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [PLUGIN / name for name in listed if not name.startswith("tests/")]


def test_no_fixed_install_paths():
    files = shipped_files()
    assert PLUGIN / "scripts" / "statusline.py" in files
    for path in files:
        if path.is_file():
            text = path.read_text()
            assert "plugins/cache" not in text, path
            assert not re.search(r"/(?:Users|home)/\w", text), path
