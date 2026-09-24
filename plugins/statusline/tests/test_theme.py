import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture
def trigger(home):
    path = home / ".local" / "share" / "theme-monitor" / "theme-change.trigger"
    path.parent.mkdir(parents=True)
    return path


@pytest.fixture
def macos(sl, monkeypatch):
    """Stand-in for the macOS appearance, recording whether it was asked."""
    state = {"value": None, "calls": 0}

    def appearance():
        state["calls"] += 1
        return state["value"]

    monkeypatch.setattr(sl, "macos_appearance", appearance)
    return state


@pytest.mark.parametrize(
    ("value", "expected", "other"),
    [("dark", "dark", "light"), ("light", "light", "dark"), (" Light\n", "light", "dark")],
)
def test_env_override_wins(sl, home, trigger, macos, monkeypatch, value, expected, other):
    trigger.write_text(other)
    macos["value"] = other
    monkeypatch.setenv("CLAUDE_STATUSLINE_THEME", value)
    assert sl.detect_theme() == expected
    assert macos["calls"] == 0


def test_invalid_env_override_is_ignored(sl, home, trigger, macos, monkeypatch):
    monkeypatch.setenv("CLAUDE_STATUSLINE_THEME", "auto")
    trigger.write_text("light")
    assert sl.detect_theme() == "light"


def test_trigger_file_beats_macos(sl, home, trigger, macos):
    trigger.write_text("light")
    macos["value"] = "dark"
    assert sl.detect_theme() == "light"
    assert macos["calls"] == 0


def test_unreadable_trigger_content_falls_through_to_macos(sl, home, trigger, macos):
    trigger.write_text("sepia")
    macos["value"] = "light"
    assert sl.detect_theme() == "light"


def test_macos_appearance_without_trigger(sl, home, macos):
    macos["value"] = "light"
    assert sl.detect_theme() == "light"
    assert macos["calls"] == 1


def test_defaults_to_dark(sl, home, macos):
    assert sl.detect_theme() == "dark"


@pytest.fixture
def defaults_run(sl, monkeypatch):
    calls = []

    def install(returncode=0, stdout="", error=None):
        def run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            if error:
                raise error
            return subprocess.CompletedProcess(cmd, returncode, stdout, "")

        monkeypatch.setattr(sl.subprocess, "run", run)
        return calls

    monkeypatch.setattr(sys, "platform", "darwin")
    return install


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [(0, "Dark\n", "dark"), (1, "", "light"), (0, "Light\n", "light")],
)
def test_macos_appearance_reads_the_global_default(sl, defaults_run, returncode, stdout, expected):
    calls = defaults_run(returncode, stdout)
    assert sl.macos_appearance() == expected
    cmd, kwargs = calls[0]
    assert cmd == ["defaults", "read", "-g", "AppleInterfaceStyle"]
    assert kwargs["timeout"] <= 1


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("defaults", 1)])
def test_macos_appearance_unknown_when_defaults_fails(sl, defaults_run, error):
    defaults_run(error=error)
    assert sl.macos_appearance() is None


def test_macos_appearance_skipped_off_macos(sl, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sl.subprocess, "run", lambda *a, **k: pytest.fail("ran defaults"))
    assert sl.macos_appearance() is None


@pytest.mark.skipif(sys.platform != "darwin", reason="reads the macOS appearance")
@pytest.mark.parametrize(("stub", "expected"), [("echo Dark", "dark"), ("exit 1", "light")])
def test_end_to_end_with_stubbed_defaults(sl, home, tmp_path, stub, expected):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "defaults").write_text(f"#!/bin/sh\n{stub}\n")
    (bin_dir / "defaults").chmod(0o755)
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin"}
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "statusline.py")],
        input='{"model": {"display_name": "Opus"}}',
        env=env,
        cwd=home,
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    palette = sl.DARK if expected == "dark" else sl.LIGHT
    assert palette.lavender in result.stdout
