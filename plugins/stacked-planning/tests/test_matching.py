"""The rule engine: what each facet matches, and how facets, values and rules combine.

Subjects are built by hand here rather than read from a diff — the engine takes the facts
it is given and never asks git for anything, which is what lets these cases be exhaustive.
"""

import pytest
from census_support import diff_census


def subject(path="src/a.py", size=None, mode=None, **line):
    """A subject over one file, with any line-level facts the case supplies."""
    return diff_census.Subject(diff_census.File(path, size=size, mode=mode), **line)


@pytest.fixture
def rules(load):
    """Compile a rule list, and return the predicate over subjects it evaluates to."""

    def _rules(body, extra=""):
        config = load(extra + f"[diff_census.matchers.m]\nrules = [{body}]\n")
        matcher = config.matchers["m"]
        return lambda subj: diff_census.matches_any(matcher.rules, subj)

    return _rules


@pytest.fixture
def facet(rules):
    """The predicate for a single-facet rule, which is most of what is tested here."""
    return lambda body: rules(f"{{ {body} }}")


@pytest.fixture
def group(load):
    """Compile a group, and return its membership predicate."""

    def _group(body, extra=""):
        config = load(extra + "[diff_census.groups.g]\nlimit = { changed = 1 }\n" + body)
        g = config.groups["g"]
        return lambda subj: diff_census.member(g, subj)

    return _group


# -- the subject ------------------------------------------------------------


@pytest.mark.parametrize(
    "path, dirname, name, ext",
    [
        ("src/api/handlers.py", "src/api", "handlers.py", "py"),
        ("README", "", "README", ""),
        (".gitignore", "", ".gitignore", ""),
        ("a/b/archive.tar.gz", "a/b", "archive.tar.gz", "gz"),
        ("Makefile.PROD", "", "Makefile.PROD", "prod"),
    ],
)
def test_the_file_facets_derive_from_the_path(path, dirname, name, ext):
    f = diff_census.File(path)
    assert (f.dir, f.name, f.ext) == (dirname, name, ext)


def test_a_files_mime_type_comes_from_its_path():
    assert diff_census.File("a/b.py").mime == "text/x-python"


def test_the_supplementary_table_wins_over_the_standard_one():
    # Python's own map calls `.ts` a video stream and `.rs` an XML service description.
    assert diff_census.File("a.ts").mime == "text/x-typescript"
    assert diff_census.File("a.rs").mime == "text/x-rust"


def test_an_unguessable_type_is_octet_stream():
    assert diff_census.File("a.wibble").mime == "application/octet-stream"


# -- path, dir, name --------------------------------------------------------


@pytest.mark.parametrize(
    "path, hit", [("src/a.py", True), ("src/api/v1/a.py", True), ("lib/a.py", False)]
)
def test_path_is_a_glob_over_the_whole_path(facet, path, hit):
    assert facet("path = 'src/**'")(subject(path)) is hit


@pytest.mark.parametrize("path, hit", [("src/a.py", True), ("src/api/a.py", False)])
def test_a_single_star_does_not_cross_a_separator(facet, path, hit):
    assert facet("path = 'src/*.py'")(subject(path)) is hit


def test_path_regex_searches_the_whole_path(facet):
    match = facet("path_regex = 'api/v[0-9]+/'")
    assert match(subject("src/api/v2/a.py")) is True
    assert match(subject("src/api/a.py")) is False


def test_path_regex_is_unanchored_unless_it_says_otherwise(facet):
    assert facet("path_regex = '^src/'")(subject("lib/src/a.py")) is False
    assert facet("path_regex = 'src/'")(subject("lib/src/a.py")) is True


def test_dir_matches_the_dirname_only(facet):
    match = facet("dir = 'src/api'")
    assert match(subject("src/api/a.py")) is True
    assert match(subject("src/other/a.py")) is False


def test_a_file_at_the_root_has_no_dirname_to_match(facet):
    assert facet("dir = '**'")(subject("README.md")) is False


