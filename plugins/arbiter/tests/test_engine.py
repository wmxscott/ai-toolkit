"""Change set, cache, glob gating, verdict parsing and the CLI subcommands."""

import json

import pytest
from arbiter import cli
from arbiter.config import ConfigLoader, Task
from arbiter.engine import Engine
from arbiter.patterns import matches
from arbiter.repository import Repository
from arbiter.state import State
from arbiter.verdicts import Verdict, extract_json


def engine_for(repo):
    return Engine(Repository(repo), ConfigLoader(repo).load())


def counting_gate(counter, name="count", status=0):
    return (
        f'[[task]]\nname = "{name}"\nrunner = "shell"\n'
        f"command = \"echo run >> '{counter}'; exit {status}\"\n"
    )


def test_change_set_is_the_merge_base_diff_plus_untracked(repo, git):
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "committed.txt").write_text("a\n")
    git(repo, "add", "committed.txt")
    git(repo, "commit", "-q", "--no-gpg-sign", "-m", "c")
    (repo / "README.md").write_text("edited\n")
    (repo / "untracked.txt").write_text("u\n")
    (repo / "ignored.log").write_text("i\n")
    (repo / ".gitignore").write_text("*.log\n")
    state = repo / ".arbiter" / "state"
    state.mkdir(parents=True)
    (state / "x.json").write_text("{}")
    assert Repository(repo).changed_paths == [
        ".gitignore",
        "README.md",
        "committed.txt",
        "untracked.txt",
    ]


def test_on_the_default_branch_only_uncommitted_work_counts(repo):
    assert Repository(repo).changed_paths == []
    (repo / "README.md").write_text("edited\n")
    assert Repository(repo).changed_paths == ["README.md"]


def test_change_hash_follows_content(repo):
    (repo / "a.txt").write_text("one\n")
    first = Repository(repo).change_hash
    assert Repository(repo).change_hash == first
    (repo / "a.txt").write_text("two\n")
    assert Repository(repo).change_hash != first


def test_discover_walks_up_and_returns_none_outside_git(repo, home):
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    assert Repository.discover(sub).root == repo
    outside = home.path / "outside"
    outside.mkdir()
    assert Repository.discover(outside) is None
    assert Repository.discover(home.path / "missing") is None


@pytest.mark.parametrize(
    ("path", "patterns", "expected"),
    [
        ("src/a.py", ["*.py"], False),
        ("a.py", ["*.py"], True),
        ("src/a.py", ["**/*.py"], True),
        ("a.py", ["**/*.py"], True),
        ("src/auth/login.ts", ["**/auth/**"], True),
        ("auth.ts", ["**/auth/**"], False),
        ("migrations/001.sql", ["migrations/**"], True),
        ("a/migrations/001.sql", ["migrations/**"], False),
        ("x1.ts", ["x?.ts"], True),
        ("x12.ts", ["x?.ts"], False),
        ("b.ts", ["[ab].ts"], True),
        ("c.ts", ["[ab].ts"], False),
        ("a+b.txt", ["a+b.txt"], True),
    ],
)
def test_glob_semantics(path, patterns, expected):
    assert matches(path, patterns) is expected


def test_tasks_without_paths_always_apply():
    task = Task.from_dict({"name": "t", "runner": "shell", "command": "true"}, "")
    assert task.applies_to(["anything"])
    assert task.skip_reason(["x"], cached_ok=True) == "cached pass"


def test_run_caches_passes_and_reruns_failures(home, repo, write_config):
    passes, fails = home.root / "passes", home.root / "fails"
    write_config(counting_gate(passes, "pass") + counting_gate(fails, "fail", status=1))

    first = engine_for(repo).run()
    assert [(v.task.name, v.ok, v.cached) for v in first] == [
        ("pass", True, False),
        ("fail", False, False),
    ]
    second = engine_for(repo).run()
    assert [(v.task.name, v.cached) for v in second] == [("pass", True), ("fail", False)]
    assert passes.read_text() == "run\n"
    assert fails.read_text() == "run\nrun\n"

    replay = engine_for(repo).run(reuse_failures=True)
    assert all(v.cached for v in replay)
    assert fails.read_text() == "run\nrun\n"

    engine_for(repo).run(use_cache=False)
    assert passes.read_text() == "run\nrun\n"


def test_editing_a_file_invalidates_the_cache(home, repo, write_config):
    counter = home.root / "runs"
    write_config(counting_gate(counter))
    engine_for(repo).run()
    engine_for(repo).run()
    (repo / "README.md").write_text("changed\n")
    engine_for(repo).run()
    assert counter.read_text() == "run\nrun\n"


def test_only_runs_a_single_task(home, repo, write_config):
    write_config(counting_gate(home.root / "a", "a") + counting_gate(home.root / "b", "b"))
    assert [v.task.name for v in engine_for(repo).run(only="b")] == ["b"]
    assert not (home.root / "a").exists()


def test_cache_does_not_persist_required(home, repo, write_config):
    write_config(counting_gate(home.root / "x", status=1))
    engine = engine_for(repo)
    engine.run()
    cached = engine.state.load_verdicts(engine.change_hash)
    assert set(cached["count"]) == {"ok", "summary", "findings"}


