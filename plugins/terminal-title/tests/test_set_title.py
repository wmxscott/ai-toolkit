import pytest


def assert_untouched(sandbox, result):
    assert result.stdout == b""
    assert sandbox.calls() == []
    assert not (sandbox.home / ".cache").exists()


@pytest.mark.parametrize(
    "args", [(), ("",), ("\x01\x02\t\n\x1f",)], ids=["none", "empty", "controls"]
)
def test_empty_title_is_a_noop(sandbox, args):
    sandbox.herdr()
    sandbox.tmux()
    sandbox.env["CLAUDE_CODE_SESSION_ID"] = "s1"
    assert_untouched(sandbox, sandbox.run("set_title.sh", *args))


def test_osc_fallback(sandbox):
    result = sandbox.run("set_title.sh", "login bug")
    assert result.stdout == sandbox.osc("login bug")
    assert sandbox.calls() == []


def test_strips_control_characters_and_truncates(sandbox):
    result = sandbox.run("set_title.sh", "log\x1bin\t\x07bug\n" + "x" * 100)
    assert result.stdout == sandbox.osc("loginbug" + "x" * 72)


def test_tmux(sandbox):
    sandbox.tmux(pane="%7")
    result = sandbox.run("set_title.sh", "auth flow")
    assert result.stdout == b""
    assert sandbox.calls() == [
        ["tmux", "set-window-option", "-t", "%7", "automatic-rename", "off"],
        ["tmux", "rename-window", "-t", "%7", "auth flow"],
    ]


def test_tmux_does_not_cache(sandbox):
    sandbox.tmux()
    sandbox.env["CLAUDE_CODE_SESSION_ID"] = "s1"
    sandbox.run("set_title.sh", "auth flow")
    assert not sandbox.cached("s1").exists()


def test_herdr_solo_pane_renames_pane_and_tab(sandbox):
    sandbox.herdr(tab="t1", pane="p1", panes=1)
    sandbox.tmux()
    result = sandbox.run("set_title.sh", "login bug")
    assert result.stdout == b""
    assert sandbox.calls() == [
        ["herdr", "tab", "get", "t1"],
        ["herdr", "pane", "rename", "p1", "login bug"],
        ["herdr", "tab", "rename", "t1", "login bug"],
    ]


def test_herdr_shared_tab_renames_only_the_pane(sandbox):
    sandbox.herdr(tab="t1", pane="p1", panes=3)
    sandbox.run("set_title.sh", "login bug")
    assert sandbox.calls() == [
        ["herdr", "tab", "get", "t1"],
        ["herdr", "pane", "rename", "p1", "login bug"],
    ]


def test_herdr_unreadable_pane_count_counts_as_solo(sandbox):
    sandbox.herdr(tab="t1", pane="p1", panes="garbage")
    sandbox.run("set_title.sh", "login bug")
    assert ["herdr", "tab", "rename", "t1", "login bug"] in sandbox.calls()


def test_herdr_caches_title_per_session(sandbox):
    sandbox.herdr()
    sandbox.env["CLAUDE_CODE_SESSION_ID"] = "s1"
    sandbox.run("set_title.sh", "login\x01 bug")
    assert sandbox.cached("s1").read_text() == "login bug"


def test_herdr_without_session_id_does_not_cache(sandbox):
    sandbox.herdr()
    sandbox.run("set_title.sh", "login bug")
    assert not (sandbox.home / ".cache").exists()


def test_herdr_env_without_herdr_binary_falls_through(sandbox):
    sandbox.env.update(HERDR_TAB_ID="t1", HERDR_PANE_ID="p1")
    sandbox.tmux()
    sandbox.run("set_title.sh", "login bug")
    assert [call[0] for call in sandbox.calls()] == ["tmux", "tmux"]
