import json
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
STYLE = (PLUGIN / "output-styles" / "chat.md").read_text()
README = (PLUGIN / "README.md").read_text()


def frontmatter(text):
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match
    return dict(line.split(": ", 1) for line in match[1].splitlines())


def test_ships_one_output_style_from_the_default_directory():
    assert "outputStyles" not in MANIFEST
    assert sorted(p.name for p in (PLUGIN / "output-styles").iterdir()) == ["chat.md"]


def test_ships_nothing_else():
    shipped = {p.name for p in PLUGIN.iterdir()}
    assert shipped == {".claude-plugin", "output-styles", "README.md", "tests"}


def test_frontmatter():
    meta = frontmatter(STYLE)
    assert meta.keys() == {"name", "description"}
    assert meta["name"] == "Chat"
    assert meta["description"]


def test_style_is_opt_in():
    assert "force-for-plugin" not in STYLE


def test_readme_gives_the_exact_selection_value():
    # Claude Code names a plugin output style "<plugin>:<style name>".
    value = f"{MANIFEST['name']}:{frontmatter(STYLE)['name']}"
    assert value == "chat-style:Chat"
    assert f'"outputStyle": "{value}"' in README
    assert f"/output-style {value}" in README
