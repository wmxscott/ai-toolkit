import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
ROOT = PLUGIN.parent.parent
SKILL = (PLUGIN / "skills" / "herdr-worktrees" / "SKILL.md").read_text()
BLOCKS = re.findall(r"^```sh\n(.+?)\n```$", SKILL, re.M | re.S)
[FALLBACK] = [block for block in BLOCKS if block.startswith("branch=<branch>\n")]
GIT = shutil.which("git") or "/usr/bin/git"
SHELLS = [shell for shell in ("/bin/bash", "/bin/zsh") if Path(shell).is_file()]

# `herdr worktree open --help`, herdr 0.9.
HERDR_OPEN_FLAGS = {
    "--workspace",
    "--cwd",
    "--path",
    "--branch",
    "--label",
    "--focus",
    "--no-focus",
    "--trust-repository",
}

HERDR_STUB = """#!/bin/bash
printf '%s\\n' "$@" > "$HERDR_LOG"
"""

# Answers `git remote get-url origin` with $FAKE_ORIGIN_URL, so URL forms that can't be
# fetched in a test can still be parsed; every other call goes to the real git.
GIT_STUB = """#!/bin/bash
if [ -n "$FAKE_ORIGIN_URL" ] && [ "$*" = "remote get-url origin" ]; then
    printf '%s\\n' "$FAKE_ORIGIN_URL"
    exit 0
fi
exec "$REAL_GIT" "$@"
"""


def manifest(*parts):
    return json.loads(PLUGIN.joinpath(*parts).read_text())


def test_frontmatter_is_portable():
    frontmatter = re.match(r"---\n(.*?)\n---\n", SKILL, re.S)
    assert frontmatter
    fields = dict(line.split(": ", 1) for line in frontmatter[1].splitlines())
    assert fields.keys() == {"name", "description"}
    assert fields["name"] == "herdr-worktrees"
    description = fields["description"]
    assert description.startswith("Use when")
    assert len(description) <= 1024
    assert ": " not in description and " #" not in description


def test_command_surface_matches_herdr_wkt():
    commands = [b for b in BLOCKS if b.startswith("wkt ")]
    assert commands == [
        "wkt new -b <branch> [-s <source>] [-n <label>]",
        "wkt rename -b <new-branch> [-n <label>] [-y]",
        "wkt setup <repo-url>",
    ]


def test_describes_herdr_wkt_1_0():
    for fact in (
        "`$HERDR_WKT_ROOT/<org>/<repo>/<branch>`",
        "defaults to `~/.herdr/worktrees`",
        "`.bare` layouts",
        "with `--no-track`",
        "`herdr-wkt`",
    ):
        assert fact in SKILL, fact
    assert not re.search(r"\btabs?\b", SKILL, re.I), "Herdr calls them workspaces"
    assert "DEV_DIR" not in SKILL


def test_fallback_uses_real_herdr_flags():
    calls = " ".join(re.findall(r"herdr worktree open[^\n`]*", SKILL))
    used = set(re.findall(r"--[a-z-]+", calls))
    assert used
    assert used <= HERDR_OPEN_FLAGS


def test_no_agent_specific_variables():
    assert "CLAUDE_" not in SKILL


def test_codex_manifest_mirrors_claude_manifest():
    claude = manifest(".claude-plugin", "plugin.json")
    codex = manifest("plugin.json")
    for field in ("name", "description", "author", "homepage", "repository", "license", "keywords"):
        assert codex[field] == claude[field], field
    assert "version" not in claude and "version" not in codex
    assert codex["extensions"]["com.openai"]["interface"]["developerName"] == "wmxscott"


def test_listed_in_both_marketplaces():
    claude = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    codex = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
    assert {"name": "herdr", "source": "./plugins/herdr"}.items() <= next(
        e for e in claude["plugins"] if e["name"] == "herdr"
    ).items()
    assert next(e for e in codex["plugins"] if e["name"] == "herdr")["source"] == {
        "source": "local",
        "path": "./plugins/herdr",
    }


