"""Resolution, loading and parsing: where the configuration comes from, and the shape
the `[diff_census]` table turns into."""

import json
import os
import subprocess
import sys

import pytest
from census_support import HEADER, SCRIPT, diff_census

# -- resolution -------------------------------------------------------------


def test_absent_config_is_built_in_defaults():
    config = diff_census.load_config()
    assert config.source is None
    assert config.matchers == {} and config.groups == {}
    assert [r.facets for r in config.global_exclude] == [
        {"path": list(diff_census.BUILTIN_GLOBAL_EXCLUDE)}
    ]


def test_explicit_config_wins_over_environment(write, monkeypatch):
    monkeypatch.setenv(diff_census.CONFIG_ENV, write(HEADER, "env.toml"))
    named = write(HEADER + "overlap = 'first_match_wins'\n", "named.toml")
    assert diff_census.load_config(named).overlap == "first_match_wins"


def test_environment_wins_over_the_repository(write, monkeypatch):
    path = write(HEADER)
    monkeypatch.setenv(diff_census.CONFIG_ENV, path)
    assert diff_census.load_config().source == path


def test_repository_path_is_used_when_nothing_else_is(tmp_path, monkeypatch):
    subprocess.run(("git", "init", "-q", str(tmp_path)), check=True)
    path = tmp_path / diff_census.CONFIG_RELPATH
    path.parent.mkdir(parents=True)
    path.write_text(HEADER)
    monkeypatch.chdir(tmp_path)
    assert os.path.samefile(diff_census.load_config().source, path)


def test_named_config_that_is_missing_is_an_error(tmp_path):
    with pytest.raises(diff_census.ConfigError) as caught:
        diff_census.load_config(str(tmp_path / "nope.toml"))
    assert "not a file" in str(caught.value)


def test_named_config_that_is_a_directory_is_an_error(tmp_path):
    with pytest.raises(diff_census.ConfigError):
        diff_census.load_config(str(tmp_path))


def test_environment_config_that_is_missing_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv(diff_census.CONFIG_ENV, str(tmp_path / "nope.toml"))
    with pytest.raises(diff_census.ConfigError):
        diff_census.load_config()


def test_unreadable_config_is_an_error(write):
    path = write(HEADER)
    os.chmod(path, 0o000)
    try:
        with pytest.raises(diff_census.ConfigError) as caught:
            diff_census.load_config(path)
    finally:
        os.chmod(path, 0o644)
    assert "cannot read" in str(caught.value)


def test_malformed_toml_is_an_error(error_raw):
    assert "config.toml" in error_raw("[diff_census\nversion = 1\n")


# -- the section ------------------------------------------------------------


def test_sibling_tables_are_ignored(load_raw):
    config = load_raw("""
[some_other_tool]
its_own = 400
keys = ["*.md"]

[stack_overlap]
anything = true

[diff_census]
version = 1
overlap = "first_match_wins"
""")
    assert config.overlap == "first_match_wins"


def test_a_file_without_the_section_is_defaults(load_raw):
    config = load_raw("[some_other_tool]\nits_own = 400\n")
    assert config.groups == {} and config.overlap == "multi"
    assert config.source is not None


def test_the_section_must_be_a_table(error_raw):
    assert "diff_census" in error_raw("diff_census = 1\n")


def test_unknown_top_level_key_names_itself(error):
    message = error("verison = 1\n")
    assert "diff_census.verison" in message and "unknown key" in message


# -- scalars ----------------------------------------------------------------


def test_defaults_apply_to_omitted_keys(load):
    config = load("")
    assert config.version == 1
    assert config.overlap == "multi"
    assert config.docstrings_as_comments is True
    assert config.extend_builtin is True


@pytest.mark.parametrize(
    "body,key",
    [
        ("version = 'one'", "diff_census.version"),
        ("version = true", "diff_census.version"),
        ("overlap = 1", "diff_census.overlap"),
        ("docstrings_as_comments = 'yes'", "diff_census.docstrings_as_comments"),
    ],
)
def test_scalar_type_errors_name_the_key(error_raw, body, key):
    assert key in error_raw("[diff_census]\n" + body + "\n")


# -- global -----------------------------------------------------------------