def test_name_matches_the_basename_only(facet):
    match = facet("name = '*_test.py'")
    assert match(subject("deep/nested/thing_test.py")) is True
    assert match(subject("thing_test.py/inner.py")) is False


def test_name_regex_matches_the_basename_only(facet):
    match = facet("name_regex = '^conftest'")
    assert match(subject("tests/conftest.py")) is True
    assert match(subject("conftest/a.py")) is False


def test_globs_accept_character_classes(facet):
    match = facet("path = '**/*.[ch]'")
    assert match(subject("src/a.c")) is True
    assert match(subject("src/a.py")) is False


# -- ext --------------------------------------------------------------------


def test_ext_carries_no_leading_dot(facet):
    assert facet("ext = 'py'")(subject("src/a.py")) is True


def test_ext_is_case_folded_on_both_sides(facet):
    assert facet("ext = 'PY'")(subject("src/a.Py")) is True


def test_ext_empty_string_means_no_extension(facet):
    match = facet("ext = ''")
    assert match(subject("Makefile")) is True
    assert match(subject(".gitignore")) is True
    assert match(subject("a.py")) is False


def test_a_leading_dot_in_the_configured_ext_is_ignored(facet):
    assert facet("ext = '.py'")(subject("a.py")) is True


# -- mime -------------------------------------------------------------------


def test_mime_matches_exactly(facet):
    match = facet("mime = 'text/x-python'")
    assert match(subject("a.py")) is True
    assert match(subject("a.js")) is False


def test_mime_matches_a_type_wildcard(facet):
    match = facet("mime = 'image/*'")
    assert match(subject("assets/logo.png")) is True
    assert match(subject("assets/logo.svg")) is True
    assert match(subject("a.py")) is False


def test_a_mime_wildcard_does_not_match_a_different_type(facet):
    assert facet("mime = 'text/*'")(subject("a.png")) is False


# -- size -------------------------------------------------------------------


@pytest.mark.parametrize(
    "op, hit", [("<", False), ("<=", True), (">", False), (">=", True), ("==", True), ("!=", False)]
)
def test_every_size_operator(facet, op, hit):
    assert facet(f"size = '{op} 1024'")(subject(size=1024)) is hit


@pytest.mark.parametrize(
    "unit, size", [("", 1), ("B", 1), ("KiB", 1024), ("MiB", 1024**2), ("GiB", 1024**3)]
)
def test_every_size_unit(facet, unit, size):
    match = facet(f"size = '>= 1{unit}'")
    assert match(subject(size=size)) is True
    assert match(subject(size=size - 1)) is False


def test_size_units_are_case_insensitive(facet):
    assert facet("size = '> 1mib'")(subject(size=1024**2 + 1)) is True


def test_a_file_of_unknown_size_matches_no_size_comparison(facet):
    assert facet("size = '< 1MiB'")(subject(size=None)) is False


# -- mode -------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["100644", "100755", "120000", "160000"])
def test_every_git_file_mode_matches_itself(facet, mode):
    match = facet(f"mode = '{mode}'")
    assert match(subject(mode=mode)) is True
    assert match(subject(mode="100644" if mode != "100644" else "100755")) is False


def test_a_file_of_unknown_mode_matches_no_mode(facet):
    assert facet("mode = '100644'")(subject(mode=None)) is False


# -- the line-level facets --------------------------------------------------


def test_content_matches_the_line_text(facet):
    match = facet("content = '@generated'")
    assert match(subject(text=b"// @generated by protoc")) is True
    assert match(subject(text=b"ordinary code")) is False


def test_content_is_applied_to_the_raw_bytes(facet):
    assert facet("content = '^\\s*$'")(subject(text=b"   ")) is True


@pytest.mark.parametrize("change", ["add", "del"])
def test_change_matches_the_side_of_the_diff(facet, change):
    match = facet(f"change = '{change}'")
    assert match(subject(change=change)) is True
    assert match(subject(change="del" if change == "add" else "add")) is False


