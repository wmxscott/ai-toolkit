"""Performance: which work a configuration lets the census skip, and the proof that
skipping it changes no answer.

Every case here is about a decision rather than about a duration. A benchmark would
assert nothing a slow machine could not fail, so what is held instead is that the cheap
path is taken when it is available, that it produces the same numbers as the expensive
one, and that the diagnostics say which path ran.
"""

import pytest
from census_support import changed, diff_census

# ---------------------------------------------------------------------------
# The fast-path decision
#
# `--numstat` with `--raw` answers everything but the text of a line. What the decision
# turns on is whether any active rule reads that text.
# ---------------------------------------------------------------------------

GROUP = "[diff_census.groups.g]\nlimit = {{ changed = 99 }}\ninclude = [{{ {0} }}]\n"


@pytest.mark.parametrize(
    "facet",
    [
        "ext = 'py'",
        "path = 'src/**'",
        "mode = '100755'",
        "size = '> 1KiB'",
        "change = 'add'",
    ],
)
def test_a_configuration_reading_no_line_text_needs_no_patch(load, facet):
    """`change` included: which side a count is on is a property of the count, not of the
    line, so numstat answers it."""
    assert diff_census.needs_patch(load(GROUP.format(facet))) is False


@pytest.mark.parametrize("facet", ["content = 'TODO'", "comment = 'only'"])
def test_a_configuration_reading_line_text_needs_the_patch(load, facet):
    assert diff_census.needs_patch(load(GROUP.format(facet))) is True


def test_a_line_facet_inside_a_matcher_needs_the_patch(load):
    """The decision is over every rule the configuration carries, not only the ones a
    group reaches — the safe direction, and the same over-approximation `uses_facet`
    makes."""
    config = load("[diff_census.matchers.todo]\nrules = [{ content = 'TODO' }]\n")
    assert diff_census.needs_patch(config) is True


def test_an_empty_configuration_needs_no_patch(load):
    assert diff_census.needs_patch(load("")) is False


# ---------------------------------------------------------------------------
# `change` off numstat
# ---------------------------------------------------------------------------


def test_change_matches_on_a_file_counted_from_numstat(census):
    """A numstat file charges once per side, so a rule reading `change` fires without a
    line ever being walked."""
    taken = census(GROUP.format("change = 'add'"), [changed("src/a.py", adds=7, dels=3)])
    assert (taken.groups["g"].adds, taken.groups["g"].dels) == (7, 0)


def test_both_sides_of_a_numstat_file_reach_a_group_that_takes_both(census):
    taken = census(GROUP.format("ext = 'py'"), [changed("src/a.py", adds=7, dels=3)])
    assert (taken.groups["g"].adds, taken.groups["g"].dels) == (7, 3)
    assert taken.groups["g"].files == 1


def test_a_numstat_file_with_one_side_only_charges_that_side(census):
    taken = census(GROUP.format("change = 'del'"), [changed("src/a.py", adds=7, dels=0)])
    assert taken.groups["g"].changed == 0
    assert taken.unmatched.changed == 7


# ---------------------------------------------------------------------------
# The two paths agree
#
# The specification's requirement, held against a real repository: a configuration both
# paths can serve must produce the same census either way.
# ---------------------------------------------------------------------------


@pytest.fixture
def both(repo, load):
    """Take the census of the last commit twice — once off numstat, once off the patch —
    and return the two."""

    def _both(body):
        config = load(body)
        git = diff_census.Git.open(str(repo.root))
        refs = diff_census.resolve_refs(git, "two-dot", base="HEAD~1")
        return tuple(
            diff_census.take_census(diff_census.acquire(git, refs, patch=patch), config)
            for patch in (False, True)
        )

    return _both


