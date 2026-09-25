"""Pi extensions and themes: the files `pi.extensions` and `pi.themes` list in package.json.

`schemas/pi-0.87.1-theme.schema.json` is Pi's theme schema (MIT) from
https://github.com/earendil-works/pi/blob/v0.87.1/packages/coding-agent/src/modes/interactive/theme/theme-schema.json
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
PI_DIR = ROOT / "pi"
PACKAGE = json.loads((ROOT / "package.json").read_text())
EXTENSIONS = PACKAGE["pi"]["extensions"]
THEMES = PACKAGE["pi"]["themes"]
THEME_SCHEMA = json.loads((ROOT / "tests" / "schemas" / "pi-0.87.1-theme.schema.json").read_text())
README = (ROOT / "README.md").read_text()
PI_README = (PI_DIR / "README.md").read_text()

# Pi supplies these to extensions; the package has no dependencies of its own.
PI_SUPPLIED = {
    "@earendil-works/pi-ai",
    "@earendil-works/pi-agent-core",
    "@earendil-works/pi-coding-agent",
    "@earendil-works/pi-tui",
    "typebox",
}
TRIGGER = ".local/share/theme-monitor/theme-change.trigger"


def listed(entries, directory, suffix):
    paths = []
    for entry in entries:
        assert entry.startswith(f"./pi/{directory}/"), entry
        assert entry.endswith(suffix), entry
        paths.append(ROOT / entry)
    return paths


EXTENSION_FILES = listed(EXTENSIONS, "extensions", ".ts")
THEME_FILES = listed(THEMES, "themes", ".json")


def test_package_lists_every_extension_and_theme_once():
    assert sorted(EXTENSION_FILES) == sorted((PI_DIR / "extensions").iterdir())
    assert sorted(THEME_FILES) == sorted((PI_DIR / "themes").iterdir())
    assert len(set(EXTENSIONS)) == len(EXTENSIONS)
    assert len(set(THEMES)) == len(THEMES)
    assert all(path.is_file() for path in EXTENSION_FILES + THEME_FILES)


@pytest.mark.parametrize("path", THEME_FILES, ids=lambda p: p.name)
def test_theme_matches_pi_schema(path):
    theme = json.loads(path.read_text())
    jsonschema.validate(theme, THEME_SCHEMA)
    assert theme["name"] == path.stem
    for value in theme["colors"].values():
        if isinstance(value, str) and value and not value.startswith("#"):
            assert value in theme["vars"], value


def test_themes_define_the_same_colours():
    keys = [set(json.loads(path.read_text())["colors"]) for path in THEME_FILES]
    assert all(k == keys[0] for k in keys)


def test_theme_switcher_names_packaged_themes():
    source = (PI_DIR / "extensions" / "theme-switcher.ts").read_text()
    names = set(re.findall(r'(?:dark|light): "([a-z0-9-]+)"', source))
    assert names == {path.stem for path in THEME_FILES}


@pytest.mark.parametrize("path", EXTENSION_FILES, ids=lambda p: p.name)
def test_extension_imports_only_what_pi_supplies(path):
    source = path.read_text()
    specifiers = re.findall(r'^\s*(?:import|export)\b[^;]*?\bfrom\s+"([^"]+)"', source, re.M | re.S)
    assert specifiers
    for spec in specifiers:
        assert spec.startswith("node:") or spec in PI_SUPPLIED, spec
    assert re.search(r"^export default function\b", source, re.M)


@pytest.mark.parametrize(
    "path",
    sorted(p for p in PI_DIR.rglob("*") if p.suffix in {".ts", ".json", ".md"}),
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_no_personal_paths(path):
    text = path.read_text()
    assert not re.search(r"/(?:Users|home)/[^/\s\"']+", text)
    assert "dotfiles" not in text.lower()


def test_theme_monitor_trigger_is_its_public_default():
    for name in ("statusline.ts", "theme-switcher.ts"):
        source = (PI_DIR / "extensions" / name).read_text()
        assert TRIGGER in source and "homedir()" in source


def test_display_keeps_pix_display_attribution_and_licence():
    source = (PI_DIR / "extensions" / "display.ts").read_text()
    for text in (
        "Adapted from pix-display by xynogen",
        "https://github.com/xynogen/pix-mono/tree/main/packages/pix-display",
        "MIT License",
        "Copyright (c) 2026 xynogen",
        "The above copyright notice and this permission notice shall be included in all",
        'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND',
    ):
        assert text in source, text
    assert "pix-display" in PI_README and "xynogen" in PI_README


def test_readmes_cover_every_extension_and_the_filter():
    for path in EXTENSION_FILES:
        assert f"`{path.name}`" in PI_README, path.name
    assert "theme-monitor" in PI_README
    assert "brew install wmxscott/tap/theme-monitor" in PI_README
    assert "## Pi extensions" in README
    assert '"source": "git:github.com/wmxscott/ai-toolkit"' in README
    assert '"skills": []' in README


STRIP_TYPES = (
    'import { stripTypeScriptTypes } from "node:module";'
    'import { readFileSync } from "node:fs";'
    'process.stdout.write(stripTypeScriptTypes(readFileSync(process.argv[1], "utf8")));'
)


def strip_types(path):
    """Node's own TypeScript parser (22.13 and later) turns `path` into plain JavaScript,
    and throws on a syntax error. `node --check` alone passes a broken .ts module."""
    return subprocess.run(
        ["node", "--no-warnings", "--input-type=module", "-e", STRIP_TYPES, str(path)],
        capture_output=True,
        text=True,
    )


def node_strips_types():
    if not shutil.which("node"):
        return False
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "probe.ts"
        probe.write_text("const x: number = 1;\n")
        return strip_types(probe).stdout.startswith("const x")


@pytest.mark.skipif(not node_strips_types(), reason="needs node 22.13 or later")
@pytest.mark.parametrize("path", EXTENSION_FILES, ids=lambda p: p.name)
def test_extension_parses(path, tmp_path):
    stripped = strip_types(path)
    assert stripped.returncode == 0, stripped.stderr
    module = tmp_path / f"{path.stem}.mjs"
    module.write_text(stripped.stdout)
    checked = subprocess.run(["node", "--check", str(module)], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr


def test_syntax_check_catches_a_broken_extension(tmp_path):
    if not node_strips_types():
        pytest.skip("needs node 22.13 or later")
    broken = tmp_path / "broken.ts"
    broken.write_text('import { a } from "node:fs";\nconst y: { x: number } = { x: 1 ;\n')
    assert strip_types(broken).returncode != 0


def run_pi(tmp_path, package):
    """Load the package with Pi's own loader in a throwaway home, and list its commands."""
    home = tmp_path / "home"
    agent = home / ".pi" / "agent"
    agent.mkdir(parents=True)
    (agent / "settings.json").write_text(json.dumps({"packages": [package]}))
    (home / "gitconfig").touch()
    work = tmp_path / "work"
    work.mkdir()
    env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "TERM": "dumb",
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "GIT_CONFIG_GLOBAL": str(home / "gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "PI_CODING_AGENT_DIR": str(agent),
        "PI_CODING_AGENT_SESSION_DIR": str(home / "sessions"),
        "PI_OFFLINE": "1",
        "PI_SKIP_VERSION_CHECK": "1",
        "PI_TELEMETRY": "0",
    }
    if subprocess.run(["pi", "--version"], capture_output=True, env=env).returncode != 0:
        pytest.skip("pi does not run in an isolated home")
    done = subprocess.run(
        ["pi", "--mode", "rpc", "--no-session"],
        input='{"id":"1","type":"get_commands"}\n',
        capture_output=True,
        text=True,
        cwd=work,
        env=env,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    response = next(
        record
        for record in map(json.loads, done.stdout.splitlines())
        if record.get("command") == "get_commands"
    )
    assert response["success"], response
    return {
        command["name"]: command["sourceInfo"]["path"]
        for command in response["data"]["commands"]
        if command["sourceInfo"].get("origin") == "package"
    }


needs_pi = pytest.mark.skipif(not shutil.which("pi"), reason="needs the pi CLI")


@needs_pi
def test_pi_loads_the_whole_package(tmp_path):
    commands = run_pi(tmp_path, str(ROOT))
    assert commands["statusline"] == str(PI_DIR / "extensions" / "statusline.ts")
    assert any(name.startswith("skill:") for name in commands)


@needs_pi
def test_pi_filter_drops_the_skills(tmp_path):
    commands = run_pi(tmp_path, {"source": str(ROOT), "skills": []})
    assert set(commands) == {"statusline"}