@pytest.mark.parametrize("state", ["only", "trailing", "none", "unknown"])
def test_every_comment_state_matches_itself(facet, state):
    assert facet(f"comment = '{state}'")(subject(comment=state)) is True


@pytest.mark.parametrize("body", ["content = 'x'", "change = 'add'", "comment = 'only'"])
def test_an_unsupplied_line_level_value_does_not_match(facet, body):
    assert facet(body)(subject()) is False


def test_an_unsupplied_line_level_value_does_not_exclude(group):
    """The safe direction for a budget: a rule that cannot be answered fails to fire, so
    an `exclude` that cannot be answered leaves the line inside the group."""
    member = group("include = [{ ext = 'py' }]\nexclude = [{ comment = 'only' }]\n")
    assert member(subject("a.py")) is True
    assert member(subject("a.py", comment="only")) is False


# -- the algebra ------------------------------------------------------------


def test_facets_and_within_a_rule(facet):
    match = facet("path = 'src/**', ext = 'py'")
    assert match(subject("src/a.py")) is True
    assert match(subject("src/a.js")) is False
    assert match(subject("lib/a.py")) is False


def test_values_or_within_a_facet(facet):
    match = facet("path = ['src/**', 'lib/**']")
    assert match(subject("src/a.py")) is True
    assert match(subject("lib/a.py")) is True
    assert match(subject("docs/a.py")) is False


def test_rules_or_across_a_list(rules):
    match = rules("{ path = 'src/**' }, { ext = 'md' }")
    assert match(subject("src/a.py")) is True
    assert match(subject("docs/a.md")) is True
    assert match(subject("docs/a.txt")) is False


def test_a_scalar_facet_value_is_a_one_element_list(facet):
    assert facet("path = 'src/**'")(subject("src/a.py")) is True


def test_an_empty_rule_list_matches_nothing():
    assert diff_census.matches_any([], subject()) is False


# -- matcher references -----------------------------------------------------


def test_matches_evaluates_the_referenced_matcher(rules):
    match = rules("{ matches = 'base' }", "[diff_census.matchers.base]\nrules = [{ ext = 'py' }]\n")
    assert match(subject("a.py")) is True
    assert match(subject("a.md")) is False


def test_matches_ands_with_its_siblings(rules):
    match = rules(
        "{ matches = 'base', dir = 'src/api' }",
        "[diff_census.matchers.base]\nrules = [{ ext = 'py' }]\n",
    )
    assert match(subject("src/api/a.py")) is True
    assert match(subject("src/other/a.py")) is False
    assert match(subject("src/api/a.md")) is False


def test_matches_ors_across_its_own_list(rules):
    match = rules(
        "{ matches = ['py', 'md'] }",
        """
[diff_census.matchers.py]
rules = [{ ext = 'py' }]
[diff_census.matchers.md]
rules = [{ ext = 'md' }]
""",
    )
    assert match(subject("a.py")) is True
    assert match(subject("a.md")) is True
    assert match(subject("a.js")) is False


def test_nested_references_evaluate_to_the_leaf(rules):
    match = rules(
        "{ matches = 'outer' }",
        """
[diff_census.matchers.leaf]
rules = [{ ext = 'py' }]
[diff_census.matchers.middle]
rules = [{ matches = 'leaf' }]
[diff_census.matchers.outer]
rules = [{ matches = 'middle', dir = 'src' }]
""",
    )
    assert match(subject("src/a.py")) is True
    assert match(subject("src/a.md")) is False
    assert match(subject("lib/a.py")) is False


# -- group membership -------------------------------------------------------


def test_omitted_include_matches_everything(group):
    assert group("")(subject("anything/at/all.xyz")) is True


def test_exclude_beats_include(group):
    member = group("include = [{ path = 'src/**' }]\nexclude = [{ ext = 'md' }]\n")
    assert member(subject("src/a.py")) is True
    assert member(subject("src/a.md")) is False


