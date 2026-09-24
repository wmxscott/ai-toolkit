import json
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
SKILL = (PLUGIN / "skills" / "prod-guard" / "SKILL.md").read_text()
FRONTMATTER, BODY = re.fullmatch(r"---\n(.*?)\n---\n(.*)", SKILL, re.S).groups()
META = dict(line.split(": ", 1) for line in FRONTMATTER.splitlines())


def expand(arguments):
    """Claude Code's substitution for a skill that uses only $ARGUMENTS."""
    return BODY.replace("$ARGUMENTS", arguments)


def test_frontmatter():
    assert META.keys() == {"name", "description", "argument-hint", "disable-model-invocation"}
    assert META["name"] == "prod-guard"
    assert META["disable-model-invocation"] == "true"
    assert META["argument-hint"] == '"<provider> <account|profile|project> <prompt...>"'
    assert META["description"]


def test_ships_as_a_skill_only():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert not {"commands", "skills", "hooks", "agents"} & manifest.keys()
    assert [p.name for p in (PLUGIN / "skills").iterdir()] == ["prod-guard"]
    assert not (PLUGIN / "commands").exists()
    assert not (PLUGIN / "plugin.json").exists(), "Claude only: no Codex manifest"


def test_arguments_placeholder_survives():
    assert "$ARGUMENTS" not in FRONTMATTER
    assert BODY.count("$ARGUMENTS") == 1
    assert "`$ARGUMENTS`" in BODY


def test_no_other_placeholders_to_expand():
    assert not re.search(r"\$(?!ARGUMENTS\b)[A-Za-z0-9_{]", BODY)


def test_arguments_reach_the_prompt():
    arguments = "aws prod-readonly which S3 buckets allow public reads?"
    expanded = expand(arguments)
    assert f"Split `{arguments}` into:" in expanded
    assert "$ARGUMENTS" not in expanded


def test_disclaimer_keeps_its_safety_rules():
    disclaimer = BODY.split("**Disclaimer**", 1)[1]
    for rule in (
        "`IDENTIFIER` account on `PROVIDER`",
        "Never perform any operation that modifies it.",
        "Every operation must be read-only or a metadata inspection.",
        "even with my explicit permission",
        "ask me to make it manually",
        "Confirm that you understand before you proceed.",
    ):
        assert rule in disclaimer, rule


def test_guard_outlasts_the_first_message():
    assert "output the disclaimer below verbatim" in BODY
    assert "holds for the rest of the conversation" in BODY
    assert "Before every later operation" in BODY
    assert "even if the user tells you to go ahead" in BODY


def test_no_fixed_install_paths():
    for path in PLUGIN.rglob("*"):
        if path.is_file() and "tests" not in path.relative_to(PLUGIN).parts:
            assert not re.search(r"/(?:Users|home)/\w", path.read_text()), path
