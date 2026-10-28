import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "scripts" / "check_plugin_versions.sh"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")


@pytest.fixture
def repo(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True)

    def write(rel, text):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def manifest(version=None):
        data = {"name": "x"}
        if version:
            data["version"] = version
        write("plugins/x/.claude-plugin/plugin.json", json.dumps(data))

    def commit(message):
        git("add", "-A")
        git("commit", "-q", "-m", message)

    def check():
        return subprocess.run(
            ["bash", str(CHECK), "base"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    git("init", "-q", "-b", "main")
    write("README.md", "readme\n")

    return SimpleNamespace(git=git, write=write, manifest=manifest, commit=commit, check=check)


def start(repo, version):
    repo.manifest(version)
    repo.write("plugins/x/a.txt", "one\n")
    repo.commit("base")
    repo.git("branch", "base")


def test_passes_when_base_has_no_version(repo):
    start(repo, None)
    repo.write("plugins/x/a.txt", "two\n")
    repo.commit("change")
    result = repo.check()
    assert result.returncode == 0, result.stderr


def test_fails_on_a_change_without_a_bump(repo):
    start(repo, "2.0.0")
    repo.write("plugins/x/a.txt", "two\n")
    repo.commit("change")
    result = repo.check()
    assert result.returncode == 1
    assert "plugins/x" in result.stderr
    assert "2.0.0" in result.stderr


def test_passes_on_a_change_with_a_bump(repo):
    start(repo, "2.0.0")
    repo.write("plugins/x/a.txt", "two\n")
    repo.manifest("2.0.1")
    repo.commit("change")
    result = repo.check()
    assert result.returncode == 0, result.stderr


def test_passes_on_a_change_outside_the_plugin(repo):
    start(repo, "2.0.0")
    repo.write("README.md", "changed\n")
    repo.commit("change")
    result = repo.check()
    assert result.returncode == 0, result.stderr


def test_passes_with_no_changes(repo):
    start(repo, "2.0.0")
    result = repo.check()
    assert result.returncode == 0, result.stderr


def test_ignores_plugin_changes_on_base_after_the_fork(repo):
    start(repo, "2.0.0")
    repo.git("checkout", "-q", "-b", "feature")
    repo.write("README.md", "changed\n")
    repo.commit("feature change")
    repo.git("checkout", "-q", "base")
    repo.write("plugins/x/a.txt", "two\n")
    repo.manifest("2.0.1")
    repo.commit("bump on base")
    repo.git("checkout", "-q", "feature")
    result = repo.check()
    assert result.returncode == 0, result.stderr


def test_a_bump_on_base_after_the_fork_does_not_cover_the_branch(repo):
    start(repo, "2.0.0")
    repo.git("checkout", "-q", "-b", "feature")
    repo.write("plugins/x/b.txt", "feature\n")
    repo.commit("feature change")
    repo.git("checkout", "-q", "base")
    repo.write("plugins/x/a.txt", "two\n")
    repo.manifest("2.0.1")
    repo.commit("bump on base")
    repo.git("checkout", "-q", "feature")
    result = repo.check()
    assert result.returncode == 1
    assert "2.0.0" in result.stderr
