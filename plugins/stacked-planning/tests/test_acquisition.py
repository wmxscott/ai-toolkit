"""Reading a diff: which refs are compared, what counts as a counted line, and what the
file facets are read from.

Every case runs against a real repository. The shapes under test are git's own — how a
rename, a binary, a gitlink and a mode change are reported — so recorded output would
only be testing the recording.
"""

import pytest
from census_support import diff_census


@pytest.fixture
def branched(repo):
    """A base branch that moved after the branch was cut, which is the difference
    three-dot exists to make: `moved.txt` belongs to the base, not to the branch."""
    repo.write("kept.txt", "one\n")
    repo.commit("before the cut")
    repo.git("checkout", "-q", "-b", "feature")
    repo.write("branch.txt", "added on the branch\n")
    repo.commit("on the branch")
    repo.git("checkout", "-q", "main")
    repo.write("moved.txt", "landed on the base after the cut\n")
    repo.commit("on the base")
    repo.git("checkout", "-q", "feature")
    return repo


# ---------------------------------------------------------------------------
# Refs
# ---------------------------------------------------------------------------


def test_three_dot_measures_only_what_the_branch_introduced(branched, by_path):
    files = by_path(mode="three-dot", base="main")
    assert set(files) == {"branch.txt"}


def test_two_dot_also_carries_what_landed_on_the_base(branched, by_path):
    files = by_path(mode="two-dot", base="main")
    assert set(files) == {"branch.txt", "moved.txt"}


def test_three_dot_reports_the_merge_base_it_used(branched, repo):
    git = diff_census.Git.open(str(repo.root))
    refs = diff_census.resolve_refs(git, "three-dot", base="main")
    assert refs.merge_base == repo.git("rev-parse", "main~1").strip()


def test_two_dot_has_no_merge_base_to_report(repo):
    git = diff_census.Git.open(str(repo.root))
    assert diff_census.resolve_refs(git, "two-dot", base="HEAD~1").merge_base is None


def test_an_unresolvable_merge_base_is_an_error(repo):
    repo.write("a.txt", "one\n")
    repo.commit("main")
    repo.git("checkout", "-q", "--orphan", "unrelated")
    repo.git("rm", "-rq", "--cached", ".")
    repo.write("b.txt", "two\n")
    repo.commit("unrelated")
    git = diff_census.Git.open(str(repo.root))
    with pytest.raises(diff_census.GitError) as caught:
        diff_census.resolve_refs(git, "three-dot", base="main")
    assert "merge base" in str(caught.value)


def test_a_base_that_names_nothing_is_an_error(repo):
    git = diff_census.Git.open(str(repo.root))
    with pytest.raises(diff_census.GitError):
        diff_census.resolve_refs(git, "three-dot", base="no-such-ref")


def test_staged_compares_the_index_against_head(repo, by_path):
    repo.write("staged.txt", "one\n")
    repo.git("add", "staged.txt")
    repo.write("unstaged.txt", "two\n")
    assert set(by_path(mode="staged")) == {"staged.txt"}


def test_working_tree_carries_both_staged_and_unstaged_work(repo, by_path):
    repo.write("staged.txt", "one\n")
    repo.git("add", "staged.txt")
    repo.write("unstaged.txt", "two\n")
    repo.git("add", "-N", "unstaged.txt")
    assert set(by_path(mode="working-tree")) == {"staged.txt", "unstaged.txt"}


def test_the_default_base_follows_origins_head(repo):
    repo.write("a.txt", "one\n")
    repo.commit("one")
    repo.git("update-ref", "refs/remotes/origin/trunk", "HEAD")
    repo.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
    git = diff_census.Git.open(str(repo.root))
    assert diff_census.default_base(git) == "origin/trunk"


def test_the_default_base_falls_back_to_the_local_default_branch(repo):
    repo.write("a.txt", "one\n")
    repo.commit("one")
    git = diff_census.Git.open(str(repo.root))
    assert diff_census.default_base(git) == "main"


def test_outside_a_repository_there_is_nothing_to_measure(tmp_path):
    with pytest.raises(diff_census.GitError):
        diff_census.Git.open(str(tmp_path))


# ---------------------------------------------------------------------------
# Line accounting
# ---------------------------------------------------------------------------


def test_an_empty_diff_counts_nothing(repo, acquire):
    repo.commit("changing nothing")
    diff = acquire()
    assert (diff.files, diff.adds, diff.dels, diff.changed) == ([], 0, 0, 0)


def test_an_added_file_counts_every_line(repo, by_path):
    repo.write("a.txt", "one\ntwo\nthree\n")
    repo.commit("add")
    assert (by_path()["a.txt"].adds, by_path()["a.txt"].dels) == (3, 0)


