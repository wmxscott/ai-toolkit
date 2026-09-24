"""`stack_overlap.py` — glob semantics, plan parsing, and the verdicts it reaches.

The glob cases carry the weight here. Under-matching is the dangerous direction: a fence
that owns nothing reports a clean branch, which is the exact failure the gate exists to
prevent, so a pattern this gate does not implement is refused rather than read as a
literal.
"""

import fnmatch

import pytest
from census_support import SCRIPTS, stack_overlap

PlanError = stack_overlap.PlanError


def matched(path, pattern):
    return stack_overlap.match_any(path, stack_overlap.compile_globs([pattern]))


# ---------------------------------------------------------------------------
# Glob semantics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path, pattern, owned",
    [
        # A single `*` stays inside one path segment. This is the whole reason the script
        # does not use fnmatch; STACK_OVERLAP.md has the table.
        ("src/b.py", "src/*.py", True),
        ("src/a/b.py", "src/*.py", False),
        ("migrations/20260101_billing_add.sql", "migrations/*_billing_*.sql", True),
        ("migrations/sub/2026_billing.sql", "migrations/*_billing_*.sql", False),
        # `**` as a whole segment crosses them.
        ("src/b.py", "src/**", True),
        ("src/a/b/c.py", "src/**", True),
        ("src", "src/**", False),  # trailing `**` needs at least one segment
        ("srcs/b.py", "src/**", False),
        ("src/a/b/c.py", "src/**/*.py", True),
        ("src/b.py", "src/**/*.py", True),  # ...and matches zero segments in the middle
        ("a/b", "a/**/b", True),
        ("a/x/y/b", "a/**/b", True),
        ("a/b/x.py", "**/x.py", True),
        ("x.py", "**/x.py", True),
        ("x.pyc", "**/x.py", False),
        # `**` inside a segment is not a whole segment: it degrades to a single `*`.
        ("src/a/b.py", "src/**.py", False),
        ("src/ab.py", "src/**.py", True),
        # A pattern that matches a directory matches everything under it, as in gitignore.
        ("src/billing/api/routes.py", "src/billing", True),
        ("src/billing/api/routes.py", "src/billing/**", True),
        ("src/billingx/routes.py", "src/billing", False),
        ("src/a/b.py", "src/*", True),  # `src/a` is a directory, so its tree matches
        ("src/billing/x.py", "src/billing/", True),  # a trailing slash is a directory too
        # Exact paths and `?`.
        ("stow/p/.config/mise/claude", "stow/p/.config/mise/claude", True),
        ("a/b.py", "?/b.py", True),
        ("ab/b.py", "?/b.py", False),
        ("./src/b.py", "src/*.py", True),  # paths and patterns are normalised
    ],
)
def test_glob_ownership(path, pattern, owned):
    assert (matched(path, pattern) is not None) is owned


def test_fnmatch_over_matches_where_this_does_not():
    """The divergence from fnmatch, pinned. fnmatch's `*` crosses `/`, so it would call
    this an overlap. Under-matching is the dangerous direction, but over-matching is
    still wrong."""
    assert fnmatch.fnmatch("src/a/b.py", "src/*.py") is True
    assert matched("src/a/b.py", "src/*.py") is None


def test_match_any_reports_which_glob_hit():
    assert matched("src/billing/api.py", "src/billing/**") == "src/billing/**"


def test_match_any_misses_cleanly():
    assert matched("src/auth/api.py", "src/billing/**") is None


@pytest.mark.parametrize(
    "pattern",
    [
        "migrations/2026[01]*_billing_*.sql",
        "src/[ab].py",
        "!src/vendor/**",
    ],
)
def test_unsupported_syntax_is_not_silently_literal(pattern):
    """Matching `migrations/2026[01]*.sql` literally would own nothing and report a clean
    branch — the false clean the whole gate exists to prevent."""
    assert stack_overlap.unsupported_syntax(pattern) is not None


@pytest.mark.parametrize(
    "pattern",
    [
        "src/**",
        "migrations/*_billing_*.sql",
        "a/b!c/**",
        "src/?.py",
    ],
)
def test_supported_syntax_compiles(pattern):
    assert stack_overlap.unsupported_syntax(pattern) is None
    assert stack_overlap.compile_globs([pattern])