@pytest.fixture
def populated(repo):
    """A commit touching enough shapes that the two paths have something to disagree
    about: source, prose, a deletion, a rename, a binary and a mode flip."""
    repo.write("src/a.py", "one\ntwo\nthree\n")
    repo.write("src/gone.py", "x\n")
    repo.write("moved.txt", "keep\n")
    repo.write("docs/guide.md", "# title\n")
    repo.write("run.sh", "echo\n")
    repo.write("logo.bin", bytes(range(256)))
    repo.commit("before")
    repo.write("src/a.py", "one\ntwo prime\nthree\nfour\n")
    (repo.root / "src/gone.py").unlink()
    repo.git("mv", "moved.txt", "elsewhere.txt")
    repo.write("docs/guide.md", "# title\n\nprose\n")
    repo.write("run.sh", "echo\n", mode=0o755)
    repo.write("logo.bin", bytes(range(255, -1, -1)))
    repo.commit("after")
    return repo


def buckets(taken):
    return {
        name: (b.adds, b.dels, b.files)
        for name, b in list(taken.groups.items())
        + list(taken.matchers.items())
        + [("total", taken.total), ("unmatched", taken.unmatched), ("exempt", taken.exempt)]
    }


AGREE = (
    "[diff_census.matchers.prose]\nreport = true\nrules = [{ ext = ['md'] }]\n"
    "[diff_census.groups.production]\nlimit = { changed = 99 }\n"
    "include = [{ ext = ['py', 'sh'] }]\nexclude = [{ change = ['del'] }]\n"
    "[diff_census.groups.everything]\nlimit = { changed = 99 }\n"
)


def test_the_two_paths_produce_the_same_census(populated, both):
    numstat, patched = both(AGREE)
    assert buckets(numstat) == buckets(patched)
    assert (numstat.via, patched.via) == ("numstat", "patch")


def test_the_two_paths_agree_on_the_rule_attribution(populated, both):
    numstat, patched = both(AGREE)
    assert {k: v.changed for k, v in numstat.by_rule.items()} == {
        k: v.changed for k, v in patched.by_rule.items()
    }


# ---------------------------------------------------------------------------
# The path a run took
#
# Asserted through the report, because an optimisation nothing observes is one that can
# silently stop happening.
# ---------------------------------------------------------------------------

FILE_ONLY = (
    "[diff_census.groups.g]\nlimit = { changed = 999 }\n"
    "include = [{ ext = ['py'] }]\nexclude = [{ change = ['del'] }]\n"
)

READS_LINES = "[diff_census.groups.g]\nlimit = { changed = 999 }\ninclude = [{ content = 'one' }]\n"


@pytest.fixture
def via(repo, gate):
    """The acquisition path a full run took, as the text report names it."""
    repo.write("src/a.py", "one\ntwo\n")
    repo.commit("add")

    def _via(config, *argv):
        code, out = gate("--two-dot", "--base", "HEAD~1", "--format", "text", *argv, config=config)
        assert code == 0, out.err
        return out.out.splitlines()[0].split(", via ")[1]

    return _via


def test_a_configuration_reading_no_line_text_runs_off_numstat(via):
    assert via(FILE_ONLY) == "numstat"


def test_a_configuration_reading_line_text_runs_off_the_patch(via):
    assert via(READS_LINES) == "patch"


def test_force_patch_overrides_the_decision(via):
    """Kept so the two paths can be compared on a configuration that would otherwise
    never take the slow one."""
    assert via(FILE_ONLY, "--force-patch") == "patch"


# ---------------------------------------------------------------------------
# The three-valued reading
#
# `True` and `False` are what a file's own facets say about all of its lines at once.
# `None` is `depends` — the case a walk is for.
# ---------------------------------------------------------------------------


@pytest.fixture
def state(load):
    """What one rule says about a file, without a line to read."""

    def _state(body, path="src/a.py", **facets):
        rule = load(GROUP.format(body)).groups["g"].include[0]
        return diff_census.rule_state(
            rule, diff_census.Subject(diff_census.File(path, **facets), change="add")
        )

    return _state


def test_a_file_facet_settles_a_rule_either_way(state):
    assert state("ext = 'py'") is True
    assert state("ext = 'go'") is False


