import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture
def home(tmp_path, stubs, monkeypatch):
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("PATH", f"{stubs}:/usr/bin:/bin")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_THEME_SYNC_THEME", raising=False)
    return path


def trigger(home, value):
    path = home / ".local" / "share" / "theme-monitor" / "theme-change.trigger"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def appearance(home, dark):
    (home / "appearance").write_text("Dark" if dark else "")


@pytest.fixture
def darwin(monkeypatch, ts):
    monkeypatch.setattr(ts.sys, "platform", "darwin")


def test_override_wins_over_everything(ts, home, darwin, monkeypatch):
    trigger(home, "dark")
    appearance(home, True)
    monkeypatch.setenv("CLAUDE_THEME_SYNC_THEME", " Light ")
    assert ts.resolve() == "light"


@pytest.mark.parametrize("value", ["", "blue", "auto"])
def test_unusable_override_is_ignored(ts, home, darwin, monkeypatch, value):
    trigger(home, "light")
    monkeypatch.setenv("CLAUDE_THEME_SYNC_THEME", value)
    assert ts.resolve() == "light"


@pytest.mark.parametrize(("content", "expected"), [("light", "light"), ("dark\n", "dark")])
def test_trigger_file_wins_over_macos(ts, home, darwin, content, expected):
    appearance(home, expected == "light")
    trigger(home, content)
    assert ts.resolve() == expected


def test_unreadable_trigger_falls_through_to_macos(ts, home, darwin):
    trigger(home, "sepia")
    appearance(home, False)
    assert ts.resolve() == "light"


@pytest.mark.parametrize(("dark", "expected"), [(True, "dark"), (False, "light")])
def test_macos_appearance(ts, home, darwin, dark, expected):
    appearance(home, dark)
    assert ts.resolve() == expected


def test_defaults_missing_means_dark(ts, home, darwin, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    assert ts.resolve() == "dark"


def test_not_macos_means_dark(ts, home, monkeypatch):
    monkeypatch.setattr(ts.sys, "platform", "linux")
    appearance(home, False)
    assert ts.resolve() == "dark"


def test_sync_command_prints_and_writes(home):
    trigger(home, "light")
    env = {"HOME": str(home), "PATH": os.environ["PATH"]}
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "theme_sync.py"), "sync"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out == "light\n"
    theme = home / ".claude" / "themes" / "theme-sync.json"
    assert json.loads(theme.read_text()) == {"name": "Theme sync", "base": "light"}


def test_theme_path_honours_claude_config_dir(ts, home, monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    assert ts.theme_path() == str(tmp_path / "config" / "themes" / "theme-sync.json")


@pytest.fixture
def theme(home):
    return home / ".claude" / "themes" / "theme-sync.json"


def test_sync_creates_the_file_and_folder(ts, theme):
    assert ts.sync("dark") is True
    assert json.loads(theme.read_text()) == {"name": "Theme sync", "base": "dark"}
    assert ts.SETTING == "custom:theme-sync"


def test_sync_writes_only_on_a_change(ts, theme):
    ts.sync("dark")
    before = os.stat(theme)
    assert ts.sync("dark") is False
    after = os.stat(theme)
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


def test_sync_replaces_the_file_atomically(ts, theme):
    ts.sync("dark")
    before = os.stat(theme).st_ino
    assert ts.sync("light") is True
    assert os.stat(theme).st_ino != before
    assert sorted(p.name for p in theme.parent.iterdir()) == ["theme-sync.json"]


def test_sync_keeps_name_overrides_and_order(ts, theme):
    theme.parent.mkdir(parents=True)
    original = {"overrides": {"claude": "#bd93f9"}, "base": "dark", "name": "Mine"}
    theme.write_text(json.dumps(original))
    ts.sync("light")
    updated = json.loads(theme.read_text())
    assert updated == {**original, "base": "light"}
    assert list(updated) == ["name", "overrides", "base"]


@pytest.mark.parametrize("content", ["{broken", "[]", ""])
def test_sync_replaces_an_unusable_file(ts, theme, content):
    theme.parent.mkdir(parents=True)
    theme.write_text(content)
    assert ts.sync("dark") is True
    assert json.loads(theme.read_text())["base"] == "dark"


def test_sync_writes_through_a_symlink(ts, theme, tmp_path):
    real = tmp_path / "dotfiles" / "theme-sync.json"
    real.parent.mkdir()
    real.write_text('{"base": "dark"}')
    theme.parent.mkdir(parents=True)
    theme.symlink_to(real)
    ts.sync("light")
    assert theme.is_symlink()
    assert json.loads(real.read_text())["base"] == "light"
    assert sorted(p.name for p in real.parent.iterdir()) == ["theme-sync.json"]


def test_sync_keeps_file_permissions(ts, theme):
    ts.sync("dark")
    theme.chmod(0o600)
    ts.sync("light")
    assert stat.S_IMODE(theme.stat().st_mode) == 0o600


def test_live_clients_forgets_dead_and_reused_pids(ts, tmp_path):
    data = tmp_path / "data"
    assert ts.register(str(data), os.getpid())
    dead = subprocess.Popen(["true"])
    dead.wait()
    (data / "clients" / str(dead.pid)).write_text("Mon Jan  1 00:00:00 2024\n")
    reused = subprocess.Popen(["sleep", "30"])
    try:
        (data / "clients" / str(reused.pid)).write_text("Mon Jan  1 00:00:00 2024\n")
        assert ts.live_clients(str(data)) == 1
        assert sorted(p.name for p in (data / "clients").iterdir()) == [str(os.getpid())]
    finally:
        reused.kill()
        reused.wait()


def test_live_clients_without_a_data_dir(ts, tmp_path):
    assert ts.live_clients(str(tmp_path / "missing")) == 0


def test_lock_is_exclusive(ts, tmp_path):
    fd = ts.try_lock(str(tmp_path))
    assert fd is not None
    assert ts.try_lock(str(tmp_path)) is None
    os.close(fd)
    again = ts.try_lock(str(tmp_path))
    assert again is not None
    os.close(again)
