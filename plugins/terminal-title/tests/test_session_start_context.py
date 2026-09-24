import json
import shutil
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
SKILL_MD = PLUGIN / "skills" / "terminal-title" / "SKILL.md"
PLACEHOLDER = "${CLAUDE_PLUGIN_ROOT}"


def context(sandbox, plugin_root=PLUGIN):
    result = sandbox.run(
        "session_start_context.sh",
        stdin={"hook_event_name": "SessionStart", "source": "startup"},
        script_dir=plugin_root / "scripts",
    )
    output = json.loads(result.stdout)
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    return output["hookSpecificOutput"]["additionalContext"]


def test_inlines_skill_with_resolved_script_path(sandbox):
    text = context(sandbox)
    skill = SKILL_MD.read_text().rstrip("\n")
    assert PLACEHOLDER in skill
    assert skill.replace(PLACEHOLDER, str(PLUGIN)) in text
    assert PLACEHOLDER not in text
    assert f"bash {PLUGIN}/scripts/set_title.sh" in text
    assert text.startswith("<IMPORTANT>\n")
    assert text.endswith("</IMPORTANT>")


def test_escapes_awkward_install_paths(sandbox, tmp_path):
    root = tmp_path / 'odd & "quoted" \\ dir\tname' / "terminal-title"
    shutil.copytree(PLUGIN / "scripts", root / "scripts")
    shutil.copytree(PLUGIN / "skills", root / "skills")
    text = context(sandbox, root)
    assert f"bash {root}/scripts/set_title.sh" in text
    assert PLACEHOLDER not in text


def test_missing_skill_still_emits_valid_json(sandbox, tmp_path):
    root = tmp_path / "terminal-title"
    shutil.copytree(PLUGIN / "scripts", root / "scripts")
    assert "Error reading terminal-title skill" in context(sandbox, root)