def test_a_line_facet_leaves_a_rule_depending(state):
    assert state("comment = 'only'") is None
    assert state("content = 'TODO'") is None


def test_a_side_settles_a_rule_without_a_line(state):
    """`change` reads the side of the count, which a file-level subject carries."""
    assert state("change = 'add'") is True
    assert state("change = 'del'") is False


def test_a_cheap_conjunct_settles_a_rule_a_line_facet_shares(state):
    """The point of ordering conjuncts by cost: an `ext` that already says no ends the
    rule, so the `content` beside it is never a reason to walk the file."""
    assert state("ext = 'go', content = 'TODO'") is False
    assert state("ext = 'py', content = 'TODO'") is None


def test_a_rule_list_reports_the_index_first_match_would_have(load):
    rules = (
        load(
            "[diff_census.matchers.m]\nrules = [{ ext = 'go' }, { ext = 'py' }, "
            "{ path = 'src/**' }]\n"
        )
        .matchers["m"]
        .rules
    )
    subject = diff_census.Subject(diff_census.File("src/a.py"))
    assert diff_census.any_state(rules, subject) == (True, 1)
    assert diff_census.first_match(rules, subject) == 1


def test_a_depending_rule_ends_the_scan_of_a_list(load):
    """Conservative on purpose: a later certain match would still leave which rule a
    trace should name unanswered, and the cost of being wrong is a walk."""
    rules = (
        load("[diff_census.matchers.m]\nrules = [{ content = 'x' }, { ext = 'py' }]\n")
        .matchers["m"]
        .rules
    )
    subject = diff_census.Subject(diff_census.File("src/a.py"))
    assert diff_census.any_state(rules, subject) == (None, None)


def test_an_empty_rule_list_settles_as_no_match(load):
    assert diff_census.any_state([], diff_census.Subject(diff_census.File("a.py"))) == (False, None)


# ---------------------------------------------------------------------------
# The file pre-pass
# ---------------------------------------------------------------------------

SCOPED = (
    "[diff_census.groups.g]\nlimit = { changed = 99 }\n"
    "include = [{ path = ['src/**'] }]\nexclude = [{ comment = ['only'] }]\n"
)


@pytest.fixture
def prepass(load):
    return lambda body: diff_census.Prepass(load(body))


def test_a_file_the_include_rules_out_settles(prepass):
    """The shape the specification is about: a `comment` exclusion inside a group whose
    `include` most of the tree fails, so most of the tree never reaches the lexer."""
    assert prepass(SCOPED).resolved(changed("docs/guide.md", ["+x"])) is True


def test_a_file_the_include_admits_depends_on_its_lines(prepass):
    assert prepass(SCOPED).resolved(changed("src/a.py", ["+x"])) is False


def test_a_reported_matcher_reading_only_lines_settles_nothing(prepass):
    """Asked about every file, so no file settles. Worth stating, because it is the
    configuration shape the pre-pass cannot help."""
    blanket = SCOPED + (
        "[diff_census.matchers.commentary]\nreport = true\n"
        "rules = [{ comment = ['only', 'trailing'] }]\n"
    )
    assert prepass(blanket).resolved(changed("docs/guide.md", ["+x"])) is False


def test_an_unreported_matcher_is_not_asked(prepass):
    """A matcher nothing reports and nothing references decides nothing, so it cannot be
    the reason a file is walked."""
    quiet = SCOPED + ("[diff_census.matchers.commentary]\nrules = [{ comment = ['only'] }]\n")
    assert prepass(quiet).resolved(changed("docs/guide.md", ["+x"])) is True


def test_a_reference_is_as_line_level_as_what_it_resolves_to(prepass):
    body = (
        "[diff_census.matchers.paths]\nrules = [{{ path = ['vendor/**'] }}]\n"
        "[diff_census.matchers.texts]\nrules = [{{ content = 'TODO' }}]\n"
        "[diff_census.groups.g]\nlimit = {{ changed = 99 }}\n"
        "exclude = [{{ matches = ['{0}'] }}]\n"
    )
    assert prepass(body.format("paths")).resolved(changed("src/a.py", ["+x"])) is True
    assert prepass(body.format("texts")).resolved(changed("src/a.py", ["+x"])) is False


