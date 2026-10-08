import json
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
CLAUDE = shutil.which("claude")


def test_hooks_load_the_module():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    assert hooks == {"modules": ["./register.tsx"]}
    assert (PLUGIN / "hooks" / "register.tsx").is_file()


def test_module_source_is_ascii():
    # The flag icon is spelled  so the private-use character never lands in the file.
    for path in (PLUGIN / "hooks").glob("*.tsx"):
        assert path.read_text().isascii(), path


def test_overview_command_takes_arguments():
    command = (PLUGIN / "commands" / "overview.md").read_text()
    assert command.startswith("---\ndescription: ")
    assert "$ARGUMENTS" in command
    assert "/overview" in (PLUGIN / "README.md").read_text()


@pytest.mark.skipif(not CLAUDE, reason="claude CLI not installed")
def test_module_tests_pass():
    result = subprocess.run([CLAUDE, "plugin", "test", str(PLUGIN)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert " 0 fail" in result.stdout + result.stderr
