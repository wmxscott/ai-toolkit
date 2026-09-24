import json
import os
import stat
import sys

import pytest

macos = pytest.mark.skipif(sys.platform != "darwin", reason="theme-sync runs on macOS only")


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_THEME_SYNC_THEME", raising=False)
    return path


def trigger(home, value):
    path = home / ".local" / "share" / "theme-monitor" / "theme-change.trigger"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


@pytest.fixture
def theme(home):
    return home / ".claude" / "themes" / "theme-sync.json"


def test_override_wins_over_the_trigger(ts, home, monkeypatch):
    trigger(home, "dark")
    monkeypatch.setenv("CLAUDE_THEME_SYNC_THEME", " Light ")
    assert ts.override_theme() == "light"


@pytest.mark.parametrize("value", ["", "blue", "auto"])
def test_unusable_override_is_ignored(ts, home, monkeypatch, value):
    monkeypatch.setenv("CLAUDE_THEME_SYNC_THEME", value)
    assert ts.override_theme() is None


@pytest.mark.parametrize(("content", "expected"), [("light", "light"), ("dark\n", "dark")])
def test_trigger_file(ts, home, content, expected):
    trigger(home, content)
    assert ts.trigger_theme() == expected


@pytest.mark.parametrize("content", [None, "", "sepia"])
def test_no_usable_trigger_means_no_theme(ts, home, content):
    if content is not None:
        trigger(home, content)
    assert ts.trigger_theme() is None


def test_theme_path_honours_claude_config_dir(ts, home, monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    assert ts.theme_path() == str(tmp_path / "config" / "themes" / "theme-sync.json")


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


def test_register_records_the_start_time(ts, tmp_path):
    assert ts.register(str(tmp_path), os.getpid())
    recorded = (tmp_path / "clients" / str(os.getpid())).read_text().strip()
    assert recorded == ts.start_times([os.getpid()])[os.getpid()]


def test_register_skips_a_dead_pid(ts, tmp_path):
    assert not ts.register(str(tmp_path), 99999)
    assert not (tmp_path / "clients").exists()


def test_lock_is_exclusive(ts, tmp_path):
    fd = ts.try_lock(str(tmp_path))
    assert fd is not None
    assert ts.try_lock(str(tmp_path)) is None
    os.close(fd)
    again = ts.try_lock(str(tmp_path))
    assert again is not None
    os.close(again)


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_start_and_watch_are_silent_no_ops_off_macos(ts, home, theme, monkeypatch, platform):
    monkeypatch.setattr(ts.sys, "platform", platform)
    trigger(home, "dark")
    theme.parent.mkdir(parents=True)
    theme.write_text('{"base": "light"}')
    data = home / "data"
    assert ts.start(str(data)) == 0
    assert ts.watch(str(data)) == 0
    assert json.loads(theme.read_text()) == {"base": "light"}
    assert not data.exists()


@macos
def test_start_without_theme_monitor_does_nothing(ts, home, theme):
    theme.parent.mkdir(parents=True)
    theme.write_text('{"base": "light"}')
    data = home / "data"
    assert ts.start(str(data)) == 0
    assert json.loads(theme.read_text()) == {"base": "light"}
    assert not data.exists()
