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
    """With no manifest entry for them, Pi would fall back to these conventional directories
    and could pick up a Claude-only plugin's resources."""
    assert set(PACKAGE["pi"]) == {"skills"}
    names = pi_plugins()
    assert len(names) == len(set(names))
    for directory in ("skills", "extensions", "prompts", "themes"):
        assert not (ROOT / directory).exists(), directory


@pytest.mark.parametrize("name", pi_plugins())
def test_every_agent_loads_the_same_skills(name):
    plugin = PLUGINS / name
    claude = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text())
    codex_manifest = plugin / "plugin.json"
    assert codex_manifest.is_file(), "a Pi or OpenCode plugin must support Codex too"
    codex = json.loads(codex_manifest.read_text())
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


def run_config_hook(config):
    script = (
        f"const {{ default: plugin }} = await import({json.dumps(str(ROOT / OPENCODE_MODULE))});"
        "const hooks = await plugin.server({});"
        f"const config = {json.dumps(config)};"
        "await hooks.config(config); await hooks.config(config);"
        "console.log(JSON.stringify(config));"
    )
    done = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(done.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_opencode_module_adds_each_skills_directory_once():
    expected = [str(ROOT / "plugins" / name / "skills") for name in pi_plugins()]
    assert run_config_hook({}) == {"skills": {"paths": expected}}
    kept = run_config_hook({"skills": {"paths": ["/elsewhere"]}})
    assert kept["skills"]["paths"] == ["/elsewhere", *expected]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_opencode_module_leaves_a_skills_list_alone():
    assert run_config_hook({"skills": []}) == {"skills": []}
