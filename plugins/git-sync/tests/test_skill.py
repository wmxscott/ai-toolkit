"""Runs the commands exactly as SKILL.md gives them against scratch repositories."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
SKILL = (PLUGIN / "skills" / "fast-forward-sync" / "SKILL.md").read_text()
GIT = shutil.which("git") or "/usr/bin/git"
UPSTREAM, FETCH, COUNT, FAST_FORWARD = re.findall(r"^```bash\n(.+?)\n```$", SKILL, re.M | re.S)


def test_frontmatter_names_the_skill():
    frontmatter = re.match(r"---\n(.*?)\n---\n", SKILL, re.S)
    assert frontmatter
    fields = dict(line.split(": ", 1) for line in frontmatter[1].splitlines())
    assert fields.keys() == {"name", "description"}
    assert fields["name"] == "fast-forward-sync"
    assert fields["description"].startswith("Use when")


def test_procedure_uses_only_safe_commands():
    assert (UPSTREAM, FETCH, COUNT, FAST_FORWARD) == (
        "git rev-parse --abbrev-ref --symbolic-full-name '@{u}'",
        "git fetch",
        "git rev-list --left-right --count 'HEAD...@{u}'",
        "git merge --ff-only '@{u}'",
    )


class Repos:
    """A bare origin, the working clone the skill runs in, and a second clone that pushes to it."""

    def __init__(self, root: Path):
        self.home = root / "home"
        self.home.mkdir()
        (self.home / ".gitconfig").touch()
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{Path(GIT).parent}:/usr/bin:/bin",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
        self.origin = root / "origin.git"
        self.work = root / "work"
        self.other = root / "other"
        self.git(root, "init", "--bare", "-b", "main", str(self.origin))
        self.git(root, "clone", "-q", str(self.origin), str(self.work))
        self.commit(self.work, "base")
        self.git(self.work, "push", "-q", "-u", "origin", "main")
        self.git(root, "clone", "-q", str(self.origin), str(self.other))

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=cwd, env=self.env, capture_output=True, text=True, check=True
        ).stdout.strip()

    def commit(self, repo: Path, name: str, content: str | None = None) -> None:
        (repo / name).write_text(content or name)
        self.git(repo, "add", name)
        self.git(repo, "commit", "-q", "-m", name)

    def upstream_moves(self, name: str = "upstream", content: str | None = None) -> None:
        self.commit(self.other, name, content)
        self.git(self.other, "push", "-q")

    def run(self, command: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "-c", command], cwd=self.work, env=self.env, capture_output=True, text=True
        )

    def head(self) -> str:
        return self.git(self.work, "rev-parse", "HEAD")

    def counts(self) -> str:
        assert self.run(UPSTREAM).returncode == 0
        assert self.run(FETCH).returncode == 0
        result = self.run(COUNT)
        assert result.returncode == 0
        return result.stdout.strip()


@pytest.fixture
def repos(tmp_path):
    return Repos(tmp_path)


def test_no_upstream_is_detected(repos):
    repos.git(repos.work, "switch", "-q", "-c", "local-only")
    assert repos.run(UPSTREAM).returncode != 0


def test_detached_head_is_detected(repos):
    repos.git(repos.work, "switch", "-q", "--detach")
    assert repos.run(UPSTREAM).returncode != 0


def test_up_to_date(repos):
    assert repos.counts() == "0\t0"


def test_behind_only_fast_forwards(repos):
    repos.upstream_moves()
    assert repos.counts() == "0\t1"
    assert repos.run(FAST_FORWARD).returncode == 0
    assert repos.head() == repos.git(repos.work, "rev-parse", "@{u}")
    assert (repos.work / "upstream").is_file()


def test_ahead_only_has_nothing_to_pull(repos):
    repos.commit(repos.work, "local")
    assert repos.counts() == "1\t0"


def test_diverged_refuses_and_leaves_head_alone(repos):
    repos.commit(repos.work, "local")
    repos.upstream_moves()
    assert repos.counts() == "1\t1"
    before = repos.head()
    assert repos.run(FAST_FORWARD).returncode != 0
    assert repos.head() == before


def test_uncommitted_change_blocks_fast_forward_without_loss(repos):
    repos.upstream_moves("base", "upstream edit")
    (repos.work / "base").write_text("local edit")
    assert repos.counts() == "0\t1"
    before = repos.head()
    assert repos.run(FAST_FORWARD).returncode != 0
    assert repos.head() == before
    assert (repos.work / "base").read_text() == "local edit"
