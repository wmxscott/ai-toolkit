"""Every rejection the configuration reference promises, and the key each one names."""

import pytest
from census_support import diff_census

# -- version ----------------------------------------------------------------


def test_version_is_required(error_raw):
    message = error_raw("[diff_census]\noverlap = 'multi'\n")
    assert "diff_census.version" in message and "required" in message


def test_version_must_be_one(error_raw):
    message = error_raw("[diff_census]\nversion = 2\n")
    assert "diff_census.version" in message and "unsupported version 2" in message


# -- overlap ----------------------------------------------------------------


@pytest.mark.parametrize("value", ["multi", "first_match_wins"])
def test_both_overlap_policies_are_accepted(load, value):
    assert load(f"overlap = '{value}'\n").overlap == value


def test_unknown_overlap_policy_names_the_key(error):
    message = error("overlap = 'last_wins'\n")
    assert "diff_census.overlap" in message and "first_match_wins" in message


# -- names ------------------------------------------------------------------


@pytest.mark.parametrize("name", diff_census.RESERVED_NAMES)
def test_reserved_group_name_is_rejected(error, name):
    message = error(f"[diff_census.groups.{name}]\nlimit = {{ changed = 1 }}\n")
    assert f"diff_census.groups.{name}" in message
    assert "reserved" in message


@pytest.mark.parametrize("name", diff_census.RESERVED_NAMES)
def test_reserved_matcher_name_is_rejected(error, name):
    message = error(f"[diff_census.matchers.{name}]\nrules = [{{ ext = 'py' }}]\n")
    assert f"diff_census.matchers.{name}" in message
    assert "reserved" in message


def test_one_name_for_a_group_and_a_matcher_is_rejected(error):
    message = error("""
[diff_census.matchers.tests]
rules = [{ dir = "tests" }]
[diff_census.groups.tests]
limit = { changed = 1 }
""")
    assert "diff_census.groups.tests" in message
    assert "both a group and a matcher" in message


# -- limits -----------------------------------------------------------------


def test_group_without_a_limit_points_at_report(error):
    message = error("[diff_census.groups.g]\ninclude = [{ dir = 'src' }]\n")
    assert "diff_census.groups.g" in message
    assert "needs `limit`" in message
    assert "report = true" in message


def test_unknown_limit_metric_names_the_key(error):
    message = error("[diff_census.groups.g]\nlimit = { lines = 400 }\n")
    assert "diff_census.groups.g.limit.lines" in message


@pytest.mark.parametrize("grace", ["1.0", "1.5", "-0.1"])
def test_grace_outside_the_band_is_rejected(error, grace):
    message = error(f"[diff_census.groups.g]\nlimit = {{ changed = 1, grace = {grace} }}\n")
    assert "diff_census.groups.g.limit.grace" in message
    assert "outside [0, 1)" in message


@pytest.mark.parametrize("grace", ["0.0", "0.1", "0.999"])
def test_grace_inside_the_band_is_accepted(load, grace):
    load(f"[diff_census.groups.g]\nlimit = {{ changed = 1, grace = {grace} }}\n")


def test_grace_on_the_totals_limit_is_checked_too(error):
    message = error("[diff_census.limits]\ntotal = { changed = 1, grace = 2.0 }\n")
    assert "diff_census.limits.total.grace" in message


@pytest.mark.parametrize("bucket", ["total", "unmatched"])
def test_limits_budget_total_and_unmatched(load, bucket):
    config = load(f"[diff_census.limits]\n{bucket} = {{ changed = 10, grace = 0.1 }}\n")
    assert config.limits[bucket].metrics["changed"] == 10


def test_limits_reject_any_other_bucket(error):
    message = error("[diff_census.limits]\nexempt = { changed = 10 }\n")
    assert "diff_census.limits" in message
    assert "exempt" in message


