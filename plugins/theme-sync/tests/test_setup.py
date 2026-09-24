import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SETUP = Path(__file__).resolve().parent.parent / "scripts" / "setup_theme_sync.py"
THEME = "custom:theme-sync"
INSTALL = "brew install wmxscott/tap/theme-monitor && brew services start theme-monitor"
macos = pytest.mark.skipif(sys.platform != "darwin", reason="setup refuses to run off macOS")


@pytest.fixture(autouse=True)
def theme_monitor(sandbox):
    sandbox.set_trigger("light")


def run(sandbox, *args, data=None, **extra):
    return subprocess.run(
        [sys.executable, str(SETUP), str(data or sandbox.data), *args],
        env={**sandbox.env, **extra},
        capture_output=True,
        text=True,
        timeout=20,
    )


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")


def read(path):
    return json.loads(path.read_text())


@macos
def test_fresh_install(sandbox):
    result = run(sandbox)
    assert result.returncode == 0, result.stderr
    assert read(sandbox.settings) == {"theme": THEME}
    assert sandbox.read_theme() == {"name": "Theme sync", "base": "light"}
    assert "New theme" in result.stdout
    assert "restart Claude Code once" in result.stdout
    assert sandbox.wait_for(lambda: len(sandbox.watchers()) == 1)


@macos
def test_no_restart_note_when_the_themes_folder_exists(sandbox):
    sandbox.theme.parent.mkdir(parents=True)
    result = run(sandbox)
    assert result.returncode == 0, result.stderr
    assert "restart Claude Code" not in result.stdout


@macos
def test_keeps_every_other_key_in_order(sandbox):
    original = {
        "model": "opus",
        "env": {"FOO": "bar"},
        "permissions": {"allow": ["Bash(ls *)"]},
        "note": "café ✓",
    }
    write(sandbox.settings, original)
    assert run(sandbox).returncode == 0
    updated = read(sandbox.settings)
    assert list(updated) == [*original, "theme"]
    assert {k: v for k, v in updated.items() if k != "theme"} == original
    assert "café ✓" in sandbox.settings.read_text(encoding="utf-8")


@macos
def test_writes_through_a_symlinked_settings_file(sandbox, tmp_path):
    real = tmp_path / "dotfiles" / "claude" / "settings.json"
    write(real, {"model": "opus"})
    sandbox.claude.mkdir(parents=True)
    sandbox.settings.symlink_to(real)
    result = run(sandbox)
    assert result.returncode == 0, result.stderr
    assert sandbox.settings.is_symlink()
    assert read(real) == {"model": "opus", "theme": THEME}
    assert "through the symlink" in result.stdout
    assert sorted(p.name for p in real.parent.iterdir()) == ["settings.json"]


@macos
def test_writes_through_a_chain_of_symlinks(sandbox, tmp_path):
    real = tmp_path / "real.json"
    write(real, {})
    middle = tmp_path / "middle.json"
    middle.symlink_to(real)
    sandbox.claude.mkdir(parents=True)
    sandbox.settings.symlink_to(middle)
    assert run(sandbox).returncode == 0
    assert sandbox.settings.is_symlink() and middle.is_symlink()
    assert read(real) == {"theme": THEME}


@macos
def test_asks_before_replacing_a_different_theme(sandbox):
    write(sandbox.settings, {"model": "opus", "theme": "light-daltonized"})
    before = sandbox.settings.read_bytes()
    result = run(sandbox)
    assert result.returncode == 3
    assert sandbox.settings.read_bytes() == before
    assert '"light-daltonized"' in result.stdout
    assert f'"{THEME}"' in result.stdout
    assert "--force" in result.stdout
    assert not sandbox.theme.exists()
    assert sandbox.watchers() == []


@macos
def test_force_replaces_it(sandbox):
    write(sandbox.settings, {"theme": "auto", "model": "opus"})
    result = run(sandbox, "--force")
    assert result.returncode == 0, result.stderr
    assert read(sandbox.settings) == {"theme": THEME, "model": "opus"}
    assert 'Old theme: "auto"' in result.stdout
    assert sandbox.theme.exists()


@macos
def test_already_set_changes_nothing(sandbox):
    write(sandbox.settings, {"theme": THEME})
    before = sandbox.settings.stat().st_mtime_ns
    result = run(sandbox)
    assert result.returncode == 0
    assert "Nothing changed" in result.stdout
    assert sandbox.settings.stat().st_mtime_ns == before
    assert sandbox.theme.exists()


@macos
def test_rerun_keeps_one_watcher(sandbox):
    assert run(sandbox).returncode == 0
    first = sandbox.wait_for(lambda: len(sandbox.watchers()) == 1 and sandbox.watchers())
    assert run(sandbox).returncode == 0
    assert sandbox.watchers() == first


@macos
@pytest.mark.parametrize("content", ["", "  \n"])
def test_empty_settings_file(sandbox, content):
    sandbox.claude.mkdir()
    sandbox.settings.write_text(content)
    assert run(sandbox).returncode == 0
    assert read(sandbox.settings) == {"theme": THEME}


@macos
@pytest.mark.parametrize("content", ["{not json", "[]"])
def test_refuses_to_touch_unparseable_settings(sandbox, content):
    sandbox.claude.mkdir()
    sandbox.settings.write_text(content)
    result = run(sandbox)
    assert result.returncode == 1
    assert "error:" in result.stderr
    assert sandbox.settings.read_text() == content
    assert not sandbox.theme.exists()


@macos
def test_keeps_file_permissions(sandbox):
    write(sandbox.settings, {})
    sandbox.settings.chmod(0o600)
    assert run(sandbox).returncode == 0
    assert stat.S_IMODE(sandbox.settings.stat().st_mode) == 0o600


@macos
def test_honours_claude_config_dir(sandbox, tmp_path):
    config = tmp_path / "config"
    data = config / "plugins" / "data" / "theme-sync-ai-toolkit"
    assert run(sandbox, data=data, CLAUDE_CONFIG_DIR=str(config)).returncode == 0
    assert not sandbox.settings.exists()
    assert not sandbox.theme.exists()
    assert read(config / "settings.json") == {"theme": THEME}
    assert (config / "themes" / "theme-sync.json").is_file()


@macos
def test_settings_flag(sandbox, tmp_path):
    target = tmp_path / "elsewhere" / "settings.json"
    assert run(sandbox, "--settings", str(target)).returncode == 0
    assert read(target) == {"theme": THEME}


@macos
def test_rejects_a_relative_data_dir(sandbox):
    result = run(sandbox, data="relative/dir")
    assert result.returncode == 1
    assert not sandbox.settings.exists()
    assert not os.path.exists(sandbox.theme)


@macos
@pytest.mark.parametrize("content", [None, "", "sepia"])
def test_needs_theme_monitor(sandbox, content):
    sandbox.trigger.unlink()
    if content is not None:
        sandbox.set_trigger(content)
    write(sandbox.settings, {"model": "opus"})
    before = sandbox.settings.read_bytes()
    result = run(sandbox)
    assert result.returncode == 4
    assert INSTALL in result.stdout
    assert "Nothing changed" in result.stdout
    assert sandbox.settings.read_bytes() == before
    assert not sandbox.theme.exists()
    assert not sandbox.data.exists()


def test_refuses_off_macos(monkeypatch, tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("setup_theme_sync", SETUP)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "setup_theme_sync", module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.theme_sync.sys, "platform", "linux")
    settings = tmp_path / "settings.json"
    assert module.main([str(tmp_path / "data"), "--settings", str(settings)]) == 1
    assert "macOS only" in capsys.readouterr().err
    assert not settings.exists()
