"""The exact commands each runner builds, run against stub `claude` and `codex`."""

import json
import os

import pytest
from arbiter import runners
from arbiter.config import Task
from arbiter.constants import BUILTIN_DIR
from arbiter.runners.claude import ClaudeRunner

VERDICT = {"ok": True, "summary": "clean", "findings": []}
FAILED = {
    "ok": False,
    "summary": "bad",
    "findings": [{"severity": "high", "file": "a.py", "line": 7, "issue": "boom"}],
}


# -p --settings <file> <base flags> --system-prompt <prompt>
PROMPT = 3 + len(ClaudeRunner.BASE_FLAGS) + 1


def judge(runner, **fields):
    data = {"name": "judge", "runner": runner, "agent": "security-reviewer", **fields}
    task = Task.from_dict(data, "test")
    task.validate()
    return task


@pytest.fixture
def ctx(repo, home):
    scratch = home.root / "scratch"

    def scratch_for(name):
        path = scratch / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    return runners.RunContext(
        root=repo,
        child_env={**os.environ, "ARBITER_CHILD": "1"},
        remaining=lambda: 500,
        scratch_for=scratch_for,
    )


def run(task, ctx):
    return runners.get(task.runner).execute(task, ctx)


def flag_value(argv, flag):
    return argv[argv.index(flag) + 1]


def test_registry():
    assert set(runners.REGISTRY) == {"shell", "claude", "codex"}


def test_claude_command(home, repo, ctx, monkeypatch):
    home.stub("claude")
    envelope = {"type": "result", "result": "```json\n" + json.dumps(FAILED) + "\n```"}
    monkeypatch.setitem(ctx.child_env, "STUB_OUTPUT", json.dumps(envelope))
    verdict = run(judge("claude", model="opus", effort="max"), ctx)

    [call] = home.calls()
    argv = call["argv"]
    scratch = ctx.scratch_for("judge")
    flags = list(ClaudeRunner.BASE_FLAGS)
    assert argv == [
        "-p",
        "--settings",
        str(scratch / "settings.json"),
        *flags,
        "--system-prompt",
        argv[PROMPT],
        "--model",
        "opus",
        "--effort",
        "max",
    ]
    assert flags == [
        "--output-format",
        "json",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--permission-mode",
        "auto",
    ]
    assert "--add-dir" not in argv
    assert call["cwd"] == os.path.realpath(scratch)
    assert call["child"] == "1"
    assert call["stdin"] == "Review the current change set and return your verdict JSON."

    prompt = argv[PROMPT]
    assert prompt.startswith("You are reviewing a code change as an independent judge.")
    assert f"Repository under review: {repo}" in prompt
    assert f"Scratch directory: {scratch}" in prompt
    assert "# Security reviewer" in prompt
    assert prompt.index("# Security reviewer") < prompt.index("# Output style")
    assert "You are rendering a verdict on a code change" in prompt
    assert "name: verdict" not in prompt

    settings = json.loads((scratch / "settings.json").read_text())
    assert settings == {
        "sandbox": {
            "enabled": True,
            "allowUnsandboxedCommands": False,
            "filesystem": {"denyWrite": [str(repo)], "allowWrite": [str(scratch)]},
        },
        "permissions": {"deny": [f"Edit(/{repo}/**)"], "defaultMode": "auto"},
        "outputStyle": "default",
    }
    assert settings["permissions"]["deny"][0].startswith("Edit(//")

    assert not verdict.ok
    assert verdict.summary == "bad"
    assert [(f.severity, f.location, f.issue) for f in verdict.findings] == [
        ("high", "a.py:7", "boom")
    ]


def test_claude_defaults_omit_model_and_effort(home, ctx, monkeypatch):
    home.stub("claude")
    monkeypatch.setitem(ctx.child_env, "STUB_OUTPUT", json.dumps({"result": json.dumps(VERDICT)}))
    assert run(judge("claude"), ctx).ok
    argv = home.calls()[0]["argv"]
    assert "--model" not in argv
    assert "--effort" not in argv


def test_claude_output_style_can_be_replaced_or_dropped(home, repo, ctx, monkeypatch):
    home.stub("claude")
    monkeypatch.setitem(ctx.child_env, "STUB_OUTPUT", json.dumps({"result": json.dumps(VERDICT)}))
    style = repo / ".arbiter" / "output-styles" / "terse.md"
    style.parent.mkdir(parents=True)
    style.write_text("---\nname: terse\n---\nBe terse.\n")
    run(judge("claude", output_style="terse"), ctx)
    run(judge("claude", output_style=""), ctx)
    first, second = (call["argv"][PROMPT] for call in home.calls())
    assert first.endswith("# Output style\n\nBe terse.")
    assert "# Output style" not in second


def test_claude_failure_carries_stderr(home, ctx, monkeypatch):
    home.stub("claude")
    monkeypatch.setitem(ctx.child_env, "STUB_STATUS", "1")
    monkeypatch.setitem(ctx.child_env, "STUB_STDERR", "Not logged in")
    verdict = run(judge("claude"), ctx)
    assert not verdict.ok
    assert verdict.summary == "claude exited 1"
    assert verdict.findings[0].issue == "Not logged in"