def test_a_character_class_is_refused_at_compile_time():
    with pytest.raises(PlanError):
        stack_overlap.compile_globs(["migrations/2026[01]*.sql"])


def test_a_negation_is_refused_at_compile_time():
    with pytest.raises(PlanError):
        stack_overlap.compile_globs(["!src/vendor/**"])


# ---------------------------------------------------------------------------
# Glob lists
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, globs",
    [
        ("src/a/**, migrations/*.sql", ["src/a/**", "migrations/*.sql"]),
        ("`src/a/**`, `b/*`", ["src/a/**", "b/*"]),  # backticks are stripped
        ("—", []),  # an em dash means none
        ("`—`", []),  # backticked, it still means none
        ("", []),
        ("a/**\nb/**", ["a/**", "b/**"]),  # newlines separate too
    ],
)
def test_split_globs(text, globs):
    assert stack_overlap.split_globs(text) == globs


def test_strict_mode_rejects_a_bare_glob():
    with pytest.raises(PlanError):
        stack_overlap.split_globs("src/a/**", True)


def test_strict_mode_rejects_a_fused_pair():
    with pytest.raises(PlanError):
        stack_overlap.split_globs("`a/**` `b/**`", True)


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------

PLAN = """## Stacks and phases

### Stack A — auth

- **Base:** `main`
- **Owns:** `src/auth/**`, `docs/plans/tkww24-*`,
  `migrations/*_auth_*.sql`
- **Independent of:** B (no shared surface)
- **Depends on:** —

| Phase | Lands | Depends on |

### Stack B — billing

- **Base:** `main`
- **Owns:** `src/billing/**`
- **Independent of:** A
- **Depends on:** —

### Stack C — chrome

- **Owns:** —
"""


def test_parse_plan():
    assert stack_overlap.parse_plan(PLAN) == {
        "A": ["src/auth/**", "docs/plans/tkww24-*", "migrations/*_auth_*.sql"],
        "B": ["src/billing/**"],
        "C": [],
    }


def test_owns_stops_at_the_next_bullet():
    assert stack_overlap.parse_plan(
        "### Stack A — x\n- **Owns:** `a/**`\n- **Independent of:** B, C\n"
    ) == {"A": ["a/**"]}


def test_owns_stops_at_a_blank_line():
    assert stack_overlap.parse_plan(
        "### Stack A — x\n- **Owns:** `a/**`\n\n  Prose that is not part of the field.\n"
    ) == {"A": ["a/**"]}


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("# A plan\n\nprose only\n", id="no stack headings"),
        pytest.param(
            "### Stack A — x\n\n- **Base:** `main`\n- **Depends on:** —\n",
            id="stack with no Owns field",
        ),
        pytest.param(
            "### Stack A — x\n\n- **Owns:** `a/**`\n- **Owns:** `b/**`\n",
            id="two Owns fields in one stack",
        ),
        pytest.param("### Stack A — x\n\n- **Owns:** src/a/**\n", id="unbackticked entry"),
        pytest.param(
            "### Stack A — x\n\n- **Owns:** `a/**` (and friends)\n", id="prose in the Owns field"
        ),
        pytest.param(
            "### Stack A — x\n- **Owns:** `a/**`\n### Stack A — y\n- **Owns:** `b/**`\n",
            id="duplicate stack id",
        ),
    ],
)
def test_a_plan_that_cannot_be_read_raises(text):
    """A plan that cannot be read exits 2, never 0 — a false clean is the failure this
    gate exists to prevent, and plan parsing is the last-resort input."""
    with pytest.raises(PlanError):
        stack_overlap.parse_plan(text)


def test_other_globs_exclude_mine():
    """Self-exclusion: a stack is never fenced by its own paths, or every PR would fail."""
    assert stack_overlap.other_globs(stack_overlap.parse_plan(PLAN), "A") == ["src/billing/**"]


def test_other_globs_from_b():
    assert stack_overlap.other_globs(stack_overlap.parse_plan(PLAN), "B") == [
        "src/auth/**",
        "docs/plans/tkww24-*",
        "migrations/*_auth_*.sql",
    ]


def test_an_unknown_stack_id_cannot_be_excluded():
    with pytest.raises(PlanError):
        stack_overlap.other_globs(stack_overlap.parse_plan(PLAN), "Z")


