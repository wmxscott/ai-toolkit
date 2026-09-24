def test_clean_repo(sl, repo):
    assert sl.git_info(str(repo)) == {
        "repo": "project",
        "branch": "main",
        "rel": "",
        "added": 0,
        "deleted": 0,
    }


def test_counts_staged_unstaged_and_untracked_lines(sl, repo, git):
    (repo / "a.txt").write_text("one\nthree\nfour\n")
    (repo / "b.txt").write_text("x\ny\n")
    git(repo, "add", "b.txt")
    (repo / "new.txt").write_text("1\n2\n3\n4\n")
    info = sl.git_info(str(repo))
    assert (info["added"], info["deleted"]) == (1 + 2 + 4, 1)


def test_subdirectory_reports_relative_path_and_whole_repo_changes(sl, repo):
    sub = repo / "src" / "lib"
    sub.mkdir(parents=True)
    (repo / "top.txt").write_text("a\nb\n")
    (sub / "deep.txt").write_text("c\n")
    info = sl.git_info(str(sub))
    assert info["rel"] == "src/lib"
    assert info["added"] == 3


def test_ignored_files_are_not_counted(sl, repo):
    (repo / ".gitignore").write_text("*.log\n")
    (repo / "debug.log").write_text("x\n" * 50)
    assert sl.git_info(str(repo))["added"] == 1


def test_odd_untracked_names_are_counted(sl, repo):
    (repo / "café menu.txt").write_text("a\nb\n")
    (repo / "-dash").write_text("c\n")
    assert sl.git_info(str(repo))["added"] == 3


def test_huge_untracked_files_are_skipped(sl, repo, monkeypatch):
    monkeypatch.setattr(sl, "MAX_UNTRACKED_BYTES", 10)
    (repo / "small.txt").write_text("a\n")
    (repo / "big.txt").write_text("b\n" * 20)
    assert sl.git_info(str(repo))["added"] == 1


def test_detached_head_shows_short_sha(sl, repo, git):
    sha = git(repo, "rev-parse", "--short", "HEAD")
    git(repo, "checkout", "-q", "--detach")
    assert sl.git_info(str(repo))["branch"] == sha


def test_repo_without_commits(sl, home, git):
    path = home / "fresh"
    path.mkdir()
    git(path, "init", "-q", "-b", "trunk")
    (path / "x.txt").write_text("1\n2\n")
    info = sl.git_info(str(path))
    assert (info["branch"], info["added"], info["deleted"]) == ("trunk", 2, 0)


def test_not_a_repo(sl, home):
    assert sl.git_info(str(home)) is None


def test_missing_directory(sl, home):
    assert sl.git_info(str(home / "does-not-exist")) is None


def test_git_not_installed(sl, repo, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    assert sl.git_info(str(repo)) is None


def test_git_runs_without_optional_locks(sl, repo, monkeypatch):
    seen = []
    real_run = sl.subprocess.run

    def run(cmd, **kwargs):
        seen.append(kwargs["env"].get("GIT_OPTIONAL_LOCKS"))
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(sl.subprocess, "run", run)
    sl.git_info(str(repo))
    assert seen and set(seen) == {"0"}
