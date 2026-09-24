import ast
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text):
    return ANSI.sub("", text)


def run_python(script, *args, stdin="", env=None, python=sys.executable):
    return subprocess.run(
        [python, str(SCRIPTS / script), *args],
        input=stdin,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_line1_shows_vim_mode_repo_path_branch_and_changes(sl, repo, sample):
    (repo / "a.txt").write_text("one\nthree\nfour\nfive\n")
    (repo / "sub").mkdir()
    sample["workspace"] = {"current_dir": str(repo / "sub")}
    line = sl.line1(sample, sl.DARK)
    assert plain(line) == (
        f"{sl.ICO_VIM} INSERT  ·  {sl.ICO_GIT} project/sub  ·  {sl.ICO_BRANCH} main  ·  +2 -1"
    )
    assert sl.DARK.vim_insert in line


def test_line1_outside_git_abbreviates_home(sl, home):
    (home / "notes").mkdir()
    assert plain(sl.line1({"cwd": str(home / "notes")}, sl.DARK)) == "~/notes"


def test_line1_leaves_paths_outside_home_alone(sl, home, tmp_path):
    other = tmp_path / "home-other"
    other.mkdir()
    assert plain(sl.line1({"cwd": str(other)}, sl.DARK)) == str(other)


def test_line1_prefers_workspace_dir_over_cwd(sl, repo, home):
    d = {"workspace": {"current_dir": str(repo)}, "cwd": str(home)}
    assert "project" in plain(sl.line1(d, sl.DARK))


def test_line2_shows_model_effort_style_and_context(sl, sample):
    assert plain(sl.line2(sample, sl.DARK)) == (
        f"{sl.ICO_MODEL} Opus 4.7  ·  {sl.ICO_BOLT} {sl.EFFORTS['high'][0]} | "
        f"{sl.ICO_STYLE} Explanatory  ·  {sl.ICO_DB} {sl.CIRCLES[2]} 42%  (84k/200k)"
    )


def test_line2_hides_default_style_and_missing_effort(sl, sample):
    sample["output_style"] = {"name": "default"}
    del sample["effort"]
    assert plain(sl.line2(sample, sl.DARK)).count("·") == 1


@pytest.mark.parametrize(
    ("pct", "colour", "circle"),
    [
        (0, "bar_ok", 0),
        (59, "bar_ok", 2),
        (60, "bar_warn", 2),
        (85, "bar_crit", 3),
        (100, "bar_crit", 4),
    ],
)
def test_context_colour_and_circle(sl, pct, colour, circle):
    line = sl.line2({"context_window": {"used_percentage": pct}}, sl.DARK)
    assert getattr(sl.DARK, colour) + sl.CIRCLES[circle] in line
    assert f"{pct}%" in plain(line)


def test_line3_shows_reset_cost_session_and_weekly(sl, sample):
    assert plain(sl.line3(sample, sl.DARK)) == (
        f"{sl.ICO_CLOCK} 2h 14m  ·  {sl.ICO_DOLLAR} $1.23  24% session  ·  {sl.ICO_CAL}  41% weekly"
    )


def test_line3_zero_cost_shows_session_without_cost(sl, sample):
    sample["cost"]["total_cost_usd"] = 0
    text = plain(sl.line3(sample, sl.DARK))
    assert "$" not in text
    assert f"{sl.ICO_DOLLAR} 24% session" in text


def test_line3_zero_cost_without_limits_falls_back_to_elapsed_time(sl):
    d = {"cost": {"total_cost_usd": 0, "total_duration_ms": 125000}}
    assert plain(sl.line3(d, sl.DARK)) == f"{sl.ICO_CLOCK} 2m 05s"
    d["cost"]["total_duration_ms"] = 3 * 3600 * 1000 + 7 * 60 * 1000
    assert plain(sl.line3(d, sl.DARK)) == f"{sl.ICO_CLOCK} 3h 07m"


def test_line3_small_cost(sl):
    assert plain(sl.line3({"cost": {"total_cost_usd": 0.0421}}, sl.DARK)) == (
        f"{sl.ICO_DOLLAR} $0.042"
    )


def test_line3_five_hour_limit_only(sl, sample):
    del sample["rate_limits"]["seven_day"]
    text = plain(sl.line3(sample, sl.DARK))
    assert "session" in text
    assert "weekly" not in text
    assert text.startswith(f"{sl.ICO_CLOCK} 2h 14m")


def test_line3_seven_day_limit_only(sl, sample):
    del sample["rate_limits"]["five_hour"]
    text = plain(sl.line3(sample, sl.DARK))
    assert text == f"{sl.ICO_DOLLAR} $1.23  ·  {sl.ICO_CAL}  41% weekly"


def test_line3_empty_without_cost_or_limits(sl):
    assert sl.line3({}, sl.DARK) == ""


def test_limit_colours(sl, sample):
    sample["rate_limits"]["five_hour"]["used_percentage"] = 90
    sample["rate_limits"]["seven_day"]["used_percentage"] = 70
    line = sl.line3(sample, sl.DARK)
    assert f"{sl.DARK.bar_crit}90% session" in line
    assert f"{sl.DARK.bar_warn}{sl.ICO_CAL}  70% weekly" in line


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"model": None, "vim": None, "context_window": None, "cost": None, "rate_limits": None},
        {"model": "x", "vim": [], "effort": {"level": None}, "rate_limits": {"five_hour": None}},
        {"context_window": {"used_percentage": "n/a", "context_window_size": None}},
    ],
)
def test_missing_or_malformed_fields_still_render(sl, home, data):
    data["cwd"] = str(home)
    out = plain(sl.render(data, "dark"))
    assert "error" not in out
    assert out.splitlines() == [
        "~",
        f"{sl.ICO_MODEL} {sl.EM_DASH}  ·  {sl.ICO_DB} {sl.CIRCLES[0]} 0%",
    ]