def test_unmatched_limit_is_independent_of_the_total_limit(load):
    config = load(
        "[diff_census.limits]\n"
        "total = { changed = 1200, grace = 0.1 }\n"
        "unmatched = { changed = 50 }\n"
    )
    assert config.limits["total"].metrics["changed"] == 1200
    assert config.limits["unmatched"].metrics["changed"] == 50
    assert config.limits["unmatched"].grace == 0.0


def test_grace_must_be_a_number(error):
    assert "diff_census.groups.g.limit.grace" in error(
        "[diff_census.groups.g]\nlimit = { changed = 1, grace = 'some' }\n"
    )


# -- facet values -----------------------------------------------------------


def matcher(body):
    return "[diff_census.matchers.x]\nrules = [{ " + body + " }]\n"


@pytest.mark.parametrize("facet", ["path", "dir", "name"])
def test_invalid_glob_names_the_key(error, facet):
    message = error(matcher(f"{facet} = ['!' ]"))
    assert f"diff_census.matchers.x.rules[0].{facet}[0]" in message
    assert "invalid glob" in message


def test_a_glob_that_matches_nothing_is_rejected(error):
    message = error(matcher("path = ['#notacomment']"))
    assert "matches nothing" in message


def test_the_offending_value_is_named_by_index(error):
    message = error(matcher("path = ['src/**', 'lib/**', '!']"))
    assert "path[2]" in message


@pytest.mark.parametrize("facet", ["path_regex", "name_regex", "content"])
def test_invalid_regex_names_the_key(error, facet):
    message = error(matcher(f"{facet} = ['(unclosed']"))
    assert f"diff_census.matchers.x.rules[0].{facet}[0]" in message
    assert "invalid regex" in message


@pytest.mark.parametrize("value", ["> 1MiB", "<= 4096", ">=1", "<0", "==10B", "!= 2GiB", "> 4 kib"])
def test_well_formed_size_comparisons_are_accepted(load, value):
    load(matcher(f"size = ['{value}']"))


@pytest.mark.parametrize("value", ["1024", "~ 10", "> ", ">> 10", "> -1", "big"])
def test_malformed_size_comparison_names_the_key(error, value):
    message = error(matcher(f"size = ['{value}']"))
    assert "diff_census.matchers.x.rules[0].size[0]" in message
    assert "malformed size comparison" in message


def test_unknown_size_unit_names_the_key(error):
    message = error(matcher("size = ['> 10PiB']"))
    assert "unknown size unit" in message and "size[0]" in message


def test_size_units_are_binary_and_case_insensitive():
    parser = diff_census.Parser("test")
    assert diff_census.check_size(parser, "k", "> 1mib") == (">", 1024 * 1024)
    assert diff_census.check_size(parser, "k", "<=4096") == ("<=", 4096)


@pytest.mark.parametrize("value", diff_census.MODES)
def test_every_git_file_mode_is_accepted(load, value):
    load(matcher(f"mode = ['{value}']"))


@pytest.mark.parametrize("value", ["644", "100664", "40000", "file"])
def test_invalid_mode_names_the_key(error, value):
    message = error(matcher(f"mode = ['{value}']"))
    assert "diff_census.matchers.x.rules[0].mode[0]" in message
    assert "file mode" in message


@pytest.mark.parametrize("value", diff_census.CHANGES)
def test_change_values_are_accepted(load, value):
    load(matcher(f"change = ['{value}']"))


def test_invalid_change_names_the_key(error):
    message = error(matcher("change = ['added']"))
    assert "diff_census.matchers.x.rules[0].change[0]" in message


@pytest.mark.parametrize("value", diff_census.COMMENTS)
def test_comment_values_are_accepted(load, value):
    load(matcher(f"comment = ['{value}']"))


def test_invalid_comment_state_names_the_key(error):
    message = error(matcher("comment = ['maybe']"))
    assert "diff_census.matchers.x.rules[0].comment[0]" in message
    assert "comment state" in message


def test_global_exclusion_rules_are_checked_too(error):
    message = error("[diff_census.global]\nexclude = [{ content = '(' }]\n")
    assert "diff_census.global.exclude[0].content[0]" in message


