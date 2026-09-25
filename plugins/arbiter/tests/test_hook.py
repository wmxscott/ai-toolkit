"""The Stop hook, driven exactly as Claude Code runs it: the command from hooks.json
under /bin/sh, with the hook payload on stdin and an environment built from scratch.

Claude Code's Stop-hook contract: exit 0 with a JSON object on stdout. `{}` lets the
turn end, `{"decision": "block", "reason": ...}` holds it open and hands the reason
to Claude, and `systemMessage` is shown to the user. Arbiter never uses exit 2."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from arbiter.constants import BLOCK_LIMIT, ENGINE_BUDGET, HOOK_TIMEOUT

PLUGIN = Path(__file__).resolve().parent.parent
HOOKS = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
[STOP] = HOOKS["hooks"]["Stop"]
[HOOK] = STOP["hooks"]
ALLOWED_KEYS = {"decision", "reason", "systemMessage"}

FAILING_GATE = """
[[task]]
name = "lint"
runner = "shell"
command = "echo lint broke; exit 1"
"""


def run_hook(home, cwd, *, payload=None, env=None, stdin=None):
    """Run the hook and check the contract every outcome must meet."""
    full_env = {**home.env(), "CLAUDE_PLUGIN_ROOT": str(PLUGIN)}
    full_env.setdefault("ARBITER_PYTHON", sys.executable)
    full_env["ARBITER_FALLBACK_PATH"] = ""
    full_env.update(env or {})
    if stdin is None:
        body = {"session_id": "s", "hook_event_name": "Stop", "stop_hook_active": False}
        body.update(payload if payload is not None else {"cwd": str(cwd)})
        stdin = json.dumps(body)
    result = subprocess.run(
        ["/bin/sh", "-c", HOOK["command"]],
        input=stdin,
        cwd=cwd,
        env={k: v for k, v in full_env.items() if v is not None},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.endswith("\n")
    assert result.stdout.count("\n") == 1, result.stdout
    decision = json.loads(result.stdout)
    assert isinstance(decision, dict)
    assert set(decision) <= ALLOWED_KEYS
    if "decision" in decision:
        assert decision["decision"] == "block"
        assert decision["reason"].strip()
    else:
        assert "reason" not in decision
    return decision


def test_hooks_json_registers_one_stop_hook():
    assert set(HOOKS["hooks"]) == {"Stop"}
    assert "matcher" not in STOP
    assert HOOK["type"] == "command"
    assert HOOK["command"] == 'bash "${CLAUDE_PLUGIN_ROOT}/bin/arbiter" hook'
    assert HOOK["timeout"] == HOOK_TIMEOUT == 600
    assert ENGINE_BUDGET < HOOK_TIMEOUT
    assert HOOKS["description"].startswith("EXPERIMENTAL:")


def test_no_config_is_a_silent_no_op(home, repo):
    (repo / "new.py").write_text("x = 1\n")
    assert run_hook(home, repo) == {}
    assert not (repo / ".arbiter").exists()
    assert not home.state.exists()


def test_outside_a_repository_is_a_silent_no_op(home):
    plain = home.path / "plain"
    plain.mkdir()
    (plain / "arbiter.toml").write_text(FAILING_GATE)
    assert run_hook(home, plain) == {}


def test_nonexistent_cwd_is_a_silent_no_op(home, repo):
    assert run_hook(home, repo, payload={"cwd": str(home.path / "gone")}) == {}


@pytest.mark.parametrize("stdin", ["", "not json", "[1, 2]", '{"cwd": 3}', '{"cwd": "rel"}'])
def test_unusable_payload_falls_back_to_the_process_cwd(home, repo, write_config, stdin):
    write_config(FAILING_GATE)
    decision = run_hook(home, repo, stdin=stdin)
    assert decision["decision"] == "block"


def test_payload_cwd_wins_over_the_process_cwd(home, repo, write_config):
    write_config(FAILING_GATE)
    elsewhere = home.path / "elsewhere"
    elsewhere.mkdir()
    assert run_hook(home, elsewhere, payload={"cwd": str(repo)})["decision"] == "block"


def test_recursion_guard(home, repo, write_config):
    write_config(FAILING_GATE)
    assert run_hook(home, repo, env={"ARBITER_CHILD": "1"}) == {}
    assert not (repo / ".arbiter").exists()


def test_a_failing_required_gate_blocks_with_its_output(home, repo, write_config):
    write_config(FAILING_GATE)
    decision = run_hook(home, repo)
    assert decision["reason"].startswith("arbiter: 1 required gate(s) failed (attempt 1/3)")
    assert "FAIL  lint" in decision["reason"]
    assert "lint broke" in decision["reason"]
    assert (repo / ".arbiter" / ".gitignore").read_text() == "*\n"


def test_passing_gates_let_the_turn_end(home, repo, write_config):
    write_config('[[task]]\nname = "ok"\nrunner = "shell"\ncommand = "true"\n')
    assert run_hook(home, repo) == {}


def test_an_advisory_failure_never_blocks(home, repo, write_config):
    write_config(FAILING_GATE + "required = false\n")
    assert run_hook(home, repo) == {}


def test_disabled_and_unmatched_gates_are_a_no_op(home, repo, write_config):
    write_config(
        FAILING_GATE
        + "enabled = false\n"
        + '[[task]]\nname = "py"\nrunner = "shell"\ncommand = "false"\npaths = ["**/*.py"]\n'
    )
    assert run_hook(home, repo) == {}


def test_no_changes_is_a_no_op(home, repo, write_config, git):
    write_config(FAILING_GATE)
    git(repo, "add", "arbiter.toml")
    git(repo, "commit", "-q", "--no-gpg-sign", "-m", "config")
    assert run_hook(home, repo) == {}


def test_changes_committed_on_a_branch_are_gated(home, repo, write_config, git):
    git(repo, "checkout", "-q", "-b", "feature")
    write_config(FAILING_GATE)
    git(repo, "add", "arbiter.toml")
    git(repo, "commit", "-q", "--no-gpg-sign", "-m", "config")
    assert run_hook(home, repo)["decision"] == "block"


def test_loop_guard_releases_an_unchanged_tree_and_resets(home, repo, write_config):
    write_config(FAILING_GATE)
    for attempt in range(1, BLOCK_LIMIT):
        decision = run_hook(home, repo)
        assert f"(attempt {attempt}/{BLOCK_LIMIT})" in decision["reason"]
    released = run_hook(home, repo)
    assert released["systemMessage"].startswith(
        f"arbiter: released after {BLOCK_LIMIT} consecutive blocks"
    )
    assert "lint broke" in released["systemMessage"]
    assert "(attempt 1/3)" in run_hook(home, repo)["reason"]


def test_an_edit_restarts_the_attempt_count(home, repo, write_config):
    write_config(FAILING_GATE)
    run_hook(home, repo)
    run_hook(home, repo)
    (repo / "fix.txt").write_text("attempt\n")
    assert "(attempt 1/3)" in run_hook(home, repo)["reason"]


def test_an_idle_turn_replays_the_cached_failure(home, repo, write_config):
    counter = home.root / "runs"
    write_config(
        f'[[task]]\nname = "count"\nrunner = "shell"\n'
        f"command = \"echo run >> '{counter}'; exit 1\"\n"
    )
    run_hook(home, repo)
    second = run_hook(home, repo)
    assert "count (cached)" in second["reason"]
    assert counter.read_text() == "run\n"


def test_invalid_config_blocks_then_releases(home, repo, write_config):
    write_config('[[task]]\nname = "x"\nrunner = "bash"\n')
    first = run_hook(home, repo)
    assert first["reason"].startswith("arbiter: invalid configuration (attempt 1/3)")
    assert "runner must be one of" in first["reason"]
    run_hook(home, repo)
    assert "runner must be one of" in run_hook(home, repo)["systemMessage"]


def test_an_internal_error_warns_and_never_blocks(home, repo, write_config):
    write_config(FAILING_GATE)
    (repo / ".arbiter").write_text("a file where the state directory goes")
    decision = run_hook(home, repo)
    assert decision["systemMessage"].startswith("arbiter: internal error, this turn was not gated")


def test_hook_gates_with_a_stub_codex_judge(home, repo, write_config):
    home.stub("codex")
    write_config('[[task]]\nname = "sec"\nrunner = "codex"\nagent = "security-reviewer"\n')
    verdict = {
        "ok": False,
        "summary": "injection",
        "findings": [{"severity": "high", "file": "db.py", "line": 3, "issue": "raw SQL"}],
    }
    decision = run_hook(home, repo, env={"STUB_VERDICT": json.dumps(verdict)})
    assert "FAIL  sec  injection" in decision["reason"]
    assert "high db.py:3: raw SQL" in decision["reason"]
    [call] = home.calls()
    assert call["child"] == "1"


def minimal_path(home) -> str:
    """A PATH holding only the tools the launcher needs, and no Python."""
    tools = home.root / "tools"
    tools.mkdir(exist_ok=True)
    for name in ("bash", "cat", "dirname", "readlink", "git"):
        found = shutil.which(name, path="/usr/bin:/bin")
        assert found, name
        target = tools / name
        if not target.exists():
            target.symlink_to(found)
    return str(tools)


@pytest.mark.parametrize("configured", [False, True])
def test_without_python_the_hook_never_blocks(home, repo, write_config, configured):
    if configured:
        write_config(FAILING_GATE)
    env = {"ARBITER_PYTHON": None, "PATH": minimal_path(home)}
    decision = run_hook(home, repo, env=env)
    if configured:
        assert decision == {
            "systemMessage": "arbiter: needs Python 3.11 or later, or uv; this turn was not gated"
        }
    else:
        assert decision == {}


def test_launcher_finds_python_on_path(home, repo, write_config):
    write_config(FAILING_GATE)
    tools = minimal_path(home)
    os.symlink(sys.executable, Path(tools) / "python3")
    decision = run_hook(home, repo, env={"ARBITER_PYTHON": None, "PATH": tools})
    assert decision["decision"] == "block"


def test_launcher_skips_an_unusable_python(home, repo, write_config):
    write_config(FAILING_GATE)
    tools = Path(minimal_path(home))
    old = tools / "python3.11"
    old.write_text("#!/bin/sh\nexit 1\n")
    old.chmod(0o755)
    os.symlink(sys.executable, tools / "python3")
    decision = run_hook(home, repo, env={"ARBITER_PYTHON": None, "PATH": str(tools)})
    assert decision["decision"] == "block"


def test_neither_pythonpath_nor_the_repository_shadows_a_module(home, repo, write_config):
    write_config(FAILING_GATE)
    (repo / "json.py").write_text("raise SystemExit('decoy imported')\n")
    decision = run_hook(home, repo, env={"PYTHONPATH": str(repo)})
    assert decision["decision"] == "block"
