"""The skills as every agent sees them: plain Agent Skills whose bundled files are found
relative to the skill's own directory, never through an agent-specific variable."""

import ast
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from census_support import SCRIPTS, diff_census

PLUGIN = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN / "skills"
NAMES = sorted(p.name for p in SKILLS.iterdir() if (p / "SKILL.md").is_file())

# Where each skill says `<scripts>` lives, relative to its own directory.
SCRIPTS_DIR = {
    "authoring-stacked-plans": "scripts",
    "implementing-stacked-plans": "../authoring-stacked-plans/scripts",
}


def text(name):
    return (SKILLS / name / "SKILL.md").read_text()


def frontmatter(name):
    match = re.match(r"---\n(.*?)\n---\n", text(name), re.S)
    assert match, name
    return dict(line.split(": ", 1) for line in match[1].splitlines())


def test_the_four_skills():
    assert NAMES == [
        "authoring-stacked-plans",
        "implementing-stacked-plans",
        "landing-changes",
        "stacked-planning",
    ]


@pytest.mark.parametrize("name", NAMES)
def test_frontmatter_is_portable(name):
    """The Agent Skills rules Pi and OpenCode enforce, and YAML every parser accepts: a plain
    scalar containing `: ` is a syntax error to a strict parser, which drops the skill."""
    fields = frontmatter(name)
    assert fields.keys() == {"name", "description"}
    assert fields["name"] == name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64
    description = fields["description"]
    assert description.startswith("Use ")
    assert len(description) <= 1024
    assert ": " not in description and " #" not in description
    assert description[0] not in "\"'[{>|*&!%@`"


@pytest.mark.parametrize("name", NAMES)
def test_no_agent_specific_paths(name):
    body = text(name)
    for token in ("~/.claude", "CLAUDE_PLUGIN_ROOT", "CLAUDE_SKILL_DIR", "$HOME", "~/"):
        assert token not in body, token


@pytest.mark.parametrize("name", NAMES)
def test_script_references_resolve(name):
    body = text(name)
    references = set(re.findall(r"<scripts>/([\w.]+)", body))
    if name not in SCRIPTS_DIR:
        assert not references, name
        return
    assert f"`{SCRIPTS_DIR[name]}" in body, "the skill must say where <scripts> is"
    assert references
    scripts = (SKILLS / name / SCRIPTS_DIR[name]).resolve()
    assert scripts == SCRIPTS
    for reference in references:
        assert (scripts / reference).is_file(), reference


def test_template_is_bundled():
    assert "`template.md`" in text("authoring-stacked-plans")
    assert (SKILLS / "authoring-stacked-plans" / "template.md").is_file()


def test_scripts_are_executable_with_a_shebang():
    for script in SCRIPTS.glob("*.py"):
        assert os.access(script, os.X_OK), script
        assert script.read_text().startswith("#!/usr/bin/env "), script


def test_diff_census_declares_its_dependencies():
    header = re.search(
        r"^# /// script\n(.*?)^# ///$", (SCRIPTS / "diff_census.py").read_text(), re.S | re.M
    )
    assert header
    assert 'dependencies = ["pathspec", "pygments"]' in header[1]


def test_stack_overlap_still_parses_as_python_3_8():
    ast.parse((SCRIPTS / "stack_overlap.py").read_text(), feature_version=(3, 8))


# ---------------------------------------------------------------------------
# The example configuration
# ---------------------------------------------------------------------------

EXAMPLE = SCRIPTS / "config.example.toml"


def test_example_config_loads_clean():
    config = diff_census.load_config(str(EXAMPLE))
    assert not config.warnings
    assert config.groups["production"].limit.metrics == {"changed": 400}
    assert config.limits["total"].metrics == {"changed": 1200}


@pytest.mark.parametrize(
    ("path", "bucket"),
    [
        ("src/app.py", "production"),
        ("tests/test_app.py", "tests"),
        ("docs/plans/abc123-thing.md", "plan"),
        ("service/docs/plans/abc123-thing.md", "plan"),
        ("README.md", "exempt"),
        ("docs/guide.md", "exempt"),
        ("notes/design.md", "exempt"),
        ("uv.lock", "exempt"),
        ("dist/app.js", "exempt"),
    ],
)
def test_example_config_buckets(path, bucket, repo, gate):
    repo.write(path, "x = 1\n")
    repo.commit()
    code, out = gate("--base", "HEAD~1", "--config", str(EXAMPLE), "--format", "json")
    assert code == 0, out.err
    report = json.loads(out.out)
    if bucket == "exempt":
        assert report["totals"]["exempt"]["changed"] == 1
        assert report["totals"]["total"]["changed"] == 0
    elif bucket == "production":
        assert report["groups"]["production"]["changed"] == 1
    else:
        assert report["matchers"][bucket]["changed"] == 1
        assert report["groups"]["production"]["changed"] == 0


# ---------------------------------------------------------------------------
# The commands exactly as the skills give them
# ---------------------------------------------------------------------------


def commands(name, program):
    found = []
    for block in re.findall(r"^```sh\n(.*?)^```$", text(name), re.S | re.M):
        joined = block.replace("\\\n", " ")
        found += [line.split("#")[0].strip() for line in joined.splitlines() if program in line]
    assert found, (name, program)
    return found


def expand(command):
    return command.replace("<scripts>", str(SCRIPTS))


@pytest.mark.skipif(not shutil.which("uv"), reason="needs uv")
@pytest.mark.parametrize("command", commands("authoring-stacked-plans", "diff_census.py"))
def test_documented_size_gate_runs(command, repo):
    repo.write("src/app.py", "x = 1\n")
    repo.commit()
    repo.git("branch", "parent", "HEAD~1")
    argv = expand(command).replace("origin/<parent>", "parent").split()
    done = subprocess.run(
        [*argv, "--config", str(EXAMPLE)], cwd=repo.root, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    assert "production" in done.stdout


@pytest.mark.parametrize("command", commands("authoring-stacked-plans", "stack_overlap.py"))
def test_documented_overlap_gate_runs(command, stacks):
    stacks.git("checkout", "-q", "stack-a-clean")
    argv = expand(command).replace("origin/<base>", "main")
    argv = argv.replace("docs/plans/<this plan>", "docs/plans/2026-01-01-two-stacks.md").split()
    done = subprocess.run(argv, cwd=stacks.root, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