def test_global_exclude_extends_the_builtins(load):
    config = load("""
[diff_census.global]
exclude = [{ path = ["docs/**"] }]
""")
    effective = [r.facets for r in config.global_exclude]
    assert effective[0] == {"path": list(diff_census.BUILTIN_GLOBAL_EXCLUDE)}
    assert effective[-1] == {"path": ["docs/**"]}


def test_extend_builtin_false_replaces_them(load):
    config = load("""
[diff_census.global]
extend_builtin = false
exclude = [{ path = ["docs/**"] }]
""")
    assert [r.facets for r in config.global_exclude] == [{"path": ["docs/**"]}]


def test_global_exclude_is_a_rule_list(load):
    config = load("""
[diff_census.global]
exclude = [{ path = ["**/*.lock"] }, { content = '^\\s*$' }]
""")
    assert [r.facets for r in config.exclude] == [{"path": ["**/*.lock"]}, {"content": ["^\\s*$"]}]


def test_global_unknown_key_names_itself(error):
    assert "diff_census.global.exlcude" in error("[diff_census.global]\nexlcude = []\n")


# -- matchers ---------------------------------------------------------------


def test_matcher_parses_report_and_rules(load):
    config = load("""
[diff_census.matchers.tests]
report = true
rules = [{ path = "**/test_*.py" }, { dir = "tests" }]
""")
    matcher = config.matchers["tests"]
    assert matcher.report is True
    assert [r.facets for r in matcher.rules] == [{"path": ["**/test_*.py"]}, {"dir": ["tests"]}]


def test_matcher_report_defaults_to_false(load):
    config = load("[diff_census.matchers.x]\nrules = [{ ext = 'py' }]\n")
    assert config.matchers["x"].report is False


def test_a_bare_facet_value_is_a_one_value_list(load):
    config = load("[diff_census.matchers.x]\nrules = [{ ext = 'py' }]\n")
    assert config.matchers["x"].rules[0].facets == {"ext": ["py"]}


def test_ext_accepts_the_empty_string(load):
    config = load("[diff_census.matchers.x]\nrules = [{ ext = '' }]\n")
    assert config.matchers["x"].rules[0].facets == {"ext": [""]}


def test_array_of_tables_is_an_equivalent_rule_list(load):
    config = load("""
[[diff_census.matchers.x.rules]]
path = ["src/**"]
[[diff_census.matchers.x.rules]]
ext = ["py"]
""")
    assert [r.facets for r in config.matchers["x"].rules] == [{"path": ["src/**"]}, {"ext": ["py"]}]


def test_a_rule_list_must_be_a_list(error):
    assert "diff_census.matchers.x.rules" in error(
        "[diff_census.matchers.x]\nrules = { ext = 'py' }\n"
    )


def test_matcher_without_rules_is_an_error(error):
    message = error("[diff_census.matchers.x]\nreport = true\n")
    assert "diff_census.matchers.x" in message and "rules" in message


def test_empty_rule_list_is_an_error(error):
    assert "rules" in error("[diff_census.matchers.x]\nrules = []\n")


def test_rule_with_no_facets_is_an_error(error):
    assert "at least one facet" in error("[diff_census.matchers.x]\nrules = [{}]\n")


def test_unknown_facet_names_itself(error):
    message = error("[diff_census.matchers.x]\nrules = [{ paht = 'a' }]\n")
    assert "diff_census.matchers.x.rules[0].paht" in message
    assert "unknown facet" in message


def test_facet_value_of_the_wrong_type_names_itself(error):
    assert "diff_census.matchers.x.rules[0].ext" in error(
        "[diff_census.matchers.x]\nrules = [{ ext = 1 }]\n"
    )


def test_matcher_unknown_key_names_itself(error):
    assert "diff_census.matchers.x.reprot" in error(
        "[diff_census.matchers.x]\nreprot = true\nrules = [{ ext = 'py' }]\n"
    )


# -- groups -----------------------------------------------------------------


def test_group_parses_limit_include_and_exclude(load):
    config = load("""
[diff_census.matchers.tests]
rules = [{ dir = "tests" }]

[diff_census.groups.production]
limit = { changed = 400, grace = 0.1 }
include = [{ dir = "src" }]
exclude = [{ matches = "tests" }]
""")
    group = config.groups["production"]
    assert group.limit.metrics == {"changed": 400}
    assert group.limit.grace == 0.1
    assert [r.facets for r in group.include] == [{"dir": ["src"]}]
    assert [r.facets for r in group.exclude] == [{"matches": ["tests"]}]