def test_a_global_exclusion_is_part_of_the_pre_pass(prepass):
    """The shipped list is paths only, so it settles every file it is asked about."""
    assert prepass("").resolved(changed("vendor/x.go", ["+x"])) is True


def test_only_the_sides_a_file_has_are_asked(prepass):
    """A file that only adds settles under a rule that would depend on its deletions,
    because it has none."""
    body = (
        "[diff_census.groups.g]\nlimit = { changed = 99 }\n"
        "include = [{ change = 'del', content = 'x' }]\n"
    )
    assert prepass(body).resolved(changed("src/a.py", ["+x"])) is True
    assert prepass(body).resolved(changed("src/a.py", ["+x", "-y"])) is False


# ---------------------------------------------------------------------------
# A settled file is charged in bulk
# ---------------------------------------------------------------------------


def test_a_settled_file_is_charged_without_its_lines_being_walked(census):
    """The same numbers a walk produces, from one charge per side."""
    lines = ["+a", "+b", "-c"]
    taken = census(SCOPED, [changed("docs/guide.md", lines, comments=["only"] * 3)])
    assert (taken.total.adds, taken.total.dels, taken.total.files) == (2, 1, 1)
    assert taken.groups["g"].changed == 0
    assert taken.unmatched.changed == 3


@pytest.mark.parametrize(
    "path, groups, counted",
    [
        ("docs/b.md", {}, ("total", "unmatched")),
        ("vendor/b.md", {}, ("exempt",)),
        ("src/b.md", {"g": {"include[0]": 2}}, ("total", "g")),
    ],
)
def test_a_settled_file_names_the_rules_a_walk_would_have_named(census, path, groups, counted):
    """A bulk charge is traced through the same `first_match` a walk uses, over a subject
    the pre-pass has already shown settles it, so the labels are the walk's own."""
    body = SCOPED.replace("comment = ['only']", "ext = ['py']")
    story = census(body, [changed(path, ["+a", "+b"])], trace=True).traces[0]
    assert story.groups == groups
    assert tuple(story.buckets) == counted


def test_a_depending_file_still_walks_its_lines(census):
    taken = census(
        SCOPED, [changed("src/a.py", ["+a", "+b", "+c"], comments=["only", "none", "only"])]
    )
    assert taken.groups["g"].changed == 1


# ---------------------------------------------------------------------------
# What the pre-pass saves
# ---------------------------------------------------------------------------


@pytest.fixture
def lexed(repo, load):
    """How many blobs a run lexes, with the pre-pass and without it, and the census each
    produced — which must be the same census."""

    def _lexed(body):
        config = load(body)
        git = diff_census.Git.open(str(repo.root))
        refs = diff_census.resolve_refs(git, "two-dot", base="HEAD~1")
        out = []
        for prepass in (None, diff_census.Prepass(config)):
            diff = diff_census.acquire(git, refs, patch=True)
            comments = diff_census.Comments(git, cache=False)
            diff_census.annotate(git, diff, comments, prepass=prepass)
            diff.prepass = prepass
            out.append((comments.diagnostics.blobs_lexed, diff_census.take_census(diff, config)))
        return out

    return _lexed


@pytest.fixture
def mixed(repo):
    """One file the pre-pass settles and one it cannot."""
    repo.write("src/a.py", "# note\nx = 1\n")
    repo.write("docs/guide.md", "# title\n")
    repo.commit("add")
    return repo


def test_the_pre_pass_keeps_a_settled_file_out_of_the_lexer(mixed, lexed):
    (without, plain), (with_pass, fast) = lexed(SCOPED)
    assert (without, with_pass) == (2, 1)
    assert buckets(plain) == buckets(fast)


