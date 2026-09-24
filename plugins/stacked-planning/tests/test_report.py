"""The two reports a human reads: the text table, and the `--explain` trace.

Neither is machine-parsed, so the cases here ask what a reader has to be able to find in
them — the number, the verdict, and the name of the rule that decided a line — rather than
pinning a layout.
"""

import pytest
from census_support import changed, diff_census

GROUP = "[diff_census.groups.production]\nlimit = {{ changed = {0}{1} }}\n"


@pytest.fixture
def traced(census):
    """The `--explain` trace of a hand-built diff."""

    def _traced(body, files, only=None):
        return diff_census.explain_text(census(body, files, trace=True), only)

    return _traced


@pytest.fixture
def text(census):
    return lambda body, files: diff_census.census_text(census(body, files))


# ---------------------------------------------------------------------------
# --explain
# ---------------------------------------------------------------------------


def test_explain_names_the_rule_that_claimed_a_line(traced):
    """The first thing anyone reaches for when a number looks wrong is which rule did it,
    so the outcome alone is not an answer."""
    out = traced(
        GROUP.format(99, "") + "include = [{ ext = ['go'] }, { ext = ['py'] }]\n",
        [changed("src/a.py", ["+one"])],
    )
    assert "include[1]" in out
    assert 'ext="py"' in out


def test_explain_names_the_global_rule_that_exempted_a_file(traced):
    out = traced("", [changed("vendor/lib/thing.go", ["+one"] * 620)])
    assert "builtin" in out
    assert "vendor" in out


def test_explain_reports_lines_matched_for_a_line_level_facet(traced):
    """A rule reading line text is true of some of a file's lines and false of others, so
    the honest answer for the file is how many rather than yes or no."""
    out = traced(
        "[diff_census.matchers.blank]\nreport = true\nrules = [{ content = '^$' }]\n",
        [changed("src/a.py", ["+one", "+", "+", "+four"])],
    )
    assert "2 lines" in out


def test_explain_reports_the_facets_a_rule_had_to_go_on(traced):
    out = traced("", [changed("src/a.py", ["+one"], size=8400, mode="100644")])
    assert "ext=py" in out
    assert "mime=text/x-python" in out
    assert "mode=100644" in out
    assert "8.2KiB" in out


def test_explain_reports_the_counts_the_file_contributed(traced):
    out = traced(
        GROUP.format(99, "") + "include = [{ ext = ['py'] }]\n",
        [changed("src/a.py", ["+one", "+two", "-three"])],
    )
    assert "production +2 -1" in out
    assert "total +2 -1" in out


def test_explain_says_so_when_a_group_excluded_the_line(traced):
    out = traced(
        GROUP.format(99, "") + "include = [{ ext = ['py'] }]\nexclude = [{ dir = ['src'] }]\n",
        [changed("src/a.py", ["+one"])],
    )
    assert "exclude[0]" in out
    assert 'dir="src"' in out


def test_explain_says_an_omitted_include_matches_everything(traced):
    out = traced(GROUP.format(99, ""), [changed("src/a.py", ["+one"])])
    assert "matches every line" in out


def test_explain_reports_the_group_first_match_wins_passed_over(traced):
    """Charging stops at the first group; the trace does not. "Why did `second` get
    nothing" is answerable only if the group that took the line is named beside it."""
    out = traced(
        "overlap = 'first_match_wins'\n"
        "[diff_census.groups.first]\nlimit = { changed = 99 }\n"
        "include = [{ ext = ['py'] }]\n"
        "[diff_census.groups.second]\nlimit = { changed = 99 }\n"
        "include = [{ dir = ['src'] }]\n",
        [changed("src/a.py", ["+one"])],
    )
    assert "first  (1 lines counted)" in out
    assert "second  (0 lines counted)" in out
    assert 'dir="src"' in out


def test_explain_covers_every_file_by_default(traced):
    out = traced("", [changed("src/a.py", ["+one"]), changed("src/b.go", ["+two"])])
    assert "src/a.py" in out and "src/b.go" in out