def test_claude_unparsable_output_fails(home, ctx, monkeypatch):
    home.stub("claude")
    monkeypatch.setitem(ctx.child_env, "STUB_OUTPUT", json.dumps({"result": "looks fine to me"}))
    verdict = run(judge("claude"), ctx)
    assert (verdict.ok, verdict.summary) == (False, "claude returned no parsable verdict")


def test_codex_command(home, repo, ctx, monkeypatch):
    home.stub("codex")
    monkeypatch.setitem(ctx.child_env, "STUB_VERDICT", json.dumps(VERDICT))
    verdict = run(judge("codex", model="gpt-x", effort="minimal"), ctx)

    [call] = home.calls()
    scratch = ctx.scratch_for("judge")
    assert call["argv"] == [
        "exec",
        "--sandbox",
        "workspace-write",
        "--cd",
        str(scratch),
        "--skip-git-repo-check",
        "--ephemeral",
        "-o",
        str(scratch / "verdict.json"),
        "--output-schema",
        str(BUILTIN_DIR / "schema" / "verdict.schema.json"),
        "-m",
        "gpt-x",
        "-c",
        'model_reasoning_effort="minimal"',
    ]
    assert call["cwd"] == os.path.realpath(scratch)
    assert call["child"] == "1"
    assert call["stdin"].startswith("You are reviewing a code change as an independent judge.")
    assert f"Repository under review: {repo}" in call["stdin"]
    assert "# Security reviewer" in call["stdin"]
    assert "# Output style" not in call["stdin"]
    assert verdict.ok
    assert verdict.summary == "clean"


def test_codex_uses_a_user_schema_override(home, ctx, monkeypatch):
    home.stub("codex")
    monkeypatch.setitem(ctx.child_env, "STUB_VERDICT", json.dumps(VERDICT))
    schema = home.config / "schema" / "verdict.schema.json"
    schema.parent.mkdir(parents=True)
    schema.write_text("{}")
    run(judge("codex"), ctx)
    argv = home.calls()[0]["argv"]
    assert flag_value(argv, "--output-schema") == str(schema)
    assert "-m" not in argv
    assert "-c" not in argv


def test_codex_falls_back_to_stdout_then_to_the_exit_status(home, ctx, monkeypatch):
    home.stub("codex")
    monkeypatch.setitem(ctx.child_env, "STUB_OUTPUT", "noise " + json.dumps(FAILED))
    assert run(judge("codex"), ctx).summary == "bad"

    monkeypatch.setitem(ctx.child_env, "STUB_OUTPUT", "")
    monkeypatch.setitem(ctx.child_env, "STUB_STATUS", "3")
    monkeypatch.setitem(ctx.child_env, "STUB_STDERR", "auth error")
    verdict = run(judge("codex"), ctx)
    assert (verdict.ok, verdict.summary) == (False, "codex exited 3")
    assert verdict.findings[0].issue == "auth error"


def test_missing_judge_cli_fails_the_gate(home, ctx):
    from arbiter.engine import Engine

    verdict = Engine._execute_one(judge("codex"), ctx)
    assert not verdict.ok
    assert verdict.summary.startswith("runner error: FileNotFoundError")


def test_unknown_persona_fails_the_gate(home, ctx):
    from arbiter.engine import Engine

    home.stub("claude")
    task = Task.from_dict({"name": "j", "runner": "claude", "agent": "nobody"}, "test")
    verdict = Engine._execute_one(task, ctx)
    assert not verdict.ok
    assert "agent 'nobody' not found" in verdict.summary
    assert home.calls() == []


def test_shell_runs_in_the_repo_with_the_child_guard(repo, ctx):
    task = Task.from_dict(
        {"name": "sh", "runner": "shell", "command": 'pwd; echo "child=$ARBITER_CHILD"; exit 4'},
        "test",
    )
    verdict = run(task, ctx)
    assert (verdict.ok, verdict.summary) == (False, "exit 4")
    assert verdict.findings[0].issue == f"{os.path.realpath(repo)}\nchild=1"
    ok = Task.from_dict({"name": "ok", "runner": "shell", "command": "true"}, "test")
    assert run(ok, ctx).ok


def test_shell_timeout_fails(ctx):
    task = Task.from_dict({"name": "t", "runner": "shell", "command": "sleep 5", "timeout": 1}, "")
    verdict = run(task, ctx)
    assert (verdict.ok, verdict.summary) == (False, "timed out after 1s")


@pytest.mark.parametrize("runner", ["shell", "claude", "codex"])
def test_an_exhausted_budget_spawns_nothing(home, ctx, runner):
    home.stub("claude")
    home.stub("codex")
    ctx.remaining = lambda: 0
    fields = {"command": "true"} if runner == "shell" else {"prompt": "p"}
    task = Task.from_dict({"name": "b", "runner": runner, **fields}, "test")
    verdict = run(task, ctx)
    assert (verdict.ok, verdict.summary) == (False, "engine budget exhausted before task started")
    assert home.calls() == []


def test_timeout_never_outlives_the_budget(ctx):
    task = Task.from_dict({"name": "t", "runner": "shell", "command": "true", "timeout": 300}, "")
    ctx.remaining = lambda: 42
    assert runners.get("shell").budgeted_timeout(task, ctx) == 42
