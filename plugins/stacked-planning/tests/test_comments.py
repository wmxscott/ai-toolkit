"""Comment detection: what a line's comment state is, where the answer is read from, and
what happens when it cannot be read at all.

The cases that matter are the ones a regex gets wrong — a `#` inside a string, a shebang,
a heading, a fenced block, and every continuation line of a block comment — so they are
asserted explicitly rather than left to the lexer's reputation.
"""

import os

import pytest
from census_support import diff_census


@pytest.fixture
def census(repo):
    """Classify the last commit's diff, and return the FileDiffs keyed by path.

    Everything goes through the real acquisition path: the patch supplies the line
    numbers, and the classification is looked up by them, which is the whole mechanism."""

    def _census(**kwargs):
        git = diff_census.Git.open(str(repo.root))
        refs = diff_census.resolve_refs(git, "two-dot", base="HEAD~1")
        diff = diff_census.acquire(git, refs, patch=True)
        comments = diff_census.Comments(git, **kwargs)
        diff_census.annotate(git, diff, comments)
        return diff, comments, {f.path: f for f in diff.files}

    return _census


@pytest.fixture
def states(repo, census):
    """The comment state of every line of one added file, in order."""

    def _states(name, text, **kwargs):
        repo.write(name, text)
        repo.commit("add " + name)
        return [line.comment for line in census(**kwargs)[2][name].lines]

    return _states


# ---------------------------------------------------------------------------
# The four states
# ---------------------------------------------------------------------------


def test_a_comment_only_line_is_only(states):
    assert states("a.py", "# a note\nx = 1\n") == ["only", "none"]


def test_code_with_a_comment_after_it_is_trailing(states):
    assert states("a.py", "x = 1  # a note\n") == ["trailing"]


def test_an_indented_comment_is_still_comment_only(states):
    assert states("a.py", "def f():\n    # a note\n    return 1\n") == ["none", "only", "none"]


def test_a_blank_line_carries_no_comment(states):
    assert states("a.py", "x = 1\n\ny = 2\n") == ["none", "none", "none"]


# ---------------------------------------------------------------------------
# What a regex gets wrong
# ---------------------------------------------------------------------------


def test_a_hash_inside_a_string_is_code(states):
    """The case the specification names: `color = "#000000"` is a colour, not a note."""
    assert states("a.py", 'color = "#000000"\n') == ["none"]


def test_a_hash_inside_a_string_with_a_real_comment_after_it_is_trailing(states):
    assert states("a.py", 'color = "#000000"  # the background\n') == ["trailing"]


def test_a_shebang_is_code(states):
    """A shebang is what the file runs under, not commentary about it. Pygments files it
    under `Comment.Hashbang`; the census does not, so it counts."""
    assert states("run.sh", "#!/bin/sh\necho one\n") == ["none", "none"]


def test_a_c_preprocessor_directive_is_code(states):
    """`#include` is `Comment.Preproc` to pygments and code to everybody else."""
    assert states("a.c", "#include <stdio.h>\nint x = 1;\n") == ["none", "none"]


def test_a_markdown_heading_is_not_a_comment(states):
    assert states("a.md", "# Heading\n\ntext\n")[0] == "none"


def test_markdown_fenced_code_is_lexed_as_the_language_it_declares(states):
    """A fenced block is handed to the language's own lexer, so a comment inside one is a
    comment and the code around it is code."""
    text = "# Heading\n\n```python\n# a note\nx = 1\n```\n"
    assert states("a.md", text) == ["none", "none", "none", "only", "none", "none"]


def test_a_heredoc_body_is_not_a_comment(states):
    """`# not a comment` inside a heredoc is data the script emits."""
    assert states("a.sh", "cat <<EOF\n# not a comment\nEOF\n") == ["none", "none", "none"]


# ---------------------------------------------------------------------------
# Block comments
# ---------------------------------------------------------------------------

BLOCK = """int a = 1;
/* one
   two
   three
   four
   five
   six
   seven
*/
int b = 2;
"""


def test_every_line_of_a_block_comment_is_comment_only(states):
    assert states("a.c", BLOCK) == (["none"] + ["only"] * 8 + ["none"])


def test_a_blank_line_inside_a_block_comment_belongs_to_the_comment(states):
    assert states("a.c", "/* one\n\n two */\nint b = 2;\n") == ["only", "only", "only", "none"]


def test_a_block_comment_classifies_across_hunk_boundaries(repo, census):
    """The point of lexing whole blobs. With `-U0` the two edits arrive as two hunks with
    no context, and neither changed line carries a comment marker of its own — the state
    is a property of the file, and only the file can supply it."""
    repo.write("a.c", BLOCK)
    repo.commit("before")
    repo.write("a.c", BLOCK.replace("   two", "   TWO").replace("   six", "   SIX"))
    repo.commit("edit inside the block")
    lines = census()[2]["a.c"].lines
    assert [(line.change, line.number, line.comment) for line in lines] == [
        ("del", 3, "only"),
        ("add", 3, "only"),
        ("del", 7, "only"),
        ("add", 7, "only"),
    ]