def test_a_deleted_file_counts_every_line(repo, by_path):
    repo.write("a.txt", "one\ntwo\n")
    repo.commit("add")
    (repo.root / "a.txt").unlink()
    repo.commit("remove")
    assert (by_path()["a.txt"].adds, by_path()["a.txt"].dels) == (0, 2)


def test_a_modified_line_counts_as_both_a_deletion_and_an_addition(repo, by_path):
    repo.write("a.txt", "one\ntwo\nthree\n")
    repo.commit("add")
    repo.write("a.txt", "one\nTWO\nthree\n")
    repo.commit("modify")
    changed = by_path()["a.txt"]
    assert (changed.adds, changed.dels, changed.changed) == (1, 1, 2)


def test_a_binary_file_counts_nothing_and_is_recorded(repo, acquire):
    repo.write("blob.bin", b"\x00\x01\x02one\x00")
    repo.commit("add")
    repo.write("blob.bin", b"\x00\x09\x02two\x00\x05\x00")
    repo.commit("change")
    diff = acquire()
    binary = diff.files[0]
    assert binary.path == "blob.bin"
    assert (binary.adds, binary.dels) == (0, 0)
    assert binary.binary and diff.binary_files == 1


def test_a_pure_rename_classifies_under_the_new_path_at_zero(repo, acquire):
    repo.write("old.txt", "one\ntwo\n")
    repo.commit("add")
    repo.git("mv", "old.txt", "new.txt")
    repo.commit("rename")
    renamed = acquire().files[0]
    assert renamed.path == "new.txt" and renamed.old_path == "old.txt"
    assert (renamed.adds, renamed.dels) == (0, 0)


def test_a_rename_with_edits_counts_under_the_new_path(repo, by_path):
    repo.write("old.txt", "one\ntwo\nthree\nfour\nfive\n")
    repo.commit("add")
    repo.git("mv", "old.txt", "new.txt")
    repo.write("new.txt", "one\nTWO\nthree\nfour\nfive\n")
    repo.commit("rename and edit")
    files = by_path()
    assert set(files) == {"new.txt"}
    assert (files["new.txt"].adds, files["new.txt"].dels) == (1, 1)


def test_without_rename_detection_the_same_change_is_a_delete_and_an_add(repo, by_path):
    repo.write("old.txt", "one\ntwo\n")
    repo.commit("add")
    repo.git("mv", "old.txt", "new.txt")
    repo.commit("rename")
    files = by_path(renames=False)
    assert set(files) == {"old.txt", "new.txt"}
    assert (files["new.txt"].adds, files["old.txt"].dels) == (2, 2)


def test_a_mode_only_change_counts_nothing(repo, by_path):
    repo.write("run.sh", "echo one\n", mode=0o644)
    repo.commit("add")
    repo.write("run.sh", "echo one\n", mode=0o755)
    repo.commit("chmod")
    changed = by_path()["run.sh"]
    assert (changed.adds, changed.dels, changed.file.mode) == (0, 0, "100755")


def test_a_submodule_counts_nothing_and_is_recorded(repo, acquire):
    repo.gitlink("sub", "0" * 39 + "1")
    repo.commit("add the gitlink", add=False)
    repo.gitlink("sub", "0" * 39 + "2")
    repo.commit("bump the gitlink", add=False)
    diff = acquire()
    gitlink = diff.files[0]
    assert (gitlink.path, gitlink.adds, gitlink.dels) == ("sub", 0, 0)
    assert gitlink.submodule and diff.submodule_changes == 1
    assert gitlink.file.mode == "160000"


def test_a_symlink_is_an_ordinary_one_line_text_change(repo, by_path):
    repo.write("target.txt", "one\n")
    repo.commit("add the target")
    repo.link("link", "target.txt")
    repo.commit("add the link")
    link = by_path()["link"]
    assert (link.adds, link.dels, link.file.mode) == (1, 0, "120000")
    assert not link.binary and not link.submodule


def test_a_path_with_a_space_and_an_accent_survives(repo, by_path):
    repo.write("a directory/naïve file.txt", "one\n")
    repo.commit("add")
    assert by_path()["a directory/naïve file.txt"].adds == 1


def test_the_totals_are_the_sum_over_the_files(repo, acquire):
    repo.write("a.txt", "one\ntwo\n")
    repo.write("b.txt", "three\n")
    repo.commit("add")
    diff = acquire()
    assert (diff.adds, diff.dels, diff.changed, len(diff.files)) == (3, 0, 3, 2)