def test_explain_of_one_path_covers_only_that_file(traced):
    out = traced(
        "", [changed("src/a.py", ["+one"]), changed("src/b.go", ["+two"])], only="src/a.py"
    )
    assert "src/a.py" in out and "src/b.go" not in out


def test_explain_of_a_path_not_in_the_diff_says_so(traced):
    out = traced("", [changed("src/a.py", ["+one"])], only="src/missing.py")
    assert "src/missing.py" in out


def test_explain_reaches_a_file_that_counted_nothing(traced):
    """A rename or a binary counts no line and joins no bucket, which is exactly the
    outcome someone comes to `--explain` to understand."""
    moved = changed("dst.py", [])
    moved.old_path = "src.py"
    out = traced("", [moved], only="dst.py")
    assert "dst.py" in out and "src.py" in out


# ---------------------------------------------------------------------------
# The text report
# ---------------------------------------------------------------------------


def test_the_text_report_carries_the_groups_matchers_and_totals(text):
    out = text(
        "[diff_census.matchers.docs]\nreport = true\nrules = [{ ext = ['md'] }]\n"
        + GROUP.format(99, "")
        + "include = [{ ext = ['py'] }]\n",
        [
            changed("src/a.py", ["+one"]),
            changed("README.md", ["+two"]),
            changed("vendor/x.go", ["+three"]),
        ],
    )
    for expected in ("production", "docs", "total", "unmatched", "exempt"):
        assert expected in out


def test_the_text_report_shows_a_limit_and_its_verdict(text):
    out = text(GROUP.format(400, ", grace = 0.10"), [changed("src/a.py", ["+x"] * 10)])
    assert "400 changed" in out
    assert "ok" in out


def test_the_grace_band_is_reported_prominently(text):
    out = text(GROUP.format(10, ", grace = 0.10"), [changed("src/a.py", ["+x"] * 10)])
    assert "WARN" in out
    assert "grace" in out


def test_a_limit_past_its_band_says_so(text):
    out = text(GROUP.format(10, ", grace = 0.10"), [changed("src/a.py", ["+x"] * 99)])
    assert "OVER" in out


def test_a_comfortable_census_raises_no_banner(text):
    out = text(GROUP.format(400, ""), [changed("src/a.py", ["+x"] * 10)])
    assert "OVER" not in out and "WARN" not in out


def test_the_text_report_attributes_the_exempt_lines(text):
    out = text("", [changed("vendor/x.go", ["+one"] * 5)])
    assert "builtin" in out


def test_the_text_report_carries_the_diagnostics(text):
    out = text("", [changed("src/a.py", ["+one"])])
    assert "diagnostics" in out


def test_a_configuration_warning_reaches_the_text_report(text):
    out = text(
        "[diff_census.groups.g]\nlimit = { changed = 1 }\n"
        "include = [{ ext = ['py'] }]\nexclude = [{ ext = ['py'] }]\n",
        [changed("src/a.py", ["+one"])],
    )
    assert "no line can match" in out


# ---------------------------------------------------------------------------
# Through the command
# ---------------------------------------------------------------------------


def test_format_text_reports_the_table(repo, gate):
    repo.write("src/a.py", "one\ntwo\n")
    repo.commit("work")
    code, out = gate("--format", "text", "--two-dot", "--base", "HEAD~1", config="")
    assert code == 0
    assert "total" in out.out and "{" not in out.out


def test_explain_prints_the_trace_rather_than_the_report(repo, gate):
    repo.write("src/a.py", "one\n")
    repo.commit("work")
    code, out = gate("--explain", "--two-dot", "--base", "HEAD~1", config="")
    assert code == 0
    assert "src/a.py" in out.out and "schema_version" not in out.out


def test_explain_still_reaches_a_verdict(repo, gate):
    repo.write("src/a.py", "".join(f"line {n}\n" for n in range(50)))
    repo.commit("work")
    code, _out = gate(
        "--explain",
        "--two-dot",
        "--base",
        "HEAD~1",
        config="[diff_census.groups.g]\nlimit = { changed = 10 }\n",
    )
    assert code == 1
