import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"
MARKETPLACE = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
ENTRIES = MARKETPLACE["plugins"]
SCHEMA = json.loads(
    (ROOT / "tests" / "schemas" / "agent-plugins-1.0.0-plugin.schema.json").read_text()
)
README = (ROOT / "README.md").read_text()

# Shared fields must say the same thing in the Claude and Codex manifests.
SHARED_FIELDS = (
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
)
# From the enums in `codex app-server generate-json-schema`.
INSTALL_POLICIES = {"AVAILABLE", "INSTALLED_BY_DEFAULT", "NOT_AVAILABLE"}
AUTH_POLICIES = {"ON_INSTALL", "ON_USE"}
INTERFACE_STRINGS = {
    "displayName",
    "shortDescription",
    "longDescription",
    "developerName",
    "category",
    "websiteURL",
    "privacyPolicyURL",
    "termsOfServiceURL",
    "brandColor",
}
INTERFACE_LISTS = {"capabilities", "defaultPrompt"}


def codex_plugins():
    return sorted(p.parent.name for p in PLUGINS.glob("*/plugin.json"))


def codex_manifest(name):
    return json.loads((PLUGINS / name / "plugin.json").read_text())


def claude_manifest(name):
    return json.loads((PLUGINS / name / ".claude-plugin" / "plugin.json").read_text())


def readme_row(name):
    row = re.search(
        rf"^\| \[{re.escape(name)}\]\(plugins/{re.escape(name)}\) \|(.*)$", README, re.M
    )
    assert row, name
    return [cell.strip() for cell in row[1].split("|")]


def test_marketplace_identity():
    assert MARKETPLACE["name"] == "ai-toolkit"
    assert MARKETPLACE["interface"]["displayName"]
    assert "email" not in json.dumps(MARKETPLACE)


def test_every_codex_plugin_is_listed():
    names = [entry["name"] for entry in ENTRIES]
    assert len(names) == len(set(names))
    assert set(names) == set(codex_plugins())


def test_only_the_portable_manifest_is_used():
    assert not list(PLUGINS.glob("*/.codex-plugin")), "use plugins/<name>/plugin.json"


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["name"])
def test_entry_shape(entry):
    assert set(entry) == {"name", "source", "policy", "category"}
    assert entry["source"] == {"source": "local", "path": f"./plugins/{entry['name']}"}
    assert entry["policy"]["installation"] in INSTALL_POLICIES
    assert entry["policy"]["authentication"] in AUTH_POLICIES
    assert isinstance(entry["category"], str) and entry["category"]


@pytest.mark.parametrize("name", codex_plugins())
def test_manifest_matches_agent_plugins_schema(name):
    errors = [e.message for e in Draft202012Validator(SCHEMA).iter_errors(codex_manifest(name))]
    assert not errors


@pytest.mark.parametrize("name", codex_plugins())
def test_manifest_agrees_with_claude_manifest(name):
    codex, claude = codex_manifest(name), claude_manifest(name)
    for field in SHARED_FIELDS:
        assert codex.get(field) == claude.get(field), field


@pytest.mark.parametrize("name", codex_plugins())
def test_openai_extension(name):
    extensions = codex_manifest(name).get("extensions", {})
    assert set(extensions) <= {"com.openai"}
    openai = extensions.get("com.openai", {})
    assert set(openai) <= {"interface", "hooks", "apps"}
    interface = openai.get("interface", {})
    assert set(interface) <= INTERFACE_STRINGS | INTERFACE_LISTS | {
        "composerIcon",
        "logo",
        "logoDark",
        "screenshots",
    }
    for key in INTERFACE_STRINGS & interface.keys():
        assert isinstance(interface[key], str) and interface[key], key
    for key in INTERFACE_LISTS & interface.keys():
        assert all(isinstance(item, str) for item in interface[key]), key
    for key in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL"):
        if key in interface:
            assert urlparse(interface[key]).scheme == "https", key
    for key in ("composerIcon", "logo", "logoDark"):
        if key in interface:
            assert (PLUGINS / name / interface[key]).is_file(), key
    if "developerName" in interface:
        assert interface["developerName"] == "wmxscott"


@pytest.mark.parametrize("name", codex_plugins())
def test_skills_are_discoverable(name):
    skills = PLUGINS / name / "skills"
    for skill in skills.iterdir() if skills.is_dir() else []:
        text = (skill / "SKILL.md").read_text()
        assert re.match(rf"---\nname: {re.escape(skill.name)}\ndescription: \S", text), skill


@pytest.mark.parametrize("plugin", sorted(p.name for p in PLUGINS.iterdir() if p.is_dir()))
def test_readme_codex_column_matches_manifest(plugin):
    header = re.search(r"^\| Plugin \|(.*)$", README, re.M)
    assert header
    columns = [cell.strip() for cell in header[1].split("|")]
    codex = readme_row(plugin)[columns.index("Codex")]
    assert (codex == "✓") == (plugin in codex_plugins())
