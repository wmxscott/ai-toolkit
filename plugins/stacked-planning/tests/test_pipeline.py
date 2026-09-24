"""The classification pipeline, the report it produces, and the verdict a limit reaches.

Every case builds its diff by hand, because the pipeline takes what it is given and asks
git for nothing — which is what lets a case name the exact lines it is about. The cases
about exit codes go through `main`, since the exit code is the contract callers consume.
"""

import json

import pytest
from census_support import changed, diff_census

PY = "[diff_census.groups.g]\nlimit = {{ changed = {0} }}\n"


# ---------------------------------------------------------------------------
# Global exclusion is terminal
# ---------------------------------------------------------------------------


def test_an_excluded_line_is_exempt_and_nothing_else(census):
    """The whole point of terminal: an excluded line is invisible to every matcher and
    every group, so `total` and `exempt` partition the diff between them."""
    taken = census(
        "[diff_census.matchers.m]\nreport = true\nrules = [{ path = ['**'] }]\n"
        "[diff_census.groups.g]\nlimit = { changed = 10 }\n",
        [changed("vendor/lib/thing.go", ["+one", "+two", "-three"])],
    )
    assert (taken.exempt.adds, taken.exempt.dels) == (2, 1)
    assert taken.total.changed == 0
    assert taken.groups["g"].changed == 0
    assert taken.matchers["m"].changed == 0
    assert taken.unmatched.changed == 0


def test_the_builtin_list_is_attributed_under_its_own_name(census):
    taken = census("", [changed("node_modules/x.js", ["+a"])])
    assert taken.by_rule["builtin"].changed == 1


def test_exempt_lines_are_attributed_to_the_rule_that_caught_them(census):
    taken = census(
        "[diff_census.global]\nextend_builtin = false\n"
        "exclude = [{ ext = ['lock'] }, { path = ['third_party/**'] }]\n",
        [changed("a.lock", ["+one", "+two"]), changed("third_party/b.py", ["-three"])],
    )
    assert taken.by_rule["global[0]"].changed == 2
    assert taken.by_rule["global[1]"].changed == 1


def test_only_the_first_matching_global_rule_is_charged(census):
    taken = census(
        "[diff_census.global]\nextend_builtin = false\n"
        "exclude = [{ ext = ['py'] }, { path = ['src/**'] }]\n",
        [changed("src/a.py", ["+one"])],
    )
    assert taken.by_rule["global[0]"].changed == 1
    assert "global[1]" not in taken.by_rule
    assert taken.exempt.changed == 1


def test_a_global_rule_that_caught_nothing_has_no_entry(census, report):
    body = "[diff_census.global]\nextend_builtin = false\nexclude = [{ ext = ['lock'] }]\n"
    taken = census(body, [changed("src/a.py", ["+one"])])
    assert taken.by_rule == {}
    assert report(body, [changed("src/a.py", ["+one"])])["totals"]["exempt"]["by_rule"] == {}


def test_a_line_level_global_rule_excludes_only_the_lines_it_matches(census):
    taken = census(
        "[diff_census.global]\nextend_builtin = false\nexclude = [{ content = '^\\s*$' }]\n",
        [changed("src/a.py", ["+code", "+", "+  "])],
    )
    assert (taken.exempt.changed, taken.total.changed) == (2, 1)


# ---------------------------------------------------------------------------
# total, matchers, groups, unmatched
# ---------------------------------------------------------------------------


def test_every_line_that_is_not_exempt_counts_toward_total(census):
    taken = census("", [changed("src/a.py", ["+one", "-two"]), changed("vendor/b.py", ["+three"])])
    assert (taken.total.adds, taken.total.dels, taken.total.changed) == (1, 1, 2)


def test_a_line_no_group_and_no_matcher_claims_is_unmatched(census):
    taken = census(
        PY.format(10) + "include = [{ ext = ['go'] }]\n", [changed("src/a.py", ["+one", "+two"])]
    )
    assert taken.unmatched.changed == 2
    assert taken.groups["g"].changed == 0


def test_a_line_a_reported_matcher_claims_is_not_unmatched(census):
    taken = census(
        "[diff_census.matchers.docs]\nreport = true\nrules = [{ ext = ['md'] }]\n",
        [changed("README.md", ["+one"])],
    )
    assert taken.matchers["docs"].changed == 1
    assert taken.unmatched.changed == 0


