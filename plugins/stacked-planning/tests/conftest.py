"""Fixtures for the diff census and stack overlap suites. The scripts themselves, and the
helpers a test imports by name, come from `census_support`."""

import importlib.util
import os
import pathlib
import subprocess
import sys

import pytest


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Registered under a plain name so test modules can import it: under
# `--import-mode=importlib` neither this directory nor conftest is importable.
support = _load("census_support", pathlib.Path(__file__).with_name("census_support.py"))
diff_census, stack_overlap, HEADER = support.diff_census, support.stack_overlap, support.HEADER


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """No inherited configuration of any kind, and a working directory outside any
    repository, so a test that means "no config" gets one."""
    for name in (
        diff_census.CONFIG_ENV,
        stack_overlap.OWNS_ENV,
        stack_overlap.STACK_ENV,
        stack_overlap.PLAN_ENV,
        stack_overlap.BASE_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def write(tmp_path):
    def _write(body, name="config.toml"):
        path = tmp_path / name
        path.write_text(body)
        return str(path)

    return _write


@pytest.fixture
def load_raw(write):
    def _load(body):
        return diff_census.load_config(write(body))

    return _load


@pytest.fixture
def error_raw(write):
    def _error(body):
        with pytest.raises(diff_census.ConfigError) as caught:
            diff_census.load_config(write(body))
        return str(caught.value)

    return _error


@pytest.fixture
def load(load_raw):
    """Parse a body under a valid header, and return the Config."""
    return lambda body: load_raw(HEADER + body)


# ---------------------------------------------------------------------------
# Git fixtures
#
# Acquisition is tested against real repositories rather than recorded output, because
# what is under test is largely git's own formatting — which record shapes a rename, a
# binary or a gitlink produce is the thing that has to be got right.
# ---------------------------------------------------------------------------


class Repo:
    """A throwaway repository. Identity is fixed and signing is off, so a test never
    reaches the user's configuration or asks a hardware key for a touch."""

    SETTINGS = (
        ("user.email", "test@example.test"),
        ("user.name", "Test"),
        ("commit.gpgsign", "false"),
        ("tag.gpgsign", "false"),
        ("core.autocrlf", "false"),
        ("gc.auto", "0"),
    )

    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main", ".")
        for key, value in self.SETTINGS:
            self.git("config", key, value)

    def git(self, *args):
        proc = subprocess.run(("git", *args), cwd=self.root, capture_output=True)
        if proc.returncode != 0:
            raise AssertionError(
                "git {}: {}".format(" ".join(args), proc.stderr.decode("utf-8", "replace"))
            )
        return proc.stdout.decode("utf-8", "replace")

    def write(self, path, text, mode=None):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            target.write_bytes(text)
        else:
            target.write_text(text)
        if mode is not None:
            os.chmod(target, mode)
        return target

    def link(self, path, target):
        (self.root / path).symlink_to(target)

    def gitlink(self, path, oid):
        """A submodule entry, written straight into the index. The pointed-at commit need
        not exist for a diff to report the change, and conjuring one would need a second
        repository and the file-protocol allowance a bare gitlink does not."""
        self.git("update-index", "--add", "--cacheinfo", f"160000,{oid},{path}")

    def commit(self, message="c", add=True):
        """Commit the working tree, or with `add=False` only what the index already holds
        — a gitlink has no directory for `git add -A` to find, and would be staged as a
        deletion the moment it looked."""
        if add:
            self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path):
    """An empty repository with one commit already in it, so `HEAD~1` is available."""
    made = Repo(tmp_path / "repo")
    made.commit("root")
    return made


# ---------------------------------------------------------------------------
# Overlap fixtures
#
# Two stacks with one deliberate overlap between them, and two branches off the same base:
# one that stays inside stack A's paths and one that strays into stack B's. Both verdicts
# come out of the same repository, so a case cannot pass by measuring the wrong thing.
# ---------------------------------------------------------------------------