def test_block_counter(repo):
    state = State(repo)
    assert [state.record_block("h") for _ in range(3)] == [1, 2, 3]
    assert state.record_block("other") == 1
    state.clear_blocks()
    assert state.record_block("other") == 1


def test_scratch_lives_under_the_state_home(home, repo):
    scratch = State(repo).scratch_for("hash", "task")
    assert scratch.is_dir()
    assert scratch.is_relative_to(home.state / "scratch")
    assert not scratch.is_relative_to(repo)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"ok": true}', {"ok": True}),
        ('prose ```json\n{"ok": false, "summary": "x"}\n``` more', {"ok": False, "summary": "x"}),
        (
            'lead {"ok": true, "findings": [{"a": {"b": 1}}]} trail',
            {"ok": True, "findings": [{"a": {"b": 1}}]},
        ),
        ("no json here", None),
        ("", None),
        ('{broken {"ok": true}', {"ok": True}),
    ],
)
def test_extract_json(text, expected):
    assert extract_json(text) == expected


def test_verdict_without_ok_fails():
    task = Task.from_dict({"name": "t", "runner": "shell", "command": "true"}, "")
    verdict = Verdict.from_payload(task, {"summary": "hi"}, "fallback")
    assert (verdict.ok, verdict.summary) == (False, "fallback")
    assert verdict.blocks
    task.required = False
    assert not verdict.blocks


def main(*argv):
    return cli.main(list(argv))


def test_run_exit_codes(home, repo, write_config, capsys):
    assert main("run") == 0
    assert "no configuration found" in capsys.readouterr().out
    write_config(counting_gate(home.root / "x"))
    assert main("run") == 0
    assert "all required gates passed" in capsys.readouterr().out
    write_config(counting_gate(home.root / "x", status=1))
    assert main("run") == 2
    write_config('[[task]]\nname = "x"\n')
    assert main("run") == 2
    assert "arbiter:" in capsys.readouterr().err


def test_plan_explains_each_task(home, repo, write_config, capsys):
    write_config(
        counting_gate(home.root / "x")
        + '[[task]]\nname = "py"\nrunner = "shell"\ncommand = "true"\npaths = ["**/*.py"]\n'
    )
    assert main("plan") == 0
    out = capsys.readouterr().out
    assert "security" in out and "disabled" in out
    assert "no path match (**/*.py)" in out
    assert "would run" in out


def test_status_shows_cached_verdicts(home, repo, write_config, capsys):
    write_config(counting_gate(home.root / "x"))
    main("status")
    assert "no cached verdicts" in capsys.readouterr().out
    main("run")
    capsys.readouterr()
    main("status")
    out = capsys.readouterr().out
    assert json.loads(out.split(":\n", 1)[1])["count"]["ok"] is True


def test_init_lists_and_writes_to_the_repo_root(home, repo, monkeypatch, capsys):
    assert main("init") == 0
    assert "typescript" in capsys.readouterr().out

    sub = repo / "pkg"
    sub.mkdir()
    monkeypatch.chdir(sub)
    assert main("init", "typescript") == 0
    written = (repo / "arbiter.toml").read_text()
    assert written.startswith("# arbiter — TypeScript project template")
    assert not (sub / "arbiter.toml").exists()

    assert main("init", "typescript") == 2
    assert "already exists" in capsys.readouterr().err
    (repo / "arbiter.toml").write_text("mine")
    assert main("init", "typescript", "--force") == 0
    assert (repo / "arbiter.toml").read_text() == written

    assert main("init", "cobol") == 2
    assert "available: typescript" in capsys.readouterr().err


def test_a_user_template_joins_and_shadows_the_builtin(home, repo, capsys):
    templates = home.config / "templates"
    templates.mkdir(parents=True)
    (templates / "typescript.toml").write_text("# mine\n")
    (templates / "rust.toml").write_text("# rust\n")
    main("init")
    assert capsys.readouterr().out.splitlines()[1:3] == ["  rust", "  typescript"]
    main("init", "typescript")
    assert (repo / "arbiter.toml").read_text() == "# mine\n"


def test_the_typescript_template_loads(repo):
    assert main("init", "typescript") == 0
    names = [t.name for t in ConfigLoader(repo).load().tasks if t.enabled]
    assert names == [
        "typecheck",
        "lint",
        "test",
        "sast",
        "sca-secrets",
        "cloudformation-bundle-size",
        "security-review",
        "scalability-review",
        "codex-review",
    ]


def test_clean_removes_state_and_scratch(home, repo, write_config, capsys):
    write_config(counting_gate(home.root / "x"))
    engine = engine_for(repo)
    engine.run()
    engine.state.scratch_for(engine.change_hash, "t")
    assert main("clean") == 0
    assert not (repo / ".arbiter").exists()
    assert not engine.state.scratch_root.exists()
    assert main("clean") == 0
    assert "nothing to clean" in capsys.readouterr().out


def test_clean_refuses_a_symlinked_state_dir(home, repo, capsys):
    target = home.path / "precious"
    target.mkdir()
    (target / "keep").write_text("x")
    (repo / ".arbiter").symlink_to(target)
    assert main("clean") == 2
    assert "symlink" in capsys.readouterr().err
    assert (target / "keep").exists()