def test_a_matcher_that_is_not_reported_claims_nothing(census):
    """A matcher without `report` is a definition, not a bucket. It has no counts, and a
    line it happens to match is still unclaimed."""
    taken = census(
        "[diff_census.matchers.docs]\nrules = [{ ext = ['md'] }]\n",
        [changed("README.md", ["+one"])],
    )
    assert "docs" not in taken.matchers
    assert taken.unmatched.changed == 1


def test_a_line_a_group_claims_is_not_unmatched(census):
    taken = census(
        PY.format(10) + "include = [{ ext = ['py'] }]\n", [changed("src/a.py", ["+one"])]
    )
    assert (taken.groups["g"].changed, taken.unmatched.changed) == (1, 0)


def test_files_counts_the_files_contributing_a_line_to_the_bucket(census):
    taken = census(
        "",
        [
            changed("a.py", ["+one", "+two"]),
            changed("b.py", ["-three"]),
            changed("c.go", ["+four"]),
        ],
    )
    assert taken.total.files == 3
    assert taken.exempt.files == 0


def test_a_file_with_nothing_to_count_joins_no_bucket(census):
    """A binary, a gitlink and a bare rename count zero lines, so they contribute no file
    to any bucket rather than an empty one."""
    binary = changed("logo.png", [])
    binary.binary = True
    taken = census("", [binary, changed("moved.py", [])])
    assert (taken.total.files, taken.total.changed) == (0, 0)


# ---------------------------------------------------------------------------
# Overlap
# ---------------------------------------------------------------------------

TWO_GROUPS = (
    "[diff_census.groups.first]\nlimit = {{ changed = 99 }}\ninclude = [{{ {0} }}]\n"
    "[diff_census.groups.second]\nlimit = {{ changed = 99 }}\ninclude = [{{ {1} }}]\n"
)


def test_multi_charges_every_group_a_line_matches(census):
    taken = census(
        TWO_GROUPS.format("ext = ['py']", "dir = ['src']"), [changed("src/a.py", ["+one", "+two"])]
    )
    assert taken.groups["first"].changed == 2
    assert taken.groups["second"].changed == 2
    assert taken.total.changed == 2  # group counts may sum above the total


def test_first_match_wins_charges_at_most_one_group(census):
    taken = census(
        "overlap = 'first_match_wins'\n" + TWO_GROUPS.format("ext = ['py']", "dir = ['src']"),
        [changed("src/a.py", ["+one", "+two"])],
    )
    assert (taken.groups["first"].changed, taken.groups["second"].changed) == (2, 0)


def test_first_match_wins_follows_declaration_order(census):
    """The same two groups, declared the other way round, charge the other one — which is
    the whole of what declaration order means here."""
    taken = census(
        "overlap = 'first_match_wins'\n" + TWO_GROUPS.format("dir = ['src']", "ext = ['py']"),
        [changed("src/a.py", ["+one"])],
    )
    assert (taken.groups["first"].changed, taken.groups["second"].changed) == (1, 0)


def test_first_match_wins_still_leaves_the_line_claimed(census):
    taken = census(
        "overlap = 'first_match_wins'\n" + TWO_GROUPS.format("ext = ['py']", "dir = ['src']"),
        [changed("src/a.py", ["+one"])],
    )
    assert taken.unmatched.changed == 0


def test_matchers_are_evaluated_in_full_under_first_match_wins(census):
    """The overlap policy budgets groups. Matchers are observational, so both of them
    count the line however the groups were charged."""
    taken = census(
        "overlap = 'first_match_wins'\n"
        "[diff_census.matchers.one]\nreport = true\nrules = [{ ext = ['py'] }]\n"
        "[diff_census.matchers.two]\nreport = true\nrules = [{ dir = ['src'] }]\n"
        + TWO_GROUPS.format("ext = ['py']", "dir = ['src']"),
        [changed("src/a.py", ["+one"])],
    )
    assert taken.matchers["one"].changed == taken.matchers["two"].changed == 1


def test_unmatched_is_the_same_under_either_policy(census):
    """Whether a line is claimed does not depend on how many groups charged it, so the
    coverage metric reads the same either way."""
    files = [changed("src/a.py", ["+one"]), changed("other.go", ["+two"])]
    body = TWO_GROUPS.format("ext = ['py']", "dir = ['src']")
    assert census(body, files).unmatched.changed == 1
    assert census("overlap = 'first_match_wins'\n" + body, files).unmatched.changed == 1


# ---------------------------------------------------------------------------
# The fast path
# ---------------------------------------------------------------------------


