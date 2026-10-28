import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
SETUP = PLUGIN / "scripts" / "setup_statusline.py"
COMMAND = '"$HOME/.claude/plugins/data/statusline-ai-toolkit/statusline"'
EXPECTED = {"type": "command", "command": COMMAND, "padding": 0, "refreshInterval": 15}
OLD = 'python3 "$HOME/.claude/plugins/data/statusline-ai-toolkit/statusline.py"'


class Env:
    def __init__(self, home: Path, release):
        self.home = home
        self.release = release
        self.claude = home / ".claude"
        self.settings = self.claude / "settings.json"
        self.data = self.claude / "plugins" / "data" / "statusline-ai-toolkit"
        self.env = {"HOME": str(home), "PATH": str(release.tools)}

    def run(self, *args, data=None):
        script = self.release.root / "scripts" / "setup_statusline.py"
        return subprocess.run(
            [sys.executable, str(script), str(data or self.data), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def write(self, obj, path=None):
        path = path or self.settings
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, indent=2) + "\n")

    def read(self, path=None):
        return json.loads((path or self.settings).read_text())

    def binary(self, version="2.0.0"):
        return self.data / "bin" / f"statusline-{version}-darwin-arm64"


@pytest.fixture
def env(tmp_path, release):
    home = tmp_path / "home"
    home.mkdir()
    return Env(home, release)


def test_fresh_install_downloads_and_creates_settings(env):
    result = env.run()
    assert result.returncode == 0, result.stderr
    assert env.read() == {"statusLine": EXPECTED}
    assert os.readlink(env.data / "statusline") == str(env.binary())
    assert "New statusLine" in result.stdout
    assert json.dumps(COMMAND) in result.stdout
    assert "once the download completes" not in result.stdout


def test_writes_settings_even_when_the_download_fails(env):
    shutil.rmtree(env.release.serve)
    result = env.run()
    assert result.returncode == 0, result.stderr
    assert env.read() == {"statusLine": EXPECTED}
    assert not os.path.lexists(env.data / "statusline")
    assert "once the download completes" in result.stdout


def test_keeps_every_other_key_in_order(env):
    original = {
        "model": "opus",
        "env": {"FOO": "bar"},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "true"}]}]},
        "permissions": {"allow": ["Bash(ls *)"]},
        "note": "café ✓",
    }
    env.write(original)
    assert env.run().returncode == 0
    updated = env.read()
    assert list(updated) == [*original, "statusLine"]
    assert {k: v for k, v in updated.items() if k != "statusLine"} == original
    assert "café ✓" in env.settings.read_text(encoding="utf-8")


def test_writes_through_a_symlinked_settings_file(env, tmp_path):
    real = tmp_path / "dotfiles" / "claude" / "settings.json"
    env.write({"model": "opus"}, real)
    env.claude.mkdir(parents=True)
    env.settings.symlink_to(real)
    result = env.run()
    assert result.returncode == 0, result.stderr
    assert env.settings.is_symlink()
    assert env.settings.resolve() == real.resolve()
    assert env.read(real) == {"model": "opus", "statusLine": EXPECTED}
    assert "through the symlink" in result.stdout
    assert not [p for p in real.parent.iterdir() if p.name != "settings.json"]


def test_writes_through_a_chain_of_symlinks(env, tmp_path):
    real = tmp_path / "real.json"
    env.write({}, real)
    middle = tmp_path / "middle.json"
    middle.symlink_to(real)
    env.claude.mkdir(parents=True)
    env.settings.symlink_to(middle)
    assert env.run().returncode == 0
    assert env.settings.is_symlink() and middle.is_symlink()
    assert env.read(real) == {"statusLine": EXPECTED}


def test_asks_before_replacing_a_different_statusline(env):
    theirs = {"type": "command", "command": "~/.claude/statusline.sh", "padding": 2}
    env.write({"model": "opus", "statusLine": theirs})
    before = env.settings.read_bytes()
    result = env.run()
    assert result.returncode == 3
    assert env.settings.read_bytes() == before
    assert "~/.claude/statusline.sh" in result.stdout
    assert json.dumps(COMMAND) in result.stdout
    assert "--force" in result.stdout


def test_force_replaces_it_and_keeps_extra_statusline_keys(env):
    theirs = {"type": "command", "command": "other", "padding": 2, "hideVimModeIndicator": True}
    env.write({"model": "opus", "statusLine": theirs})
    result = env.run("--force")
    assert result.returncode == 0, result.stderr
    assert env.read() == {
        "model": "opus",
        "statusLine": {**EXPECTED, "hideVimModeIndicator": True},
    }
    assert "Old statusLine" in result.stdout


def old_setup(env, command):
    env.data.mkdir(parents=True)
    (env.data / "statusline.py").symlink_to("/old/install/scripts/statusline.py")
    block = {"type": "command", "command": command, "padding": 0, "refreshInterval": 1}
    env.write({"model": "opus", "statusLine": {**block, "hideVimModeIndicator": True}})


@pytest.mark.parametrize("absolute", [False, True])
def test_replaces_the_old_python_setup_without_asking(env, absolute):
    command = f'python3 "{env.data}/statusline.py"' if absolute else OLD
    old_setup(env, command)
    result = env.run()
    assert result.returncode == 0, result.stderr
    assert env.read() == {
        "model": "opus",
        "statusLine": {**EXPECTED, "hideVimModeIndicator": True},
    }
    assert not os.path.lexists(env.data / "statusline.py")
    assert os.readlink(env.data / "statusline") == str(env.binary())
    assert "Old statusLine" in result.stdout
    assert "systemMessage" not in result.stdout