def test_numeric_strings_are_accepted(sl):
    line = sl.line2(
        {"context_window": {"used_percentage": "50", "context_window_size": "1000000"}}, sl.DARK
    )
    assert "50%  (500k/1.0M)" in plain(line)


def test_unknown_effort_and_vim_mode_use_neutral_colour(sl):
    assert sl.DARK.silver + f"{sl.ICO_BOLT} turbo" in sl.effort_badge(sl.DARK, "turbo")
    assert sl.DARK.silver + f"{sl.ICO_VIM} WEIRD" in sl.vim_badge(sl.DARK, "weird")


def test_a_failing_line_is_reported_not_raised(sl, monkeypatch, home):
    def boom(d, p):
        raise RuntimeError("bad input")

    monkeypatch.setattr(sl, "line2", boom)
    lines = plain(sl.render({"cwd": str(home)}, "dark")).splitlines()
    assert lines == ["~", "statusline error: bad input"]


def test_palettes_differ(sl, sample):
    sample["cwd"] = "/"
    dark, light = sl.render(sample, "dark"), sl.render(sample, "light")
    assert sl.DARK.lavender in dark and sl.LIGHT.lavender not in dark
    assert sl.LIGHT.lavender in light and sl.DARK.lavender not in light
    assert plain(dark) == plain(light)


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (NOW.timestamp() + 2 * 3600 + 5 * 60, "2h 05m"),
        ((NOW.timestamp() + 45 * 60) * 1000, "45m"),
        ((NOW + timedelta(minutes=90)).isoformat().replace("+00:00", "Z"), "1h 30m"),
        ("2026-01-01T12:10:00", "10m"),
        (NOW.timestamp() - 60, "now"),
        ("soon", "?"),
        (float("inf"), "?"),
    ],
)
def test_fmt_resets(sl, value, expected):
    assert sl.fmt_resets(value, now=NOW) == expected


@pytest.mark.parametrize(("n", "expected"), [(999, "999"), (84000, "84k"), (1_500_000, "1.5M")])
def test_fmt_tokens(sl, n, expected):
    assert sl.fmt_tokens(n) == expected


def test_main_reads_stdin_and_prints_three_lines(sample, repo, home):
    sample["cwd"] = str(repo)
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "CLAUDE_STATUSLINE_THEME": "dark"}
    result = run_python("statusline.py", stdin=json.dumps(sample), env=env)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert len(lines) == 3
    assert "project" in plain(lines[0])


@pytest.mark.parametrize("stdin", ["", "not json", "[1, 2]", "null"])
def test_main_survives_bad_input(stdin, home):
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "CLAUDE_STATUSLINE_THEME": "dark"}
    result = subprocess.run(
        ["python3", str(SCRIPTS / "statusline.py")],
        input=stdin,
        env=env,
        cwd=home,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert plain(result.stdout).splitlines()[0] == "~"


@pytest.mark.parametrize("script", ["statusline.py", "setup_statusline.py"])
def test_scripts_parse_as_python_39(script):
    source = (SCRIPTS / script).read_text()
    assert source.startswith("#!/usr/bin/env python3\n")
    assert "from __future__ import annotations" in source
    ast.parse(source, feature_version=(3, 9))


def python39():
    for candidate in ("python3.9", "/usr/bin/python3"):
        path = shutil.which(candidate)
        if not path:
            continue
        version = subprocess.run(
            [path, "-c", "import sys; print(sys.version_info[:2] == (3, 9))"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if version == "True":
            return path
    return None


def test_runs_on_python_39(sample, repo, home):
    python = python39()
    if not python:
        pytest.skip("no Python 3.9 interpreter")
    sample["cwd"] = str(repo)
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "CLAUDE_STATUSLINE_THEME": "light"}
    result = run_python("statusline.py", stdin=json.dumps(sample), env=env, python=python)
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) == 3