def test_a_file_counted_from_numstat_classifies_in_bulk(census):
    """No lines to walk, so the whole file's count is charged against the file's own
    facets — which is sound because that path is taken only when no rule reads a line."""
    taken = census(
        PY.format(99) + "include = [{ ext = ['py'] }]\n", [changed("src/a.py", adds=7, dels=3)]
    )
    assert (taken.groups["g"].adds, taken.groups["g"].dels) == (7, 3)
    assert taken.total.files == 1


def test_a_numstat_file_that_is_excluded_is_exempt_in_bulk(census):
    taken = census("", [changed("vendor/x.go", adds=620, dels=4)])
    assert (taken.exempt.changed, taken.total.changed) == (624, 0)


def test_a_numstat_file_at_zero_joins_no_bucket(census):
    taken = census("", [changed("src/a.py", adds=0, dels=0)])
    assert (taken.total.files, taken.exempt.files) == (0, 0)


# ---------------------------------------------------------------------------
# The grace band
# ---------------------------------------------------------------------------


def band(census, count):
    """The verdict on a group budgeted at 400 with a 10% grace, given `count` lines."""
    taken = census(
        "[diff_census.groups.g]\nlimit = { changed = 400, grace = 0.10 }\n",
        [changed("src/a.py", ["+x"] * count)],
    )
    return diff_census.verdict(taken.config.groups["g"].limit, taken.groups["g"])


@pytest.mark.parametrize(
    "count, expected",
    [
        (399, "ok"),  # below the limit
        (400, "warn"),  # exactly the limit — the band warns, it does not move it
        (401, "warn"),
        (440, "warn"),  # exactly the hard threshold, inclusive
        (441, "over"),  # one past it
    ],
)
def test_the_grace_band_boundaries(census, count, expected):
    assert band(census, count) == expected


def test_a_limit_with_no_grace_warns_at_the_limit_exactly(census):
    taken = census(PY.format(10), [changed("src/a.py", ["+x"] * 10)])
    assert diff_census.verdict(taken.config.groups["g"].limit, taken.groups["g"]) == "warn"
    taken = census(PY.format(10), [changed("src/a.py", ["+x"] * 11)])
    assert diff_census.verdict(taken.config.groups["g"].limit, taken.groups["g"]) == "over"


def test_every_named_metric_must_pass(census):
    """`added` is comfortable and `deleted` is not, so the limit is not."""
    taken = census(
        "[diff_census.groups.g]\nlimit = { added = 100, deleted = 1 }\n",
        [changed("src/a.py", ["+one", "-two", "-three"])],
    )
    assert diff_census.verdict(taken.config.groups["g"].limit, taken.groups["g"]) == "over"


def test_the_census_wide_limits_budget_total_and_unmatched(census):
    taken = census(
        PY.format(99) + "include = [{ ext = ['go'] }]\n"
        "[diff_census.limits]\ntotal = { changed = 99 }\nunmatched = { changed = 1 }\n",
        [changed("src/a.py", ["+one", "+two"])],
    )
    names = {name: status for name, _, _, status in diff_census.verdicts(taken)}
    assert names == {"g": "ok", "total": "ok", "unmatched": "over"}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def test_the_report_carries_the_specified_shape(report):
    out = report(
        "[diff_census.matchers.m]\nreport = true\nrules = [{ ext = ['py'] }]\n"
        + PY.format(99)
        + "include = [{ ext = ['py'] }]\n"
        "[diff_census.limits]\ntotal = { changed = 99 }\n",
        [changed("src/a.py", ["+one", "-two"]), changed("vendor/x.go", ["+three"])],
    )
    assert out["schema_version"] == 1
    assert out["refs"] == {"base": "main", "head": "HEAD", "merge_base": None, "mode": "two-dot"}
    assert out["groups"]["g"] == {
        "adds": 1,
        "dels": 1,
        "changed": 2,
        "files": 1,
        "limit": {"metric": "changed", "value": 99, "grace": 0.0, "hard": 99},
        "status": "ok",
    }
    assert out["matchers"]["m"] == {"adds": 1, "dels": 1, "changed": 2, "files": 1}
    assert out["totals"]["total"]["status"] == "ok"
    assert out["totals"]["unmatched"] == {"adds": 0, "dels": 0, "changed": 0, "files": 0}
    assert out["totals"]["exempt"]["by_rule"] == {"builtin": {"adds": 1, "dels": 0, "changed": 1}}
    assert set(out) == {"schema_version", "refs", "groups", "matchers", "totals", "diagnostics"}