# ---------------------------------------------------------------------------
# File metadata
# ---------------------------------------------------------------------------


def test_size_and_mode_come_from_the_post_image(repo, by_path):
    repo.write("a.txt", "one\n")
    repo.commit("add")
    repo.write("a.txt", "one\ntwo\nthree\n")
    repo.commit("grow")
    assert by_path()["a.txt"].file.size == len("one\ntwo\nthree\n")


def test_a_deletion_reads_its_facts_from_the_pre_image(repo, by_path):
    repo.write("run.sh", "echo one\necho two\n", mode=0o755)
    repo.commit("add")
    (repo.root / "run.sh").unlink()
    repo.commit("remove")
    gone = by_path()["run.sh"]
    assert (gone.file.size, gone.file.mode) == (len("echo one\necho two\n"), "100755")


def test_a_submodule_has_no_blob_to_size(repo, acquire):
    repo.gitlink("sub", "0" * 39 + "1")
    repo.commit("add the gitlink", add=False)
    repo.gitlink("sub", "0" * 39 + "2")
    repo.commit("bump the gitlink", add=False)
    assert acquire().files[0].file.size is None


def test_a_working_tree_file_is_sized_from_the_file_itself(repo, by_path):
    repo.write("a.txt", "one\n")
    repo.commit("add")
    repo.write("a.txt", "one\ntwo\n")
    assert by_path(mode="working-tree")["a.txt"].file.size == len("one\ntwo\n")


def test_the_path_derived_facets_are_available(repo, by_path):
    repo.write("src/pkg/thing.py", "x = 1\n")
    repo.commit("add")
    changed = by_path()["src/pkg/thing.py"].file
    assert (changed.dir, changed.name, changed.ext) == ("src/pkg", "thing.py", "py")
    assert changed.mime == "text/x-python"


def test_one_batch_check_answers_every_file(repo, acquire, monkeypatch):
    """The sizes come from one long-lived process, never a spawn per file."""
    for index in range(5):
        repo.write(f"f{index}.txt", "one\n")
    repo.commit("add")
    spawned = []
    real = diff_census.subprocess.Popen
    monkeypatch.setattr(
        diff_census.subprocess,
        "Popen",
        lambda *a, **k: (spawned.append(tuple(a[0])), real(*a, **k))[1],
    )
    diff = acquire()
    assert len(diff.files) == 5
    assert [a for a in spawned if "cat-file" in a] == [("git", "cat-file", "--batch-check")]


# ---------------------------------------------------------------------------
# The patch path
# ---------------------------------------------------------------------------


@pytest.fixture
def composite(repo):
    """Every shape of change at once, which is what the two paths have to agree about."""
    repo.write("edited.txt", "one\ntwo\nthree\nfour\nfive\n")
    repo.write("removed.txt", "gone\n")
    repo.write("moved.txt", "a\nb\nc\nd\ne\nf\n")
    repo.write("run.sh", "echo one\n", mode=0o644)
    repo.write("blob.bin", b"\x00\x01\x02one\x00")
    repo.write("target.txt", "pointed at\n")
    repo.gitlink("sub", "0" * 39 + "1")
    repo.commit("before")
    repo.write("edited.txt", "one\nTWO\nthree\nfour\nfive\nsix\n")
    (repo.root / "removed.txt").unlink()
    repo.write("added.txt", "new\nlines\n")
    repo.git("mv", "moved.txt", "elsewhere.txt")
    repo.write("elsewhere.txt", "a\nB\nc\nd\ne\nf\n")
    repo.write("run.sh", "echo one\n", mode=0o755)
    repo.write("blob.bin", b"\x00\x09\x02two\x00\x05\x00")
    repo.link("link", "target.txt")
    repo.write("nonewline.txt", "no trailing newline")
    repo.git("add", "-A")
    repo.gitlink("sub", "0" * 39 + "2")
    repo.commit("after", add=False)
    return repo


def test_both_paths_count_the_same_diff_the_same_way(composite, acquire):
    """Numstat counts what git counted; the patch counts the lines. The whole point of
    keeping both is that they never disagree about a diff either can read."""
    numstat = {f.path: (f.adds, f.dels) for f in acquire().files}
    patched = {f.path: (f.adds, f.dels) for f in acquire(patch=True).files}
    assert numstat == patched
    assert numstat["edited.txt"] == (2, 1)


def test_both_paths_see_the_same_files_and_the_same_facts(composite, acquire):
    def facts(diff):
        return [
            (f.path, f.status, f.old_path, f.binary, f.submodule, f.file.mode) for f in diff.files
        ]

    assert facts(acquire()) == facts(acquire(patch=True))


