"""Verdict cache, block counter, and judge scratch directories."""

import hashlib
import json
import shutil
from pathlib import Path

from .constants import STATE_DIRNAME, state_home


class State:
    """Everything arbiter persists between runs.

    Repository state (verdict cache, block counter) lives in the working tree so
    it is per-checkout and visible. Judge scratch lives outside it -- see
    ``scratch_root``.
    """

    def __init__(self, root: Path):
        self.root = root
        self.dir = root / STATE_DIRNAME
        self.state_dir = self.dir / "state"

    # -- repository state ---------------------------------------------------

    def ensure(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        gitignore = self.dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*\n")

    def _read_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def load_verdicts(self, change_hash: str) -> dict:
        return self._read_json(self.state_dir / f"{change_hash}.json")

    def save_verdicts(self, change_hash: str, verdicts: dict) -> None:
        self.ensure()
        (self.state_dir / f"{change_hash}.json").write_text(json.dumps(verdicts, indent=2))

    # -- block counter ------------------------------------------------------

    @property
    def _blocks_path(self) -> Path:
        return self.state_dir / "blocks.json"

    def record_block(self, change_hash: str) -> int:
        """Count consecutive blocks on an identical change set."""
        self.ensure()
        data = self._read_json(self._blocks_path)
        count = (data.get("count", 0) + 1) if data.get("hash") == change_hash else 1
        self._blocks_path.write_text(json.dumps({"hash": change_hash, "count": count}))
        return count

    def clear_blocks(self) -> None:
        self._blocks_path.unlink(missing_ok=True)

    # -- judge scratch ------------------------------------------------------

    @property
    def scratch_root(self) -> Path:
        """Judge scratch, deliberately outside the repository.

        A judge's sandbox denies writes to the repo root, and a nested
        allowWrite does not override that deny: scratch placed inside the repo
        is unwritable, leaving a judge unable to write the temp files it is
        explicitly permitted.
        """
        slug = hashlib.sha256(str(self.root).encode()).hexdigest()[:12]
        return state_home() / "scratch" / f"{self.root.name}-{slug}"

    def scratch_for(self, change_hash: str, task_name: str) -> Path:
        path = self.scratch_root / change_hash / task_name
        path.mkdir(parents=True, exist_ok=True)
        return path

    # -- teardown -----------------------------------------------------------

    def purge_scratch(self) -> Path | None:
        """Remove this repository's scratch tree. Refuses anything outside the state home."""
        root = self.scratch_root
        if not root.exists() or root.is_symlink():
            return None
        resolved = root.resolve()
        if not resolved.is_relative_to(state_home().resolve()):
            return None
        shutil.rmtree(resolved)
        return resolved

    def purge_repo_state(self) -> Path | None:
        """Remove the in-repo state directory.

        The only destructive operation in the tool, on a path derived from git,
        so it refuses a symlink or anything resolving outside the repository.
        """
        target = self.dir
        if not target.exists():
            return None
        if target.is_symlink():
            raise ValueError(f"refusing to clean {target}: it is a symlink")
        resolved, root = target.resolve(), self.root.resolve()
        if resolved != root / STATE_DIRNAME or not resolved.is_relative_to(root):
            raise ValueError(f"refusing to clean {resolved}: outside {root}")
        shutil.rmtree(resolved)
        return resolved