def test_keeps_an_old_statusline_py_that_is_not_a_link(env):
    old_setup(env, OLD)
    (env.data / "statusline.py").unlink()
    (env.data / "statusline.py").write_text("mine")
    assert env.run().returncode == 0
    assert (env.data / "statusline.py").read_text() == "mine"


@pytest.mark.parametrize(
    "command",
    [
        'python3 "/elsewhere/statusline.py"',
        f"{OLD} --theme dark",
        'python3 "$HOME/.claude/plugins/data/other-ai-toolkit/statusline.py"',
    ],
)
def test_asks_before_replacing_a_lookalike_command(env, command):
    old_setup(env, command)
    assert env.run().returncode == 3
    assert os.path.islink(env.data / "statusline.py")


def test_same_command_with_other_options_still_asks(env):
    env.write({"statusLine": {**EXPECTED, "padding": 2}})
    assert env.run().returncode == 3


def test_already_set_changes_nothing(env):
    env.write({"statusLine": {**EXPECTED, "hideVimModeIndicator": True}})
    before = env.settings.stat().st_mtime_ns
    result = env.run()
    assert result.returncode == 0
    assert "Nothing changed" in result.stdout
    assert env.settings.stat().st_mtime_ns == before


@pytest.mark.parametrize("content", ["", "  \n"])
def test_empty_settings_file(env, content):
    env.claude.mkdir()
    env.settings.write_text(content)
    assert env.run().returncode == 0
    assert env.read() == {"statusLine": EXPECTED}


@pytest.mark.parametrize("content", ["{not json", "[]"])
def test_refuses_to_touch_unparseable_settings(env, content):
    env.claude.mkdir()
    env.settings.write_text(content)
    result = env.run()
    assert result.returncode == 1
    assert "error:" in result.stderr
    assert env.settings.read_text() == content


def test_keeps_file_permissions(env):
    env.write({})
    env.settings.chmod(0o600)
    assert env.run().returncode == 0
    assert stat.S_IMODE(env.settings.stat().st_mode) == 0o600


def test_honours_claude_config_dir(env, tmp_path):
    config = tmp_path / "config"
    env.env["CLAUDE_CONFIG_DIR"] = str(config)
    data = config / "plugins" / "data" / "statusline-ai-toolkit"
    assert env.run(data=data).returncode == 0
    assert not env.settings.exists()
    written = env.read(config / "settings.json")["statusLine"]["command"]
    assert written == f'"{data}/statusline"'
    assert os.path.isfile(data / "statusline")


def test_settings_flag(env, tmp_path):
    target = tmp_path / "elsewhere" / "settings.json"
    assert env.run("--settings", str(target)).returncode == 0
    assert env.read(target) == {"statusLine": EXPECTED}


def test_rejects_a_relative_data_dir(env):
    result = env.run(data="relative/dir")
    assert result.returncode == 1
    assert not env.settings.exists()


def test_configured_command_runs_the_statusline(env):
    assert env.run().returncode == 0
    command = env.read()["statusLine"]["command"]
    result = subprocess.run(
        ["/bin/sh", "-c", command],
        input='{"model": {"display_name": "Claude Opus 4.7"}}',
        env=env.env,
        cwd=env.home,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "statusline 2.0.0 darwin-arm64\n"


def test_rerun_after_an_update_keeps_the_same_command(env):
    assert env.run().returncode == 0
    before = env.settings.read_bytes()
    env.release.publish("2.1.0")
    result = env.run()
    assert result.returncode == 0, result.stderr
    assert "Nothing changed" in result.stdout
    assert env.settings.read_bytes() == before
    assert os.readlink(env.data / "statusline") == str(env.binary("2.1.0"))
    assert not env.binary().exists()


@pytest.fixture
def setup_module(monkeypatch):
    spec = importlib.util.spec_from_file_location("setup_statusline", SETUP)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "setup_statusline", module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("home", "path", "expected"),
    [
        ("/h", "/h/.claude/x/statusline", '"$HOME/.claude/x/statusline"'),
        ("/h", "/other/statusline", '"/other/statusline"'),
        ("/h", "/hx/statusline", '"/hx/statusline"'),
        ("/h", '/h/a "b" $c `d`/s', '"$HOME/a \\"b\\" \\$c \\`d\\`/s"'),
    ],
)
def test_shell_command(setup_module, monkeypatch, home, path, expected):
    monkeypatch.setenv("HOME", home)
    assert setup_module.shell_command(path) == expected


def test_shell_command_survives_the_shell(setup_module, monkeypatch, tmp_path):
    home = tmp_path / 'my "home" $dir'
    program = home / "sub `x`" / "print"
    program.parent.mkdir(parents=True)
    program.write_text('#!/bin/sh\necho "$0"\n')
    program.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    command = setup_module.shell_command(str(program))
    out = subprocess.run(
        ["/bin/sh", "-c", command],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.strip() == str(program)


@pytest.mark.parametrize(
    ("command", "ours"),
    [
        (OLD, True),
        ('python3 "/Users/x/.claude/plugins/data/statusline-ai-toolkit/statusline.py"', True),
        ('python3 "$HOME/my \\"dir\\"/statusline-ai-toolkit/statusline.py"', True),
        ('python3 "/elsewhere/statusline.py"', False),
        (f"{OLD}; rm -rf ~", False),
        ('"$HOME/.claude/plugins/data/statusline-ai-toolkit/statusline"', False),
        (None, False),
    ],
)
def test_is_old_command(setup_module, command, ours):
    block = {"type": "command", "command": command}
    assert setup_module.is_old_setup(block) is ours