def test_a_limit_may_carry_several_metrics(load):
    config = load("[diff_census.groups.g]\nlimit = { added = 10, deleted = 5, changed = 12 }\n")
    assert config.groups["g"].limit.metrics == {"added": 10, "deleted": 5, "changed": 12}


def test_limit_grace_defaults_to_zero(load):
    config = load("[diff_census.groups.g]\nlimit = { added = 10 }\n")
    assert config.groups["g"].limit.grace == 0.0


def test_hard_threshold_applies_the_grace_band(load):
    limit = (
        load("[diff_census.groups.g]\nlimit = { changed = 400, grace = 0.1 }\n").groups["g"].limit
    )
    assert limit.hard("changed") == 440


def test_limit_with_no_metric_is_an_error(error):
    assert "diff_census.groups.g.limit" in error(
        "[diff_census.groups.g]\nlimit = { grace = 0.1 }\n"
    )


def test_limit_value_must_be_an_integer(error):
    assert "diff_census.groups.g.limit.added" in error(
        "[diff_census.groups.g]\nlimit = { added = 'lots' }\n"
    )


def test_limit_must_be_a_table(error):
    assert "diff_census.groups.g.limit" in error("[diff_census.groups.g]\nlimit = 400\n")


def test_group_unknown_key_names_itself(error):
    assert "diff_census.groups.g.limti" in error("[diff_census.groups.g]\nlimti = 1\n")


def test_omitted_include_means_match_all(load):
    config = load("[diff_census.groups.g]\nlimit = { changed = 1 }\nexclude = [{ ext = 'md' }]\n")
    assert config.groups["g"].include == []


def test_group_declaration_order_is_preserved(load):
    config = load("""
[diff_census.groups.zulu]
limit = { changed = 1 }
[diff_census.groups.alpha]
limit = { changed = 2 }
[diff_census.groups.mike]
limit = { changed = 3 }
""")
    assert list(config.groups) == ["zulu", "alpha", "mike"]


def test_matcher_declaration_order_is_preserved(load):
    config = load("""
[diff_census.matchers.zulu]
rules = [{ ext = "a" }]
[diff_census.matchers.alpha]
rules = [{ ext = "b" }]
""")
    assert list(config.matchers) == ["zulu", "alpha"]


# -- limits -----------------------------------------------------------------


def test_limits_budgets_the_total_bucket(load):
    config = load("[diff_census.limits]\ntotal = { changed = 1200, grace = 0.1 }\n")
    assert config.limits["total"].metrics == {"changed": 1200}
    assert config.limits["total"].hard("changed") == 1320


def test_limits_rejects_a_bucket_it_cannot_budget(error):
    message = error("[diff_census.limits]\nexempt = { changed = 10 }\n")
    assert "diff_census.limits.exempt" in message


# -- the command ------------------------------------------------------------


def run(*args, cwd=None):
    return subprocess.run(
        (sys.executable, str(SCRIPT), *args), capture_output=True, text=True, cwd=cwd
    )


def test_print_config_exits_zero_and_prints_json(write):
    done = run("--config", write(HEADER), "--print-config")
    assert done.returncode == 0
    assert json.loads(done.stdout)["config"]["version"] == 1


def test_declaration_order_survives_the_printed_json(write):
    path = write(
        HEADER
        + """
[diff_census.groups.zulu]
limit = { changed = 1 }
[diff_census.groups.alpha]
limit = { changed = 2 }
"""
    )
    printed = json.loads(run("--config", path, "--print-config").stdout)
    assert [g["name"] for g in printed["config"]["groups"]] == ["zulu", "alpha"]


def test_a_bad_config_exits_two(write):
    done = run("--config", write(HEADER + "verison = 1\n"), "--print-config")
    assert done.returncode == 2
    assert "diff_census.verison" in done.stderr


def test_a_missing_config_exits_two(tmp_path):
    done = run("--config", str(tmp_path / "nope.toml"), "--print-config")
    assert done.returncode == 2


def test_the_script_runs_through_its_shebang(write, tmp_path):
    done = subprocess.run(
        (str(SCRIPT), "--config", write(HEADER), "--print-config"),
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["config"]["version"] == 1
