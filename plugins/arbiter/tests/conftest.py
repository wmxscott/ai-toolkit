"""Fixtures for the arbiter suite.

Every test runs under a scratch HOME with git's global and system config cut off,
and every subprocess gets an environment built from scratch. `claude` and `codex`
are only ever stubs: nothing here reaches a real CLI, login or repository.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN / "lib"))

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}

# Records how it was called, then answers from STUB_OUTPUT / STUB_STATUS. A
# codex stub also writes STUB_VERDICT to the file named by -o, as codex does.
STUB = """#!{python}
import json, os, sys
from pathlib import Path
record = {{
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "stdin": sys.stdin.read(),
    "child": os.environ.get("ARBITER_CHILD"),
}}
log = Path(os.environ["STUB_LOG"])
calls = json.loads(log.read_text()) if log.exists() else []
log.write_text(json.dumps(calls + [record]))
if "-o" in sys.argv and "STUB_VERDICT" in os.environ:
    Path(sys.argv[sys.argv.index("-o") + 1]).write_text(os.environ["STUB_VERDICT"])
sys.stdout.write(os.environ.get("STUB_OUTPUT", ""))
sys.stderr.write(os.environ.get("STUB_STDERR", ""))
sys.exit(int(os.environ.get("STUB_STATUS", "0")))
"""


def git(cwd, *args):
    env = {**os.environ, **GIT_IDENTITY}
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


class Home:
    """A scratch HOME holding the user config dir, the state dir and a stub bin."""

    def __init__(self, root: Path):
        self.root = root
        self.path = root / "home"
        self.config = self.path / ".config" / "arbiter"
        self.state = self.path / ".local" / "state" / "arbiter"
        self.bin = root / "bin"
        self.log = root / "stub-calls.json"
        for directory in (self.path, self.bin):
            directory.mkdir(parents=True, exist_ok=True)

    def env(self) -> dict:
        return {
            "HOME": str(self.path),
            "XDG_CONFIG_HOME": str(self.path / ".config"),
            "XDG_STATE_HOME": str(self.path / ".local" / "state"),
            "XDG_CACHE_HOME": str(self.path / ".cache"),
            "XDG_DATA_HOME": str(self.path / ".local" / "share"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "STUB_LOG": str(self.log),
        }

    def user_defaults(self, text: str) -> Path:
        self.config.mkdir(parents=True, exist_ok=True)
        path = self.config / "defaults.toml"
        path.write_text(text)
        return path

    def stub(self, name: str) -> Path:
        path = self.bin / name
        path.write_text(STUB.format(python=sys.executable))
        path.chmod(0o755)
        return path

    def calls(self) -> list[dict]:
        return json.loads(self.log.read_text()) if self.log.exists() else []


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = Home(tmp_path)
    for name in list(os.environ):
        if name.startswith(("ARBITER_", "STUB_", "GIT_", "CLAUDE_")):
            monkeypatch.delenv(name)
    for name, value in home.env().items():
        monkeypatch.setenv(name, value)
    return home


@pytest.fixture
def repo(home, monkeypatch):
    """A repository `project` on `main` with one commit, as the working directory."""
    path = home.path / "project"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("hello\n")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "--no-gpg-sign", "-m", "init")
    monkeypatch.chdir(path)
    return path


@pytest.fixture
def write_config(repo):
    def _write(text: str, name: str = "arbiter.toml") -> Path:
        path = repo / name
        path.write_text(text)
        return path

    return _write


@pytest.fixture(name="git")
def git_fixture():
    return git