def test_status_appears_only_where_a_limit_is_configured(report):
    out = report(
        "[diff_census.matchers.m]\nreport = true\nrules = [{ ext = ['py'] }]\n" + PY.format(99),
        [changed("src/a.py", ["+one"])],
    )
    assert "status" in out["groups"]["g"] and "limit" in out["groups"]["g"]
    assert "status" not in out["matchers"]["m"]
    assert "status" not in out["totals"]["total"]
    assert "status" not in out["totals"]["unmatched"]
    assert "status" not in out["totals"]["exempt"]


def test_there_is_no_grand_total_field(report):
    """`total` and `exempt` are the two numbers; their sum is deliberately not a third,
    so there is one obvious way to read each."""
    out = report("", [changed("src/a.py", ["+one"]), changed("vendor/x.go", ["+two"])])
    assert "grand_total" not in out["totals"]
    assert set(out["totals"]) == {"total", "unmatched", "exempt"}


def test_a_limit_naming_several_metrics_reports_each(report):
    out = report(
        "[diff_census.groups.g]\nlimit = { added = 10, changed = 20 }\n",
        [changed("src/a.py", ["+one"])],
    )
    assert out["groups"]["g"]["limit"] == [
        {"metric": "added", "value": 10, "grace": 0.0, "hard": 10},
        {"metric": "changed", "value": 20, "grace": 0.0, "hard": 20},
    ]


def test_the_report_carries_the_diagnostics(report):
    binary = changed("logo.png", [])
    binary.binary = True
    out = report("", [binary, changed("src/a.py", ["+one"])])
    assert out["diagnostics"]["binary_files"] == 1
    assert set(out["diagnostics"]) == {
        "binary_files",
        "submodule_changes",
        "unknown_lexer_files",
        "oversize_skipped_files",
        "files_read",
        "blobs_lexed",
        "cache_hits",
        "elapsed_ms",
        "warnings",
    }


def test_a_configuration_warning_reaches_the_diagnostics(report):
    out = report(
        "[diff_census.groups.g]\nlimit = { changed = 1 }\n"
        "include = [{ ext = ['py'] }]\nexclude = [{ ext = ['py'] }]\n",
        [changed("src/a.py", ["+one"])],
    )
    assert any("no line can match" in w for w in out["diagnostics"]["warnings"])


# ---------------------------------------------------------------------------
# Gate mode and exit codes
# ---------------------------------------------------------------------------


def sized(repo, count):
    repo.write("src/a.py", "".join(f"line {n}\n" for n in range(count)))
    repo.commit("work")


def test_gate_mode_with_no_groups_exits_2(repo, gate):
    """A gate that measures nothing must not pass everything, and this is checked when
    the gate runs rather than when the configuration loads."""
    sized(repo, 5)
    code, out = gate("--gate", "--two-dot", "--base", "HEAD~1", config="")
    assert code == 2
    assert "no groups" in out.err


def test_census_mode_with_no_groups_measures(repo, gate):
    sized(repo, 5)
    code, _out = gate("--census", "--two-dot", "--base", "HEAD~1", config="")
    assert code == 0


def test_a_configuration_with_no_groups_reports_by_default(repo, gate):
    """Gate mode is the default only once a group exists, so a census-only configuration
    is what the tool is named for rather than a misconfigured gate."""
    sized(repo, 5)
    code, _out = gate(
        "--two-dot",
        "--base",
        "HEAD~1",
        config="[diff_census.matchers.m]\nreport = true\nrules = [{ ext = ['py'] }]\n",
    )
    assert code == 0


def test_a_limit_past_its_band_exits_1(repo, gate):
    sized(repo, 50)
    code, _out = gate("--two-dot", "--base", "HEAD~1", config=PY.format(10))
    assert code == 1


def test_a_limit_inside_its_band_exits_0(repo, gate):
    sized(repo, 50)
    code, _out = gate(
        "--two-dot",
        "--base",
        "HEAD~1",
        config="[diff_census.groups.g]\nlimit = { changed = 50, grace = 0.10 }\n",
    )
    assert code == 0


def test_census_mode_never_exits_1(repo, gate):
    sized(repo, 50)
    code, _out = gate("--census", "--two-dot", "--base", "HEAD~1", config=PY.format(10))
    assert code == 0


def test_the_report_is_json_by_default(repo, gate):
    sized(repo, 3)
    _code, out = gate("--two-dot", "--base", "HEAD~1", config="")
    assert json.loads(out.out)["totals"]["total"]["changed"] == 3


def test_an_empty_diff_counts_nothing_and_passes(repo, gate):
    code, _out = gate("--two-dot", "--base", "HEAD", config=PY.format(1))
    assert code == 0
