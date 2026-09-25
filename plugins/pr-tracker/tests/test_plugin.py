import json
import re
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
HOOKS = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
WRAPPER = r'bash "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/hook\.sh" '
PRINT_SESSION = "printenv CLAUDE_CODE_SESSION_ID CODEX_SESSION_ID PI_SESSION_ID"


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
        "mcp__codex_apps__github__create_pull_request",
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
    assert fields["allowed-tools"] == f"Bash(pr-tracker list *) Bash({PRINT_SESSION})"
    assert re.search(r"^pr-tracker list --scope session$", body, re.M)
    assert re.search(rf"^{PRINT_SESSION}$", body, re.M)
    assert "prs --session <id>" in body


def test_prs_reads_arguments_where_they_are_not_substituted():
    """Claude Code replaces `$ARGUMENTS`; Codex and Pi leave it, so the skill says where
    the arguments are then. Claude Code replaces every occurrence, so there's only one."""
    _, body = frontmatter("prs")
    assert body.count("$ARGUMENTS") == 1
    assert "whatever the user typed after the skill's name" in body


@pytest.mark.parametrize("skill", ["pr-tracker", "prs"])
def test_skills_leave_the_session_to_the_cli(skill):
    """pr-tracker 1.1.0 reads the session id from the variable each agent exports to its
    shell, so a skill works unchanged in Claude Code, Codex and Pi."""
    _, body = frontmatter(skill)
    commands = re.findall(r"^pr-tracker .+$", body, re.M)
    assert commands
    for command in commands:
        assert "--session" not in command, command
    assert "CLAUDE_SESSION_ID" not in body
    assert not re.search(r"\$\{\w+\}", body)
    assert "1.1.0" in body
    assert "python" not in body
    assert "CLAUDE_PLUGIN_ROOT" not in body


def openai_yaml(skill):
    return PLUGIN / "skills" / skill / "agents" / "openai.yaml"


def test_codex_never_invokes_prs_by_itself():
    """Codex ignores `disable-model-invocation`; its equivalent is the skill's
    agents/openai.yaml. `$pr-tracker:prs` still runs it."""
    assert openai_yaml("prs").read_text() == "policy:\n  allow_implicit_invocation: false\n"
    assert not openai_yaml("pr-tracker").exists()


def test_no_fixed_install_paths():
    for path in PLUGIN.rglob("*"):
        if path.is_file() and "tests" not in path.relative_to(PLUGIN).parts:
            text = path.read_text()
            assert ".agents/" not in text, path
            assert not re.search(r"/(?:Users|home)/(?!linuxbrew/)\w", text), path