TWO_STACKS = """## Stacks and phases

### Stack A — auth

- **Base:** `main`
- **Owns:** `src/auth/**`, `migrations/*_auth_*.sql`
- **Independent of:** B
- **Depends on:** —

### Stack B — billing

- **Base:** `main`
- **Owns:** `src/billing/**`,
  `migrations/*_billing_*.sql`
- **Independent of:** A
- **Depends on:** —
"""


@pytest.fixture
def stacks(tmp_path):
    """Two stacks, and the two branches the overlap cases are asked about."""
    made = Repo(tmp_path / "stacks")
    made.write("src/auth/login.py", "x = 1\n")
    made.write("src/billing/invoice.py", "y = 1\n")
    made.write("migrations/20260101_auth_users.sql", "SELECT 1;\n")
    made.write("docs/plans/2026-01-01-two-stacks.md", TWO_STACKS)
    made.commit("base")

    made.git("checkout", "-q", "-b", "stack-a-clean")
    made.write("src/auth/login.py", "x = 2\n")
    made.write("migrations/20260101_auth_users.sql", "SELECT 1;\nSELECT 2;\n")
    made.write("README.md", "notes\n")  # owned by no stack: not an overlap
    made.commit("stack A work")

    made.git("checkout", "-q", "main")
    made.git("checkout", "-q", "-b", "stack-a-overlap")
    made.write("src/auth/login.py", "x = 3\n")
    made.write("src/billing/invoice.py", "y = 2\n")  # stack B's file
    made.write("migrations/20260202_billing_fees.sql", "SELECT 3;\n")  # and its glob
    made.commit("stack A strays into B")
    return made


@pytest.fixture
def overlap(stacks, monkeypatch):
    """Run the overlap gate on one of the fixture's branches and return its exit code.
    Exit codes are what callers consume, so the cases go through `main` rather than
    around it."""

    def _overlap(branch, *argv):
        stacks.git("checkout", "-q", branch)
        monkeypatch.chdir(stacks.root)
        return stack_overlap.main(list(argv))

    return _overlap


@pytest.fixture
def acquire(repo):
    """Acquire the diff of `repo`, defaulting to three-dot against the previous commit."""

    def _acquire(mode="two-dot", base="HEAD~1", head="HEAD", **kwargs):
        git = diff_census.Git.open(str(repo.root))
        refs = diff_census.resolve_refs(git, mode, base=base, head=head)
        return diff_census.acquire(git, refs, **kwargs)

    return _acquire


@pytest.fixture
def by_path(acquire):
    """The acquired files keyed by path, which is how nearly every case reads them."""
    return lambda **kwargs: {f.path: f for f in acquire(**kwargs).files}


@pytest.fixture
def error(error_raw):
    """Parse a body expected to fail, and return the message."""
    return lambda body: error_raw(HEADER + body)


# ---------------------------------------------------------------------------
# Census fixtures
#
# The pipeline asks git for nothing — it takes a diff and a configuration and sorts what
# it is given — so these build the diff by hand, which is what lets a case name exactly
# the lines it is about and stop there.
# ---------------------------------------------------------------------------


@pytest.fixture
def census(load):
    """Take a census of a hand-built diff under a configuration body."""

    def _census(body, files, **kwargs):
        diff = diff_census.Diff(
            refs=diff_census.Refs(mode="two-dot", base="main"), files=list(files)
        )
        return diff_census.take_census(diff, load(body), **kwargs)

    return _census


@pytest.fixture
def report(census):
    """The JSON a census reports, which is the shape everything downstream reads."""
    return lambda body, files, **kwargs: diff_census.census_json(census(body, files, **kwargs))


@pytest.fixture
def gate(repo, monkeypatch, capsys):
    """Run the script's own entry point inside a repository, and return its exit code
    with whatever it wrote. Exit codes are the contract callers actually consume, so the
    cases about them go through `main` rather than around it."""

    def _gate(*argv, config=None):
        monkeypatch.chdir(repo.root)
        args = list(argv)
        if config is not None:
            path = repo.root / "census.toml"
            path.write_text(HEADER + config)
            args = ["--config", str(path), *args]
        code = diff_census.main(args)
        return code, capsys.readouterr()

    return _gate
