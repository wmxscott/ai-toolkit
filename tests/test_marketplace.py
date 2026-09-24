import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
ENTRIES = MARKETPLACE["plugins"]
PLUGINS = ROOT / "plugins"
PLUGIN_DIRS = sorted(p for p in PLUGINS.iterdir() if p.is_dir()) if PLUGINS.is_dir() else []
README = (ROOT / "README.md").read_text()


def manifest(entry):
    return json.loads((ROOT / entry["source"] / ".claude-plugin" / "plugin.json").read_text())


def all_keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from all_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from all_keys(item)


def test_marketplace_identity():
    assert MARKETPLACE["name"] == "ai-toolkit"
    assert MARKETPLACE["owner"] == {"name": "wmxscott"}


def test_every_plugin_dir_is_listed():
    sources = {entry["source"] for entry in ENTRIES}
    assert {f"./plugins/{p.name}" for p in PLUGIN_DIRS} == sources


def test_entry_names_are_unique():
    names = [entry["name"] for entry in ENTRIES]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["name"])
def test_entry_matches_plugin(entry):
    assert entry["source"] == f"./plugins/{entry['name']}"
    plugin = manifest(entry)
    assert plugin["name"] == entry["name"]
    assert plugin["author"] == {"name": "wmxscott"}
    assert plugin["license"] == "MIT"
    assert plugin["repository"] == "https://github.com/wmxscott/ai-toolkit"
    assert "version" not in entry, "set version in plugin.json only"


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["name"])
def test_plugin_has_readme_row_docs_and_tests(entry):
    name = entry["name"]
    assert re.search(rf"^\| \[{re.escape(name)}\]\(plugins/{re.escape(name)}\) \|", README, re.M)
    assert (ROOT / "plugins" / name / "README.md").is_file()
    assert list((ROOT / "plugins" / name / "tests").glob("test_*.py"))


def test_marketplace_carries_no_email():
    assert "email" not in set(all_keys(MARKETPLACE))


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["name"])
def test_plugin_manifest_carries_no_email(entry):
    assert "email" not in set(all_keys(manifest(entry)))


def test_shell_scripts_are_executable():
    for script in PLUGINS.rglob("*.sh"):
        assert os.access(script, os.X_OK), script
