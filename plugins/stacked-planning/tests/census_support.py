"""The two scripts, loaded by path, and the helpers the test modules share.

The scripts are `uv` scripts rather than package members, so they are executed as the
modules they are and registered under their own names, which is how a test module can
`import diff_census`.
"""

import importlib.util
import pathlib
import sys

SCRIPTS = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills"
    / "authoring-stacked-plans"
    / "scripts"
)
SCRIPT = SCRIPTS / "diff_census.py"

# Every config needs a version, so the fixtures supply one and the bodies in the tests
# carry only what they are about. `*_raw` fixtures skip it, for the tests that are about
# the header itself.
HEADER = "[diff_census]\nversion = 1\n"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


diff_census = _load("diff_census", SCRIPT)
stack_overlap = _load("stack_overlap", SCRIPTS / "stack_overlap.py")


def changed(path, lines=None, adds=0, dels=0, comments=(), **facets):
    """One changed file. `lines` are spelled `+text` or `-text` and numbered in order;
    without them the file carries numstat counts and no lines at all, which is the shape
    the fast path produces. `comments` gives the comment state of each line."""
    made = diff_census.FileDiff(file=diff_census.File(path, **facets))
    if lines is None:
        made.adds, made.dels = adds, dels
        return made
    made.lines = []
    for number, spelling in enumerate(lines, start=1):
        change = "add" if spelling[0] == "+" else "del"
        made.lines.append(diff_census.Line(change, spelling[1:].encode(), number))
        made.adds += change == "add"
        made.dels += change == "del"
    for line, state in zip(made.lines, comments, strict=False):
        line.comment = state
    return made
