"""Instruction text shared by every judge runner."""

from pathlib import Path

from .config import Task, resolve_instruction, resolve_output_style

PREAMBLE = """\
You are reviewing a code change as an independent judge.

Derive your assessment from the actual change. Any summary of the work you were
given is an unverified claim by the author and must not be taken as evidence.

The repository is read-only. You may write scratch files in the directory named
below, but you cannot and must not modify the code under review.

Respond with a single JSON object and nothing else:
{"ok": true|false, "summary": "one line", "findings": [
  {"severity": "high|medium|low", "file": "path", "line": 0, "issue": "what is wrong"}
]}
Set "ok": false only for problems you can point to in the change.
"""

LOCATIONS = """
Repository under review: {root}
It is read-only and sits outside your working directory, so reach it through
shell commands rather than file-reading tools, which are scoped to your working
directory: `git -C {root} diff`, `git -C {root} log`, `cat {root}/<path>`.

Scratch directory: {scratch}
Your working directory, and the only writable location available to you. Write
any temp scripts, notes or intermediate output there. Writes elsewhere fail.
"""


def build(task: Task, root: Path, scratch: Path, *, with_style: bool = False) -> str:
    """The full instruction handed to a judge.

    Both paths are stated explicitly because judges run with the scratch
    directory as their working directory, not the repository. That keeps each
    agent CLI's own bookkeeping (Claude writes a `.claude/` directory beside
    its cwd) out of the tree under review.

    ``with_style`` appends the task's output style. It is inlined rather than
    selected by name because a plugin's styles are namespaced and only resolve
    while the plugin is enabled, and the docs leave open whether a named style
    applies under ``--system-prompt`` at all.
    """
    text = PREAMBLE + LOCATIONS.format(root=root, scratch=scratch)
    text += "\n" + resolve_instruction(task, root)
    if with_style:
        style = resolve_output_style(task.output_style, root)
        if style:
            text += "\n\n# Output style\n\n" + style
    return text