def test_an_exclusion_only_group_is_everything_but(group):
    member = group("exclude = [{ ext = 'md' }]\n")
    assert member(subject("src/a.py")) is True
    assert member(subject("docs/a.md")) is False


def test_a_group_excludes_through_a_matcher(group):
    member = group(
        "include = [{ path = 'src/**' }]\nexclude = [{ matches = 'tests' }]\n",
        "[diff_census.matchers.tests]\nrules = [{ name = '*_test.py' }]\n",
    )
    assert member(subject("src/a.py")) is True
    assert member(subject("src/a_test.py")) is False


def test_the_migration_policy_classifies_as_specified(load):
    """Section 10's configuration, over the files it is meant to sort."""
    config = load("""
[diff_census.matchers.generated]
report = true
rules = [{ content = '@generated' }, { path = ['**/*.pb.go', '**/migrations/**'] }]
[diff_census.matchers.tests]
report = true
rules = [{ path = ['tests/**', '**/*_test.py'] }]
[diff_census.matchers.docs]
report = true
rules = [{ ext = ['md', 'rst', 'txt'] }, { path = ['docs/**'] }]
[diff_census.groups.production]
limit = { changed = 400, grace = 0.10 }
include = [{ path = ['src/**', 'lib/**'] }]
exclude = [{ matches = ['generated', 'tests', 'docs'] },
           { comment = ['only', 'trailing'] }]
""")

    def member(s):
        return diff_census.member(config.groups["production"], s)

    assert member(subject("src/api/handlers.py", comment="none")) is True
    assert member(subject("src/api/handlers.py", comment="only")) is False
    assert member(subject("src/api/handlers_test.py", comment="none")) is False
    assert member(subject("src/api/thing.pb.go", comment="none")) is False
    assert member(subject("src/README.md", comment="none")) is False
    assert member(subject("docs/guide.rst", comment="none")) is False


# -- the never-matches warning ----------------------------------------------


def test_an_exclude_covering_every_include_warns(load):
    config = load("""
[diff_census.groups.g]
limit = { changed = 1 }
include = [{ path = 'src/**' }]
exclude = [{ path = ['src/**', 'tests/**'] }]
""")
    assert any("diff_census.groups.g" in w for w in config.warnings)


def test_the_warning_does_not_fail_the_load(load):
    config = load("""
[diff_census.groups.g]
limit = { changed = 1 }
include = [{ path = 'src/**' }]
exclude = [{ path = 'src/**' }]
""")
    assert config.groups["g"].name == "g"


def test_an_include_the_exclude_does_not_cover_is_not_warned(load):
    config = load("""
[diff_census.groups.g]
limit = { changed = 1 }
include = [{ path = ['src/**', 'lib/**'] }]
exclude = [{ path = 'src/**' }]
""")
    assert config.warnings == []


def test_a_narrower_exclude_is_not_warned(load):
    """The exclude carries a facet the include does not, so it is the narrower rule."""
    config = load("""
[diff_census.groups.g]
limit = { changed = 1 }
include = [{ path = 'src/**' }]
exclude = [{ path = 'src/**', ext = 'md' }]
""")
    assert config.warnings == []


def test_a_line_level_exclude_is_not_analysed(load):
    config = load("""
[diff_census.groups.g]
limit = { changed = 1 }
include = [{ path = 'src/**' }]
exclude = [{ path = 'src/**', comment = 'only' }]
""")
    assert config.warnings == []


def test_a_group_with_no_include_is_not_warned(load):
    config = load("[diff_census.groups.g]\nlimit = { changed = 1 }\nexclude = [{ ext = 'md' }]\n")
    assert config.warnings == []


def test_the_specifications_example_config_warns_about_nothing(load):
    config = load("""
[diff_census.matchers.tests]
rules = [{ path = 'tests/**' }]
[diff_census.groups.production]
limit = { changed = 400 }
include = [{ path = ['src/**', 'lib/**'] }]
exclude = [{ matches = 'tests' }, { comment = ['only', 'trailing'] }]
""")
    assert config.warnings == []
