import re

import pytest

PLACEHOLDER = re.compile(r"([a-z]+) ([a-z]+) ([a-z]+)")


def session_start(session_id="s1", source="startup", **extra):
    return {"hook_event_name": "SessionStart", "session_id": session_id, "source": source, **extra}


def test_prime_sets_a_random_placeholder(sandbox):
    titles = set()
    for _ in range(20):
        out = sandbox.run("prime_title.sh", stdin=session_start()).stdout
        assert out.startswith(b"\x1b]0;")
        assert out.endswith(b"\x07")
        title = out[4:-1].decode()
        first, second, _ = PLACEHOLDER.fullmatch(title).groups()
        assert first != second
        titles.add(title)
    assert len(titles) > 1


def test_prime_backs_off_when_session_has_a_title(sandbox):
    cache = sandbox.cached("s1")
    cache.parent.mkdir(parents=True)
    cache.write_text("login bug")
    sandbox.herdr()
    result = sandbox.run("prime_title.sh", stdin=session_start(source="compact"))
    assert result.stdout == b""
    assert sandbox.calls() == []


def test_prime_and_restore_round_trip(sandbox):
    sandbox.herdr(tab="t1", pane="p1")
    sandbox.env["CLAUDE_CODE_SESSION_ID"] = "s1"

    sandbox.run("prime_title.sh", stdin=session_start())
    placeholder = sandbox.cached("s1").read_text()
    assert PLACEHOLDER.fullmatch(placeholder)

    sandbox.run("set_title.sh", "login bug")
    assert sandbox.cached("s1").read_text() == "login bug"

    sandbox.clear_calls()
    sandbox.run("prime_title.sh", stdin=session_start(source="clear"))
    assert sandbox.calls() == []

    sandbox.env.update(HERDR_TAB_ID="t2", HERDR_PANE_ID="p9")
    sandbox.run("restore_title.sh", stdin=session_start(source="resume"))
    assert sandbox.calls() == [
        ["herdr", "tab", "get", "t2"],
        ["herdr", "pane", "rename", "p9", "login bug"],
        ["herdr", "tab", "rename", "t2", "login bug"],
    ]


@pytest.mark.parametrize(
    "case",
    ["not-session-start", "subagent", "no-session-id", "no-cache", "no-herdr-env", "no-herdr"],
)
def test_restore_noops(sandbox, case):
    stdin = session_start(source="resume")
    sandbox.herdr()
    cache = sandbox.cached("s1")
    cache.parent.mkdir(parents=True)
    cache.write_text("login bug")

    if case == "not-session-start":
        stdin["hook_event_name"] = "UserPromptSubmit"
    elif case == "subagent":
        stdin["agent_id"] = "agent-1"
    elif case == "no-session-id":
        del stdin["session_id"]
    elif case == "no-cache":
        cache.unlink()
    elif case == "no-herdr-env":
        del sandbox.env["HERDR_TAB_ID"]
    elif case == "no-herdr":
        (sandbox.bin / "herdr").unlink()

    result = sandbox.run("restore_title.sh", stdin=stdin)
    assert result.stdout == b""
    assert sandbox.calls() == []
