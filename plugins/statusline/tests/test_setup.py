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
COMMAND = 'python3 "$HOME/.claude/plugins/data/statusline-ai-toolkit/statusline.py"'
EXPECTED = {"type": "command", "command": COMMAND, "padding": 0, "refreshInterval": 1}


class Env:
    def __init__(self, home: Path):
        self.home = home
        self.claude = home / ".claude"
        self.settings = self.claude / "settings.json"
        self.data = self.claude / "plugins" / "data" / "statusline-ai-toolkit"
        self.env = {"HOME": str(home), "PATH": os.environ["PATH"]}

    def run(self, *args, data=None, script=SETUP):
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


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return Env(home)


def test_fresh_install_creates_settings_and_link(env):
    result = env.run()
    assert result.returncode == 0, result.stderr
    assert env.read() == {"statusLine": EXPECTED}
    link = env.data / "statusline.py"
    assert os.readlink(link) == str(PLUGIN / "scripts" / "statusline.py")
    assert "New statusLine" in result.stdout
    assert json.dumps(COMMAND) in result.stdout


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
    assert written == f'python3 "{data}/statusline.py"'


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
        ["sh", "-c", command],
        input='{"model": {"display_name": "Claude Opus 4.7"}}',
        env={**env.env, "CLAUDE_STATUSLINE_THEME": "dark"},
        cwd=env.home,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "Opus 4.7" in result.stdout


def test_rerun_after_an_update_keeps_the_same_command(env, tmp_path):
    assert env.run().returncode == 0
    before = env.settings.read_bytes()
    new_root = tmp_path / "v2"
    shutil.copytree(PLUGIN / "scripts", new_root / "scripts")
    result = env.run(script=new_root / "scripts" / "setup_statusline.py")
    assert result.returncode == 0, result.stderr
    assert "Nothing changed" in result.stdout
    assert env.settings.read_bytes() == before
    assert os.readlink(env.data / "statusline.py") == str(new_root / "scripts" / "statusline.py")


@pytest.fixture
def setup_module(monkeypatch):
    spec = importlib.util.spec_from_file_location("setup_statusline", SETUP)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "setup_statusline", module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("home", "script", "expected"),
    [
        ("/h", "/h/.claude/x/statusline.py", 'python3 "$HOME/.claude/x/statusline.py"'),
        ("/h", "/other/statusline.py", 'python3 "/other/statusline.py"'),
        ("/h", "/hx/statusline.py", 'python3 "/hx/statusline.py"'),
        ("/h", '/h/a "b" $c `d`/s.py', 'python3 "$HOME/a \\"b\\" \\$c \\`d\\`/s.py"'),
    ],
)
def test_shell_command(setup_module, monkeypatch, home, script, expected):
    monkeypatch.setenv("HOME", home)
    assert setup_module.shell_command(script) == expected


def test_shell_command_survives_the_shell(setup_module, monkeypatch, tmp_path):
    home = tmp_path / 'my "home" $dir'
    script = home / "sub `x`" / "print.py"
    script.parent.mkdir(parents=True)
    script.write_text("import sys; print(sys.argv[0])\n")
    monkeypatch.setenv("HOME", str(home))
    command = setup_module.shell_command(str(script))
    out = subprocess.run(
        ["sh", "-c", command],
        env={"HOME": str(home), "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.strip() == str(script)