def test_both_paths_agree_on_the_totals(composite, acquire):
    numstat, patched = acquire(), acquire(patch=True)
    assert (numstat.adds, numstat.dels) == (patched.adds, patched.dels)
    assert (numstat.via, patched.via) == ("numstat", "patch")


def test_the_patch_path_carries_the_line_text_and_its_direction(repo, by_path):
    repo.write("a.txt", "one\ntwo\n")
    repo.commit("add")
    repo.write("a.txt", "one\nTWO\n")
    repo.commit("modify")
    lines = by_path(patch=True)["a.txt"].lines
    assert [(ln.change, ln.text) for ln in lines] == [("del", b"two"), ("add", b"TWO")]


def test_a_line_carries_its_number_in_the_image_it_belongs_to(repo, by_path):
    repo.write("a.txt", "one\ntwo\nthree\nfour\n")
    repo.commit("add")
    repo.write("a.txt", "one\ntwo\nTHREE\nfour\nfive\n")
    repo.commit("modify")
    lines = by_path(patch=True)["a.txt"].lines
    assert [(ln.change, ln.number) for ln in lines] == [("del", 3), ("add", 3), ("add", 5)]


def test_a_missing_trailing_newline_is_not_a_counted_line(repo, by_path):
    repo.write("a.txt", "one\n")
    repo.commit("add")
    repo.write("a.txt", "one\ntwo")
    repo.commit("drop the newline")
    changed = by_path(patch=True)["a.txt"]
    assert (changed.adds, changed.dels) == (1, 0)
    assert [ln.text for ln in changed.lines] == [b"two"]


def test_the_file_headers_are_not_counted_lines(repo, by_path):
    repo.write("a.txt", "one\n")
    repo.commit("add")
    changed = by_path(patch=True)["a.txt"]
    assert (changed.adds, changed.dels) == (1, 0)
    assert [ln.text for ln in changed.lines] == [b"one"]


def test_the_patch_path_records_no_lines_for_a_binary(composite, by_path):
    binary = by_path(patch=True)["blob.bin"]
    assert (binary.adds, binary.dels, binary.lines, binary.binary) == (0, 0, [], True)


def test_the_patch_path_counts_a_submodule_at_zero(composite, by_path):
    """Git writes a gitlink bump as a `-Subproject commit`/`+Subproject commit` pair, so
    the patch would count two lines of something nobody wrote."""
    gitlink = by_path(patch=True)["sub"]
    assert (gitlink.adds, gitlink.dels, gitlink.lines) == (0, 0, [])


def test_the_patch_path_counts_a_mode_only_change_at_zero(composite, by_path):
    assert by_path(patch=True)["run.sh"].changed == 0


def test_the_patch_path_classifies_a_rename_under_the_new_path(composite, by_path):
    moved = by_path(patch=True)["elsewhere.txt"]
    assert (moved.old_path, moved.adds, moved.dels) == ("moved.txt", 1, 1)


def test_the_numstat_path_reads_no_lines_at_all(composite, acquire):
    assert all(f.lines is None for f in acquire().files)


def test_a_line_whose_text_is_a_diff_header_is_still_a_counted_line(repo, by_path):
    """Counted lines carry a `+` or `-` of their own, so patch text inside a file cannot
    be mistaken for the patch's own framing."""
    repo.write("a.txt", "one\n")
    repo.commit("add")
    repo.write("a.txt", "one\ndiff --git a/x b/x\n@@ -1 +1 @@\n")
    repo.commit("add patch-looking text")
    changed = by_path(patch=True)["a.txt"]
    assert (changed.adds, changed.dels) == (2, 0)
    assert [ln.text for ln in changed.lines] == [b"diff --git a/x b/x", b"@@ -1 +1 @@"]


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


def test_external_diff_and_textconv_are_always_off(repo, acquire):
    """A repository configuring either would otherwise run an arbitrary program per file,
    at a cost the script does not control and producing output it cannot parse."""
    repo.write(".gitattributes", "* diff=boom\n")
    repo.git("config", "diff.boom.command", "false")
    repo.git("config", "diff.boom.textconv", "false")
    repo.write("a.txt", "one\n")
    repo.commit("add")
    assert acquire().files[-1].adds == 1


def test_the_working_directory_does_not_change_what_is_measured(repo, monkeypatch):
    repo.write("src/a.txt", "one\n")
    repo.commit("add")
    monkeypatch.chdir(repo.root / "src")
    git = diff_census.Git.open()
    refs = diff_census.resolve_refs(git, "two-dot", base="HEAD~1")
    assert [f.path for f in diff_census.acquire(git, refs).files] == ["src/a.txt"]
