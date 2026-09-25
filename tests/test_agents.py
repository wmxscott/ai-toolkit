"""Pi and OpenCode support: the root package.json and the OpenCode plugin module, checked
against the Claude and Codex manifests and the README table."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"
PACKAGE = json.loads((ROOT / "package.json").read_text())
README = (ROOT / "README.md").read_text()
OPENCODE_MODULE = ".opencode/plugins/ai-toolkit.js"
PI_SKILLS = re.compile(r"\./plugins/([a-z0-9-]+)/skills")


def pi_plugins():
    names = []
    for entry in PACKAGE["pi"]["skills"]:
        match = PI_SKILLS.fullmatch(entry)
        assert match, entry
        names.append(match[1])
    return names


def skills_in(*directories):
    return sorted(
        skill.name
        for directory in directories
        if directory.is_dir()
        for skill in directory.iterdir()
        if (skill / "SKILL.md").is_file()
    )


def manifest_skills(plugin, manifest):
    """The skills an agent loads from a plugin: `skills` in its manifest, else `skills/`."""
    paths = manifest.get("skills", "./skills")
    paths = [paths] if isinstance(paths, str) else paths
    return skills_in(*(plugin / path for path in paths))


def readme_column(plugin, column):
    header = re.search(r"^\| Plugin \|(.*)$", README, re.M)
    name = re.escape(plugin)
    row = re.search(rf"^\| \[{name}\]\(plugins/{name}\) \|(.*)$", README, re.M)
    assert header and row, plugin
    columns = [cell.strip() for cell in header[1].split("|")]
    return [cell.strip() for cell in row[1].split("|")][columns.index(column)]


def test_package_is_private_and_carries_nothing_to_install():
    assert PACKAGE["name"] == "ai-toolkit"
    assert PACKAGE["private"] is True
    assert not {"dependencies", "devDependencies", "peerDependencies", "scripts"} & PACKAGE.keys()


def test_pi_sees_only_the_listed_skills():
    """Pi's docs describe falling back to these conventional directories when the manifest
    has no entry (0.87.1 doesn't), which could pick up a Claude-only plugin's resources.
    Extensions and themes are Pi's own, under `pi/`: see tests/test_pi.py."""
    assert set(PACKAGE["pi"]) == {"skills", "extensions", "themes"}
    names = pi_plugins()
    assert len(names) == len(set(names))
    for directory in ("skills", "extensions", "prompts", "themes"):
        assert not (ROOT / directory).exists(), directory


@pytest.mark.parametrize("name", pi_plugins())
def test_every_agent_loads_the_same_skills(name):
    plugin = PLUGINS / name
    claude = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text())
    codex_manifests = [
        path
        for path in (plugin / "plugin.json", plugin / ".codex-plugin" / "plugin.json")
        if path.is_file()
    ]
    assert codex_manifests, "a Pi or OpenCode plugin must support Codex too"
    codex = json.loads(codex_manifests[0].read_text())
    pi = skills_in(plugin / "skills")
    assert pi
    assert manifest_skills(plugin, claude) == pi
    assert manifest_skills(plugin, codex) == pi


@pytest.mark.parametrize("plugin", sorted(p.name for p in PLUGINS.iterdir() if p.is_dir()))
@pytest.mark.parametrize("column", ["Pi", "OpenCode"])
def test_readme_columns_match_package(plugin, column):
    assert (readme_column(plugin, column) == "✓") == (plugin in pi_plugins())


def test_opencode_module_is_the_package_entry_point():
    assert PACKAGE["main"] == OPENCODE_MODULE
    assert PACKAGE["type"] == "module"
    assert (ROOT / OPENCODE_MODULE).is_file()


def run_module(body):
    """Import the OpenCode module in node, run `body` against it, and parse what it prints."""
    script = (
        f"const {{ default: plugin }} = await import({json.dumps(str(ROOT / OPENCODE_MODULE))});"
        + body
    )
    done = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(done.stdout)


def run_config_hook(config):
    """OpenCode 1: `server` returns hooks, and the config hook edits `skills.paths`."""
    return run_module(
        "const hooks = await plugin.server({});"
        f"const config = {json.dumps(config)};"
        "await hooks.config(config); await hooks.config(config);"
        "console.log(JSON.stringify(config));"
    )


def run_setup():
    """OpenCode 2: `setup` registers skills through `ctx.skill.transform`'s editor."""
    return run_module(
        "const added = []; let transforms = 0;"
        "await plugin.setup({ skill: { transform: async (edit) => {"
        "  transforms++; edit({ add: (skill) => added.push(skill) }); } } });"
        "console.log(JSON.stringify({ added, transforms }));"
    )


def portable_skills():
    for name in pi_plugins():
        for skill in skills_in(PLUGINS / name / "skills"):
            yield PLUGINS / name / "skills" / skill / "SKILL.md"


def test_opencode_module_exports_both_plugin_shapes():
    """OpenCode 1 reads `server` from the default export, OpenCode 2 requires `id` plus
    `setup`. Checked without node, so it holds wherever the suite runs."""
    source = (ROOT / OPENCODE_MODULE).read_text()
    assert 'export default { id: "ai-toolkit", server, setup };' in source
    assert "async function server(" in source and "async function setup(ctx)" in source


needs_node = pytest.mark.skipif(not shutil.which("node"), reason="needs node")


@needs_node
def test_opencode_1_adds_each_skills_directory_once():
    expected = [str(ROOT / "plugins" / name / "skills") for name in pi_plugins()]
    assert run_config_hook({}) == {"skills": {"paths": expected}}
    kept = run_config_hook({"skills": {"paths": ["/elsewhere"]}})
    assert kept["skills"]["paths"] == ["/elsewhere", *expected]


@needs_node
def test_opencode_1_leaves_a_skills_list_alone():
    assert run_config_hook({"skills": []}) == {"skills": []}


@needs_node
def test_opencode_2_setup_adds_every_skill():
    result = run_setup()
    assert result["transforms"] == 1
    expected = []
    for path in portable_skills():
        frontmatter, body = re.match(r"---\n(.*?)\n---\n(.*)", path.read_text(), re.S).groups()
        fields = dict(line.split(": ", 1) for line in frontmatter.splitlines())
        expected.append(
            {
                "id": path.parent.name,
                "name": fields["name"],
                "description": fields["description"],
                "path": str(path),
                "content": body,
            }
        )
    key = lambda skill: skill["id"]  # noqa: E731
    assert sorted(result["added"], key=key) == sorted(expected, key=key)


@needs_node
def test_setup_ignores_an_opencode_1_context():
    """A context without a skill domain must neither throw nor act."""
    assert run_module("await plugin.setup({}); await plugin.setup(undefined); console.log(1);") == 1


@needs_node
def test_opencode_2_skips_a_skill_it_rejects():
    everything = sorted(path.parent.name for path in portable_skills())
    rejected = everything[0]
    result = run_module(
        "const added = [];"
        "await plugin.setup({ skill: { transform: async (edit) => edit({ add: (skill) => {"
        f"  if (skill.id === {json.dumps(rejected)}) throw new Error('rejected');"
        "  added.push(skill.id); } }) } });"
        "console.log(JSON.stringify(added));"
    )
    assert sorted(result) == everything[1:]