def test_the_shipped_template_parses():
    """The stack block `template.md` teaches is the format this script parses."""
    template = (SCRIPTS.parent / "template.md").read_text()
    stacks = stack_overlap.parse_plan(template)
    assert sorted(stacks) == ["A"]
    assert stacks["A"] == ["src/billing/**", "migrations/2026*_billing_*.sql"]


# ---------------------------------------------------------------------------
# Verdicts
#
# Exit codes: 0 clean, 1 an overlap was found, 2 could not measure.
# ---------------------------------------------------------------------------


def test_clean_branch_from_owns(overlap):
    assert (
        overlap("stack-a-clean", "main", "--owns", "src/billing/**,migrations/*_billing_*.sql") == 0
    )


def test_clean_branch_from_the_plan(overlap):
    """Stack A is excluded from its own globs, or the branch would fence itself."""
    assert overlap("stack-a-clean", "main", "--stack", "A") == 0


def test_clean_branch_from_stack_owns_env(overlap, monkeypatch):
    monkeypatch.setenv(stack_overlap.OWNS_ENV, "src/billing/**")
    assert overlap("stack-a-clean", "main") == 0


def test_clean_branch_from_stack_id_env(overlap, monkeypatch):
    monkeypatch.setenv(stack_overlap.STACK_ENV, "A")
    assert overlap("stack-a-clean", "main") == 0


def test_the_same_branch_checked_as_stack_b_fails(overlap):
    """Self-exclusion, proved. Run the clean branch as if it were stack B: A's own paths
    are now the fence, and the branch that passed a moment ago fails."""
    assert overlap("stack-a-clean", "main", "--stack", "B") == 1


def test_overlap_branch_from_owns(overlap):
    assert (
        overlap(
            "stack-a-overlap",
            "main",
            "--owns",
            "src/billing/**",
            "--owns",
            "migrations/*_billing_*.sql",
        )
        == 1
    )


def test_overlap_branch_from_the_plan(overlap):
    assert overlap("stack-a-overlap", "main", "--stack", "A") == 1


def test_a_single_star_does_not_reach_into_a_subdirectory(overlap):
    """`src/*.py` owns only the top level of `src/`, so it does not reach
    `src/billing/invoice.py` — the file this branch actually strays into."""
    assert overlap("stack-a-overlap", "main", "--owns", "src/*.py") == 0


def test_a_double_star_does(overlap):
    assert overlap("stack-a-overlap", "main", "--owns", "src/**") == 1


def test_a_character_class_is_refused_rather_than_read_as_a_literal(overlap):
    """This glob is meant to catch the billing migration on this very branch. Read
    literally it would miss it and report a clean branch."""
    assert overlap("stack-a-overlap", "main", "--owns", "migrations/2026[01]*_billing_*.sql") == 2


def test_a_leading_bang_negation_is_refused(overlap):
    assert overlap("stack-a-overlap", "main", "--owns", "!src/billing/**") == 2


def test_a_plan_source_with_nothing_saying_which_stack_is_mine(overlap):
    assert overlap("stack-a-overlap", "main") == 2


def test_a_stack_id_that_is_not_in_the_plan(overlap):
    assert overlap("stack-a-overlap", "main", "--stack", "Z") == 2


def test_a_plan_that_does_not_exist(overlap):
    assert overlap("stack-a-overlap", "main", "--stack", "A", "--plan", "docs/plans/nope.md") == 2


@pytest.mark.parametrize(
    "body, reason",
    [
        pytest.param("# A plan\n\nprose, no stack blocks\n", "no stack blocks", id="no blocks"),
        pytest.param(
            "### Stack A — x\n\n- **Owns:** `src/auth/**`\n### Stack B — y\n\n- **Base:** `main`\n",
            "a stack with no Owns field",
            id="no Owns",
        ),
        pytest.param(
            "### Stack A — x\n\n- **Owns:** src/auth/**\n",
            "an Owns field that is not backticked globs",
            id="unbackticked",
        ),
        pytest.param(
            "### Stack A — x\n\n- **Owns:** `src/auth/**`\n\n### Stack B — y\n\n- **Owns:** —\n",
            "every other stack owns nothing: no fence, so no verdict",
            id="no fence",
        ),
    ],
)
def test_a_plan_that_yields_no_usable_fence(stacks, overlap, body, reason):
    stacks.write("docs/plans/broken.md", body)
    assert (
        overlap("stack-a-overlap", "main", "--stack", "A", "--plan", "docs/plans/broken.md") == 2
    ), reason


