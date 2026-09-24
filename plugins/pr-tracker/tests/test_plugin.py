import json
import re
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
HOOKS = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
WRAPPER = r'bash "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/hook\.sh" '


def frontmatter(skill):
    text = (PLUGIN / "skills" / skill / "SKILL.md").read_text()
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, skill
    return dict(line.split(": ", 1) for line in match[1].splitlines()), text[match.end() :]


def test_hooks_call_the_cli_modes():
    assert set(HOOKS) == {"PostToolUse", "Stop"}
    found = {}
    for event, groups in HOOKS.items():
        for group in groups:
            [hook] = group["hooks"]
            assert hook["type"] == "command"
            assert hook["timeout"] == 10
            match = re.fullmatch(WRAPPER + r"([a-z-]+)", hook["command"])
            assert match, hook["command"]
            found[match[1]] = (event, group.get("matcher"))
    assert found == {
        "post-bash": ("PostToolUse", "Bash"),
        "post-mcp": ("PostToolUse", "mcp__.*github.*__create_pull_request"),
        "stop": ("Stop", None),
    }


@pytest.mark.parametrize(
    "tool",
    [
        "mcp__github__create_pull_request",
        "mcp__plugin_github_github__create_pull_request",
        "mcp__my-github-server__create_pull_request",
    ],
)
def test_mcp_matcher_catches_github_servers(tool):
    [group] = [g for g in HOOKS["PostToolUse"] if g["matcher"] != "Bash"]
    assert re.fullmatch(group["matcher"], tool)


def test_tracker_skill_frontmatter():
    fields, _ = frontmatter("pr-tracker")
    assert fields.keys() == {"name", "description", "allowed-tools"}
    assert fields["name"] == "pr-tracker"
    assert fields["description"].startswith("Use when")
    assert len(fields["description"]) <= 1024
    assert fields["allowed-tools"] == "Bash(pr-tracker list *) Bash(pr-tracker status)"


def test_prs_is_a_user_command():
    fields, body = frontmatter("prs")
    assert fields.keys() == {
        "name",
        "description",
        "disable-model-invocation",
        "argument-hint",
        "allowed-tools",
    }
    assert fields["name"] == "prs"
    assert fields["disable-model-invocation"] == "true"
    assert fields["allowed-tools"] == "Bash(pr-tracker list *)"
    assert 'pr-tracker list --scope session --session "${CLAUDE_SESSION_ID}"' in body
    assert "prs --session ${CLAUDE_SESSION_ID}" in body


@pytest.mark.parametrize("skill", ["pr-tracker", "prs"])
def test_skills_call_the_cli_and_pass_the_session(skill):
    _, body = frontmatter(skill)
    commands = re.findall(r"^pr-tracker .+$", body, re.M)
    assert commands
    for command in commands:
        if command.split()[1] in {"adopt", "untrack"} or "--scope session" in command:
            assert '--session "${CLAUDE_SESSION_ID}"' in command, command
    assert "python" not in body
    assert "CLAUDE_PLUGIN_ROOT" not in body


def test_no_fixed_install_paths():
    for path in PLUGIN.rglob("*"):
        if path.is_file() and "tests" not in path.relative_to(PLUGIN).parts:
            text = path.read_text()
            assert ".agents/" not in text, path
            assert not re.search(r"/(?:Users|home)/(?!linuxbrew/)\w", text), path