class Sandbox:
    """A scratch $HOME and git config, an origin at <root>/remotes/acme/widget.git, and stub
    herdr and git first on PATH. No HERDR_* variable is set."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.home = self.root / "home"
        self.bin = self.root / "bin"
        self.log = self.root / "herdr.log"
        self.home.mkdir()
        self.bin.mkdir()
        (self.home / ".gitconfig").touch()
        for name, text in (("herdr", HERDR_STUB), ("git", GIT_STUB)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        self.env = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_STATE_HOME": str(self.home / ".local" / "state"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "XDG_DATA_HOME": str(self.home / ".local" / "share"),
            "GIT_CONFIG_GLOBAL": str(self.home / ".gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "PATH": f"{self.bin}:{Path(GIT).parent}:/usr/bin:/bin",
            "REAL_GIT": GIT,
            "HERDR_LOG": str(self.log),
        }
        self.origin = self.root / "remotes" / "acme" / "widget.git"
        seed = self.root / "seed"
        self.git(self.root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(self.root, "clone", "-q", str(self.origin), str(seed))
        self.commit(seed, "base")
        self.git(seed, "push", "-q", "origin", "main")
        self.seed = seed

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=cwd, env=self.env, capture_output=True, text=True, check=True
        ).stdout.strip()

    def commit(self, repo: Path, name: str) -> None:
        (repo / name).write_text(name)
        self.git(repo, "add", name)
        self.git(repo, "commit", "-q", "-m", name)

    def upstream_moves(self) -> str:
        self.commit(self.seed, "upstream")
        self.git(self.seed, "push", "-q", "origin", "main")
        return self.git(self.seed, "rev-parse", "HEAD")

    def clone(self) -> Path:
        work = self.root / "src" / "widget"
        self.git(self.root, "clone", "-q", str(self.origin), str(work))
        return work

    def bare_layout(self) -> Path:
        """What `wkt setup` builds."""
        top = self.root / "src" / "widget"
        top.mkdir(parents=True)
        self.git(top, "clone", "-q", "--bare", str(self.origin), ".bare")
        (top / ".git").write_text("gitdir: ./.bare\n")
        self.git(top, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
        self.git(top, "fetch", "-q", "origin")
        self.git(top, "remote", "set-head", "origin", "--auto")
        self.git(top, "worktree", "add", "-q", "main", "main")
        return top

    def run(self, shell: str, cwd: Path, branch: str = "feat/login", base: str = ""):
        script = FALLBACK.replace("<branch>", branch).replace("base=\n", f"base={base}\n", 1)
        args = [shell, "-f", "-c", script] if shell.endswith("zsh") else [shell, "-c", script]
        return subprocess.run(args, cwd=cwd, env=self.env, capture_output=True, text=True)

    def herdr_calls(self) -> list[str]:
        return self.log.read_text().splitlines()


@pytest.fixture
def sandbox(tmp_path):
    return Sandbox(tmp_path)


def assert_created(sandbox, result, repo_common: Path, worktree: Path, tip: str):
    assert result.returncode == 0, result.stderr
    assert worktree.is_dir()
    assert sandbox.git(worktree, "rev-parse", "HEAD") == tip
    assert sandbox.git(worktree, "branch", "--show-current") == "feat/login"
    upstream = subprocess.run(
        ["git", "config", "--get", "branch.feat/login.merge"], cwd=worktree, env=sandbox.env
    )
    assert upstream.returncode == 1, "a new branch must not track its base"
    assert sandbox.herdr_calls() == [
        "worktree",
        "open",
        "--cwd",
        str(repo_common),
        "--path",
        str(worktree),
        "--focus",
    ]


@pytest.mark.parametrize("shell", SHELLS)
def test_fallback_in_a_clone_uses_the_default_root(sandbox, shell):
    work = sandbox.clone()
    tip = sandbox.upstream_moves()
    result = sandbox.run(shell, work)
    worktree = sandbox.home / ".herdr" / "worktrees" / "acme" / "widget" / "feat" / "login"
    assert_created(sandbox, result, work / ".git", worktree, tip)


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("setting", ["~/trees", "{home}/trees"])
def test_fallback_honours_herdr_wkt_root(sandbox, shell, setting):
    sandbox.env["HERDR_WKT_ROOT"] = setting.format(home=sandbox.home)
    work = sandbox.clone()
    result = sandbox.run(shell, work)
    worktree = sandbox.home / "trees" / "acme" / "widget" / "feat" / "login"
    assert_created(sandbox, result, work / ".git", worktree, sandbox.git(work, "rev-parse", "HEAD"))


@pytest.mark.parametrize("shell", SHELLS)
def test_fallback_from_a_linked_worktree_still_opens_from_the_repository(sandbox, shell):
    work = sandbox.clone()
    other = sandbox.root / "other"
    sandbox.git(work, "worktree", "add", "-q", "-b", "other", str(other))
    result = sandbox.run(shell, other)
    worktree = sandbox.home / ".herdr" / "worktrees" / "acme" / "widget" / "feat" / "login"
    assert_created(sandbox, result, work / ".git", worktree, sandbox.git(work, "rev-parse", "HEAD"))


@pytest.mark.parametrize("shell", SHELLS)
def test_fallback_in_a_bare_layout_adds_a_sibling(sandbox, shell):
    top = sandbox.bare_layout()
    tip = sandbox.upstream_moves()
    result = sandbox.run(shell, top / "main")
    assert_created(sandbox, result, top / ".bare", top / "feat" / "login", tip)


@pytest.mark.parametrize("shell", SHELLS)
def test_fallback_starts_from_a_chosen_base(sandbox, shell):
    sandbox.git(sandbox.seed, "switch", "-q", "-c", "release")
    sandbox.commit(sandbox.seed, "release-only")
    sandbox.git(sandbox.seed, "push", "-q", "origin", "release")
    release = sandbox.git(sandbox.seed, "rev-parse", "HEAD")
    work = sandbox.clone()
    result = sandbox.run(shell, work, base="release")
    worktree = sandbox.home / ".herdr" / "worktrees" / "acme" / "widget" / "feat" / "login"
    assert_created(sandbox, result, work / ".git", worktree, release)


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:acme/widget.git",
        "https://github.com/acme/widget.git",
        "https://github.com/acme/widget",
        "ssh://git@github.com/acme/widget.git",
    ],
)
def test_fallback_reads_org_and_repo_from_any_origin_url(sandbox, shell, url):
    work = sandbox.clone()
    sandbox.env["FAKE_ORIGIN_URL"] = url
    result = sandbox.run(shell, work)
    worktree = sandbox.home / ".herdr" / "worktrees" / "acme" / "widget" / "feat" / "login"
    assert_created(sandbox, result, work / ".git", worktree, sandbox.git(work, "rev-parse", "HEAD"))
