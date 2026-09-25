"""Packaging: manifests, experimental marking, bundled data and the launcher."""

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import arbiter
import pytest

PLUGIN = Path(__file__).resolve().parent.parent
ROOT = PLUGIN.parent.parent
MANIFEST = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
MARKETPLACE = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
README = (PLUGIN / "README.md").read_text()
LAUNCHER = PLUGIN / "bin" / "arbiter"


def test_every_description_is_marked_experimental():
    [entry] = [p for p in MARKETPLACE["plugins"] if p["name"] == "arbiter"]
    assert entry["description"].startswith("EXPERIMENTAL:")
    assert MANIFEST["description"].startswith("EXPERIMENTAL:")
    assert entry["description"] == MANIFEST["description"]
    assert "experimental" in MANIFEST["keywords"]


def test_readme_opens_with_the_warning():
    head = README.split("\n## ", 1)[0]
    assert head.startswith("# arbiter\n\n> [!WARNING]\n")
    for phrase in ("Highly experimental", "not on `main`", "may never ship"):
        assert phrase in head
    assert "hold Claude's turn open" in head
    assert "spend model calls" in head


def test_root_readme_explains_the_branch():
    text = (ROOT / "README.md").read_text()
    assert "This is the `experimental/arbiter` branch, not `main`." in text


def test_not_a_codex_pi_or_opencode_plugin():
    assert not (PLUGIN / "plugin.json").exists()
    assert not (PLUGIN / "skills").exists()
    codex = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
    assert "arbiter" not in {p["name"] for p in codex["plugins"]}


def test_verdict_style_is_not_a_menu_output_style():
    assert not (PLUGIN / "output-styles").exists()
    assert "outputStyles" not in MANIFEST
    assert (PLUGIN / "config" / "output-styles" / "verdict.md").is_file()


def test_builtin_data_is_well_formed():
    config = PLUGIN / "config"
    defaults = tomllib.loads((config / "defaults.toml").read_text())
    assert all(task["enabled"] is False for task in defaults["task"])
    for template in (config / "templates").glob("*.toml"):
        tomllib.loads(template.read_text())
    schema = json.loads((config / "schema" / "verdict.schema.json").read_text())
    assert schema["required"] == ["ok", "summary", "findings"]
    assert sorted(p.stem for p in (config / "judges").glob("*.md")) == [
        "scalability-reviewer",
        "security-reviewer",
    ]


def test_launcher_is_executable_bash():
    assert os.access(LAUNCHER, os.X_OK)
    assert LAUNCHER.read_text().startswith("#!/bin/bash\n")


def test_launcher_passes_shellcheck():
    shellcheck = shutil.which("shellcheck")
    if not shellcheck:
        pytest.skip("shellcheck not installed")
    subprocess.run([shellcheck, str(LAUNCHER)], check=True)


def test_launcher_runs_under_bash_3_2_syntax():
    text = LAUNCHER.read_text()
    for feature in ("mapfile", "readarray", "declare -A", "${!", ";&", "|&", "&>>"):
        assert feature not in text, feature


def test_cli_version_through_the_launcher(tmp_path):
    env = {
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "ARBITER_PYTHON": sys.executable,
        "ARBITER_FALLBACK_PATH": "",
    }
    result = subprocess.run(
        ["bash", str(LAUNCHER), "--version"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == f"arbiter {arbiter.__version__}\n"


def test_no_personal_paths_or_stale_references():
    for path in PLUGIN.rglob("*"):
        parts = path.relative_to(PLUGIN).parts
        if not path.is_file() or "__pycache__" in parts or parts[0] == "tests":
            continue
        text = path.read_text()
        assert not re.search(r"/(?:Users|home)/(?!linuxbrew/)\w", text), path
        for stale in ("stow", "dotfiles", "superpowers"):
            assert stale not in text, (path, stale)