def test_the_pre_pass_saves_nothing_it_should_not(mixed, lexed):
    """A configuration asking about every file lexes every file, and says so."""
    blanket = SCOPED + (
        "[diff_census.matchers.commentary]\nreport = true\nrules = [{ comment = ['only'] }]\n"
    )
    (without, plain), (with_pass, fast) = lexed(blanket)
    assert (without, with_pass) == (2, 2)
    assert buckets(plain) == buckets(fast)


# ---------------------------------------------------------------------------
# Streaming the patch
# ---------------------------------------------------------------------------


def test_the_patch_is_read_a_line_at_a_time(repo):
    git = diff_census.Git.open(str(repo.root))
    repo.write("a.txt", "one\ntwo\n")
    repo.commit("add")
    streamed = list(git.stream("diff", "-U0", "HEAD~1", "HEAD"))
    assert streamed == git.run("diff", "-U0", "HEAD~1", "HEAD").split(b"\n")[:-1]
    assert not any(raw.endswith(b"\n") for raw in streamed)


def test_a_stream_that_fails_raises_rather_than_reading_short(repo):
    git = diff_census.Git.open(str(repo.root))
    with pytest.raises(diff_census.GitError) as caught:
        list(git.stream("diff", "no-such-ref", "HEAD"))
    assert "no-such-ref" in str(caught.value)


# ---------------------------------------------------------------------------
# `--jobs`
#
# An escape hatch, so what is held is that it changes nothing rather than that it is
# faster — a pool is only ever worth starting on a change far larger than a test's.
# ---------------------------------------------------------------------------


def test_jobs_defaults_to_one(repo):
    assert diff_census.parse_args([]).jobs == 1


def test_jobs_below_one_is_rejected():
    with pytest.raises(SystemExit):
        diff_census.parse_args(["--jobs", "0"])


@pytest.fixture
def lexes(repo, gate):
    """Run the census over a small tree of several languages, and return its report."""
    repo.write("src/a.py", "# note\nx = 1\n")
    repo.write("src/b.py", "y = 2  # tail\n")
    repo.write("src/c.js", "// note\nlet z = 3;\n")
    repo.write("src/same.py", "# note\nx = 1\n")  # a.py's blob under another name
    repo.commit("add")

    def _lexes(*argv):
        code, out = gate(
            "--two-dot", "--base", "HEAD~1", "--no-cache", *argv, config=READS_COMMENTS
        )
        assert code == 0, out.err
        return __import__("json").loads(out.out)

    return _lexes


READS_COMMENTS = (
    "[diff_census.groups.g]\nlimit = { changed = 999 }\n"
    "include = [{ ext = ['py', 'js'] }]\n"
    "exclude = [{ comment = ['only'] }]\n"
)


def test_a_pool_produces_the_same_report_as_one_worker(lexes):
    serial, parallel = lexes("--jobs", "1"), lexes("--jobs", "4")
    assert serial["groups"] == parallel["groups"]
    assert serial["totals"] == parallel["totals"]


def test_a_pool_lexes_and_reads_exactly_what_one_worker_does(lexes):
    """Including the blob two paths share, which is read once either way."""
    serial, parallel = lexes("--jobs", "1")["diagnostics"], lexes("--jobs", "4")["diagnostics"]
    assert serial["blobs_lexed"] == parallel["blobs_lexed"] == 3
    assert serial["files_read"] == parallel["files_read"] == 3
    assert parallel["warnings"] == []


def test_a_worker_classifies_a_blob_the_same_way_the_walk_does():
    """The worker is handed plain data and builds its own lexer, so this is what holds it
    to the answer the shared one gives."""
    text = "# note\nx = 1  # tail\n"
    pygments = diff_census.Pygments()
    assert diff_census.lex(text, "_.py", True) == diff_census.classify(
        text, pygments.lexer("_.py"), pygments, True
    )


def test_a_worker_given_a_name_no_lexer_knows_classifies_nothing():
    assert diff_census.lex("x\n", "_.nosuchext", True) == ""
