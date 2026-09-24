import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture
def sl(monkeypatch):
    spec = importlib.util.spec_from_file_location("statusline", SCRIPTS / "statusline.py")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves string annotations through sys.modules.
    monkeypatch.setitem(sys.modules, "statusline", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A scratch $HOME with git isolated from the real global config."""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("CLAUDE_STATUSLINE_THEME", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    return path


def run_git(cwd, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def git():
    return run_git


@pytest.fixture
def repo(home):
    """A repo named `project` on `main`, with one commit of a three-line file."""
    path = home / "project"
    path.mkdir()
    run_git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("one\ntwo\nthree\n")
    run_git(path, "add", "a.txt")
    run_git(path, "commit", "-q", "--no-gpg-sign", "-m", "init")
    return path


@pytest.fixture
def sample():
    """Statusline input with every field the statusline reads."""
    return {
        "model": {"id": "claude-opus-4-7", "display_name": "Claude Opus 4.7"},
        "vim": {"mode": "insert"},
        "effort": {"level": "high"},
        "output_style": {"name": "Explanatory"},
        "context_window": {"used_percentage": 42, "context_window_size": 200000},
        "cost": {"total_cost_usd": 1.234, "total_duration_ms": 125000},
        "rate_limits": {
            "five_hour": {
                "used_percentage": 23.5,
                "resets_at": int(time.time()) + 2 * 3600 + 14 * 60 + 30,
            },
            "seven_day": {"used_percentage": 41.2, "resets_at": int(time.time()) + 5 * 86400},
        },
    }
