"""Git repository access and change-set computation."""

import hashlib
import subprocess
from functools import cached_property
from pathlib import Path

from .constants import STATE_DIRNAME
from .errors import ConfigError


def git(*args: str, cwd: Path, check: bool = False) -> str:
    """Run git. A missing git binary or directory reads as empty output."""
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    except OSError as e:
        if check:
            raise ConfigError(f"git {' '.join(args)} failed: {e}") from e
        return ""
    if check and proc.returncode != 0:
        raise ConfigError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


class Repository:
    """The repository under review, and what changed in it."""

    def __init__(self, root: Path):
        self.root = root

    @classmethod
    def discover(cls, start: Path) -> "Repository | None":
        """Walk up to the git root. Returns None outside a repository."""
        out = git("rev-parse", "--show-toplevel", cwd=start)
        return cls(Path(out)) if out else None

    def _git(self, *args: str) -> str:
        return git(*args, cwd=self.root)

    @cached_property
    def default_branch(self) -> str | None:
        """Best-effort detection of the branch this work forked from."""
        ref = self._git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
        if ref:
            return ref.rsplit("/", 1)[-1]
        for name in ("main", "master"):
            if self._git("rev-parse", "--verify", "--quiet", name):
                return name
        return None

    @cached_property
    def _base(self) -> str:
        """The commit to diff against.

        The merge-base rather than HEAD, so work already committed on the branch
        is still gated -- which matches a worktree-per-branch workflow. On the
        default branch itself the merge-base is HEAD, so this degrades to
        uncommitted work only.
        """
        branch = self.default_branch
        if not branch:
            return "HEAD"
        merge_base = self._git("merge-base", "HEAD", branch)
        head = self._git("rev-parse", "HEAD")
        return merge_base if merge_base and merge_base != head else "HEAD"

    @cached_property
    def changed_paths(self) -> list[str]:
        """Repository-relative paths changed on this branch, plus untracked."""
        paths: set[str] = set()
        tracked = self._git("diff", "--name-only", self._base)
        if tracked:
            paths.update(tracked.splitlines())
        # Untracked files never appear in `git diff`, so they need their own pass.
        untracked = self._git("ls-files", "--others", "--exclude-standard")
        if untracked:
            paths.update(untracked.splitlines())
        return sorted(p for p in paths if p and not p.startswith(STATE_DIRNAME + "/"))

    @cached_property
    def change_hash(self) -> str:
        """Content hash over the change set.

        Hashing contents rather than the path list alone means a judge that
        passed is re-run when a file it reviewed is edited, but not when an
        unrelated file changes.
        """
        h = hashlib.sha256()
        for rel in self.changed_paths:
            h.update(rel.encode())
            try:
                h.update((self.root / rel).read_bytes())
            except (OSError, IsADirectoryError):
                h.update(b"\0missing")
        return h.hexdigest()[:16]