def test_a_deleted_line_is_read_from_the_pre_image(repo, census):
    """A `-` line no longer exists in the post-image, so its state comes from the file it
    was deleted from."""
    repo.write("a.py", "# a note\nx = 1\n")
    repo.commit("before")
    repo.write("a.py", "x = 1\n")
    repo.commit("drop the note")
    lines = census()[2]["a.py"].lines
    assert [(line.change, line.comment) for line in lines] == [("del", "only")]


def test_a_rename_reads_its_pre_image_under_the_old_path(repo, census):
    """The old name is what the pre-image's language was known by."""
    repo.write("a.py", "# a note\nx = 1\ny = 2\nz = 3\n")
    repo.commit("before")
    repo.git("mv", "a.py", "b.py")
    repo.write("b.py", "# a note\nx = 1\ny = 2\nZ = 3\n")
    repo.commit("rename and edit")
    lines = census()[2]["b.py"].lines
    assert [(line.change, line.comment) for line in lines] == [("del", "none"), ("add", "none")]


# ---------------------------------------------------------------------------
# Docstrings
# ---------------------------------------------------------------------------

DOCSTRING = 'def f():\n    """A doc."""\n    return 1\n'


def test_a_docstring_is_a_comment_by_default(states):
    assert states("a.py", DOCSTRING) == ["none", "only", "none"]


def test_a_docstring_is_code_when_the_switch_is_off(states):
    assert states("a.py", DOCSTRING, docstrings=False) == ["none", "none", "none"]


def test_an_ordinary_string_is_never_a_docstring(states):
    assert states("a.py", 'x = "not a doc"\n') == ["none"]


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


def test_without_pygments_everything_is_unknown_and_the_run_says_so(repo, census, monkeypatch):
    """A missing optional dependency is not a failure to measure. Every line classifies
    `unknown`, which counts as code, and the warning names what is missing."""

    def absent():
        raise ImportError("No module named 'pygments'")

    monkeypatch.setattr(diff_census, "Pygments", absent)
    repo.write("a.py", "# a note\nx = 1\n")
    repo.commit("add")
    _diff, comments, files = census()
    assert [line.comment for line in files["a.py"].lines] == ["unknown", "unknown"]
    assert comments.diagnostics.warnings
    assert "pygments" in comments.diagnostics.warnings[0]
    assert comments.diagnostics.blobs_lexed == 0


def test_a_file_no_lexer_knows_is_unknown_and_is_counted(repo, census):
    repo.write("a.zzzzz", "some bytes\n")
    repo.commit("add")
    _diff, comments, files = census()
    assert [line.comment for line in files["a.zzzzz"].lines] == ["unknown"]
    assert comments.diagnostics.unknown_lexer_files == 1


def test_a_file_over_the_size_cap_is_unknown_and_is_counted(repo, census):
    repo.write("a.py", "x = 1\n" * 200)
    repo.commit("add")
    _diff, comments, files = census(cap=16)
    assert {line.comment for line in files["a.py"].lines} == {"unknown"}
    assert comments.diagnostics.oversize_skipped_files == 1
    assert comments.diagnostics.blobs_lexed == 0


def test_a_binary_file_has_no_lines_to_classify(repo, census):
    repo.write("blob.bin", b"\x00\x01\x02one\x00")
    repo.commit("add")
    assert census()[2]["blob.bin"].lines == []


# ---------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------


def test_the_cache_lives_under_the_common_git_directory(repo):
    git = diff_census.Git.open(str(repo.root))
    assert diff_census.cache_dir(git) == str(repo.root / ".git" / "diff_census")


def test_the_cache_of_a_linked_worktree_is_the_repositorys_own(repo, tmp_path):
    """In a linked worktree `.git` is a file, so the specification's `.git/diff_census`
    is not a directory anything can write to. The common directory is, and it is shared:
    a blob lexed in one worktree is lexed for all of them."""
    linked = tmp_path / "linked"
    repo.git("worktree", "add", "-q", "-b", "side", str(linked))
    assert (linked / ".git").is_file()
    git = diff_census.Git.open(str(linked))
    assert diff_census.cache_dir(git) == str(repo.root / ".git" / "diff_census")