def test_two_plans_with_stack_headings_is_ambiguous_not_a_default(stacks, overlap):
    """Discovery is over tracked files, so an untracked second plan is invisible to it
    until it is added."""
    stacks.write("docs/plans/broken.md", "### Stack A — x\n\n- **Owns:** `src/auth/**`\n")
    stacks.git("add", "docs/plans/broken.md")
    assert overlap("stack-a-overlap", "main", "--stack", "A") == 2


# ---------------------------------------------------------------------------
# The base chain
#
# `gh stack view --json` reports each entry's `base` as a SHA rather than a branch name,
# so the parent is the entry below this one in the list. The shape is whatever a given
# gh-stack build emits, so every departure from the expected one degrades to "no parent"
# rather than raising: a base chain that throws would take the gate down on a tool
# upgrade, and falling through to the next source in the chain is always safe.
# ---------------------------------------------------------------------------


class _Proc:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout, self.returncode = stdout, returncode


@pytest.fixture
def gh_stack(monkeypatch):
    """Answer `gh stack view --json` with a payload, and pretend gh is installed."""

    def install(payload, returncode=0):
        monkeypatch.setattr(stack_overlap, "tool", lambda name: True)
        monkeypatch.setattr(
            stack_overlap.subprocess, "run", lambda *a, **k: _Proc(payload, returncode)
        )

    return install


@pytest.mark.parametrize(
    "branch, parent",
    [
        ("b", "a"),  # the entry below this one
        ("c", "b"),
        ("a", None),  # the bottom of the stack has no parent
        ("zz", None),  # a branch that is not in the stack at all
    ],
)
def test_the_stack_parent_is_the_entry_below(gh_stack, branch, parent):
    gh_stack(b'{"branches":[{"name":"a"},{"name":"b"},{"name":"c"}]}')
    git = stack_overlap.Git("/nowhere")
    assert stack_overlap.stack_parent(git, branch) == parent


@pytest.mark.parametrize(
    "payload, why",
    [
        (b'[{"name":"a"}]', "a top-level array instead of an object"),
        (b'{"branches":null}', "a null branches field"),
        (b"{}", "no branches field"),
        (b'{"branches":[{"nome":"a"}]}', "an entry with no name"),
        (b"not json at all", "a payload that is not JSON"),
        (b"", "an empty payload"),
    ],
)
def test_an_unexpected_payload_degrades_rather_than_raising(gh_stack, payload, why):
    gh_stack(payload)
    git = stack_overlap.Git("/nowhere")
    assert stack_overlap.stack_parent(git, "a") is None, why


def test_a_failing_gh_stack_has_no_parent(gh_stack):
    gh_stack(b'{"branches":[{"name":"a"},{"name":"b"}]}', returncode=1)
    assert stack_overlap.stack_parent(stack_overlap.Git("/nowhere"), "b") is None


def test_without_gh_there_is_no_parent_and_no_subprocess(monkeypatch):
    monkeypatch.setattr(stack_overlap, "tool", lambda name: False)

    def explode(*a, **k):
        raise AssertionError("gh was invoked despite not being installed")

    monkeypatch.setattr(stack_overlap.subprocess, "run", explode)
    assert stack_overlap.stack_parent(stack_overlap.Git("/nowhere"), "b") is None
    assert stack_overlap.pr_base(stack_overlap.Git("/nowhere")) is None


def test_an_explicit_base_wins_over_everything(monkeypatch):
    monkeypatch.setenv(stack_overlap.BASE_ENV, "from-env")
    git = stack_overlap.Git("/nowhere")
    assert stack_overlap.resolve_base(git, "from-argv", "b") == "from-argv"


def test_the_env_var_wins_over_the_inferred_chain(monkeypatch):
    monkeypatch.setenv(stack_overlap.BASE_ENV, "from-env")

    def explode(*a, **k):
        raise AssertionError(f"the chain ran despite ${stack_overlap.BASE_ENV} being set")

    monkeypatch.setattr(stack_overlap, "stack_parent", explode)
    assert stack_overlap.resolve_base(stack_overlap.Git("/nowhere"), None, "b") == "from-env"