def test_group_rules_are_checked_too(error):
    message = error("""
[diff_census.groups.g]
limit = { changed = 1 }
exclude = [{ path_regex = '[' }]
""")
    assert "diff_census.groups.g.exclude[0].path_regex[0]" in message


# -- matcher references -----------------------------------------------------


def test_a_matcher_may_reference_another(load):
    config = load("""
[diff_census.matchers.base]
rules = [{ dir = "src" }]
[diff_census.matchers.derived]
rules = [{ matches = "base", ext = "py" }]
""")
    assert config.matchers["derived"].rules[0].facets["matches"] == ["base"]


def test_nested_references_resolve(load):
    load("""
[diff_census.matchers.a]
rules = [{ ext = "py" }]
[diff_census.matchers.b]
rules = [{ matches = "a" }]
[diff_census.matchers.c]
rules = [{ matches = "b" }]
""")


def test_undefined_matcher_reference_names_the_key(error):
    message = error("""
[diff_census.matchers.x]
rules = [{ matches = "nope" }]
""")
    assert "diff_census.matchers.x.rules[0].matches" in message
    assert "undefined matcher 'nope'" in message


def test_a_group_referencing_an_undefined_matcher_is_rejected(error):
    message = error("""
[diff_census.groups.g]
limit = { changed = 1 }
exclude = [{ matches = "nope" }]
""")
    assert "diff_census.groups.g.exclude[0].matches" in message


def test_a_self_reference_is_a_cycle(error):
    message = error("""
[diff_census.matchers.a]
rules = [{ matches = "a" }]
""")
    assert "reference cycle" in message and "a -> a" in message


def test_a_cycle_is_named(error):
    message = error("""
[diff_census.matchers.a]
rules = [{ matches = "b" }]
[diff_census.matchers.b]
rules = [{ matches = "c" }]
[diff_census.matchers.c]
rules = [{ matches = "a" }]
""")
    assert "reference cycle" in message
    assert "a -> b -> c -> a" in message


def test_a_shared_reference_is_not_a_cycle(load):
    load("""
[diff_census.matchers.leaf]
rules = [{ ext = "py" }]
[diff_census.matchers.one]
rules = [{ matches = "leaf" }]
[diff_census.matchers.two]
rules = [{ matches = ["leaf", "one"] }]
""")


# -- a config of every shape ------------------------------------------------


def test_the_specifications_example_config_loads(load):
    config = load("""
overlap = "multi"
docstrings_as_comments = true

[diff_census.global]
extend_builtin = true
exclude = [
  { path = ["**/*.lock", "**/package-lock.json", "**/go.sum"] },
  { path = ["**/vendor/**", "**/node_modules/**", "**/*.min.js"] },
  { content = '^\\s*$' },
]

[diff_census.matchers.generated]
report = true
rules = [
  { content = '@generated|Code generated by' },
  { path = ["**/*.pb.go", "**/*_pb2.py", "**/migrations/**"] },
]

[diff_census.matchers.tests]
report = true
rules = [
  { path = ["tests/**", "**/*_test.py", "**/*_test.go", "**/conftest.py"] },
]

[diff_census.matchers.docs]
report = true
rules = [
  { ext = ["md", "rst", "txt"] },
  { path = ["docs/**"] },
]

[diff_census.matchers.comments]
report = true
rules = [
  { comment = ["only"] },
]

[diff_census.groups.production]
limit = { changed = 400, grace = 0.10 }
include = [
  { path = ["src/**", "lib/**"] },
]
exclude = [
  { matches = ["generated", "tests", "docs"] },
  { comment = ["only", "trailing"] },
]

[diff_census.limits]
total = { changed = 1200, grace = 0.10 }
""")
    assert list(config.matchers) == ["generated", "tests", "docs", "comments"]
    assert list(config.groups) == ["production"]
    assert config.groups["production"].limit.hard("changed") == 440
    assert config.limits["total"].hard("changed") == 1320
    assert len(config.exclude) == 3