def test_a_cache_hit_classifies_the_same_as_no_cache_at_all(repo, census):
    repo.write("a.py", "#!/usr/bin/env python\n# a note\nx = 1  # trailing\n")
    repo.commit("add")
    cold = census()
    warm = census()
    fresh = census(cache=False)
    assert [ln.comment for ln in cold[2]["a.py"].lines] == ["none", "only", "trailing"]
    assert (
        [ln.comment for ln in warm[2]["a.py"].lines]
        == [ln.comment for ln in fresh[2]["a.py"].lines]
        == [ln.comment for ln in cold[2]["a.py"].lines]
    )
    assert (cold[1].diagnostics.blobs_lexed, cold[1].diagnostics.cache_hits) == (1, 0)
    assert (warm[1].diagnostics.blobs_lexed, warm[1].diagnostics.cache_hits) == (0, 1)
    assert (fresh[1].diagnostics.blobs_lexed, fresh[1].diagnostics.cache_hits) == (1, 0)


def test_no_cache_writes_nothing(repo, census):
    repo.write("a.py", "# a note\n")
    repo.commit("add")
    census(cache=False)
    assert not os.path.exists(str(repo.root / ".git" / "diff_census"))


def test_the_key_changes_with_the_docstring_setting(repo, census):
    """A configuration change has to invalidate, or the switch would be answered from a
    cache filled under the other setting."""
    repo.write("a.py", DOCSTRING)
    repo.commit("add")
    census()
    switched = census(docstrings=False)
    assert switched[1].diagnostics.cache_hits == 0
    assert [ln.comment for ln in switched[2]["a.py"].lines] == ["none", "none", "none"]


def test_the_key_changes_with_the_pygments_version(repo, census, monkeypatch):
    repo.write("a.py", "# a note\n")
    repo.commit("add")
    census()
    monkeypatch.setattr(diff_census.Pygments, "__init__", _versioned("99.99"))
    assert census()[1].diagnostics.cache_hits == 0


def _versioned(version):
    real = diff_census.Pygments.__init__

    def patched(self):
        real(self)
        self.version = version

    return patched


def test_an_unwritable_cache_directory_does_not_fail_the_run(repo, census, monkeypatch):
    """Nothing about a cache may turn a measurement into a failure to measure."""

    def boom(*args, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(diff_census.os, "makedirs", boom)
    repo.write("a.py", "# a note\n")
    repo.commit("add")
    assert [ln.comment for ln in census()[2]["a.py"].lines] == ["only"]


# ---------------------------------------------------------------------------
# Bounding the work
# ---------------------------------------------------------------------------


def test_a_lexer_is_looked_up_once_per_extension(repo, census, monkeypatch):
    """`get_lexer_for_filename` guesses at the filesystem on every call, so the answer is
    kept — four Python files ask pygments once."""
    for index in range(4):
        repo.write(f"f{index}.py", f"# a note\nx = {index}\n")
    repo.write("a.md", "text\n")
    repo.commit("add")
    asked = []
    real = diff_census.Pygments.lexer

    def counted(self, filename):
        asked.append(filename)
        return real(self, filename)

    monkeypatch.setattr(diff_census.Pygments, "lexer", counted)
    census()
    assert sorted(asked) == ["_.md", "_.py"]


def test_a_file_with_no_extension_is_looked_up_by_its_name(repo, census):
    repo.write("Makefile", "all:\n\techo one\n")
    repo.commit("add")
    assert census()[2]["Makefile"].lines[0].comment == "none"


def test_each_image_is_lexed_once_however_many_lines_changed(repo, census):
    repo.write("a.py", "\n".join(f"x{i} = {i}" for i in range(20)) + "\n")
    repo.commit("before")
    repo.write("a.py", "\n".join(f"y{i} = {i}" for i in range(20)) + "\n")
    repo.commit("rewrite")
    _diff, comments, files = census(cache=False)
    assert len(files["a.py"].lines) == 40
    assert comments.diagnostics.blobs_lexed == 2  # the pre-image and the post-image


# ---------------------------------------------------------------------------
# When it runs at all
# ---------------------------------------------------------------------------


def test_the_lexer_runs_only_for_a_configuration_that_asks_about_comments(load):
    asks = load('[diff_census.matchers.c]\nrules = [{ comment = ["only"] }]\n')
    silent = load('[diff_census.matchers.c]\nrules = [{ ext = ["py"] }]\n')
    assert diff_census.uses_facet(asks, "comment")
    assert not diff_census.uses_facet(silent, "comment")


def test_a_comment_facet_anywhere_in_the_configuration_counts(load):
    body = (
        "[diff_census.groups.production]\n"
        "limit = { changed = 400 }\n"
        'exclude = [{ comment = ["only", "trailing"] }]\n'
    )
    assert diff_census.uses_facet(load(body), "comment")


def test_a_line_left_unclassified_is_unanswerable_rather_than_none(repo, acquire):
    """Nothing classifies until something asks, so a run that never lexes leaves the facet
    with nothing to read — which is not the same as answering `none`."""
    repo.write("a.py", "# a note\n")
    repo.commit("add")
    changed = acquire(patch=True).files[0]
    assert [line.comment for line in changed.lines] == [None]
