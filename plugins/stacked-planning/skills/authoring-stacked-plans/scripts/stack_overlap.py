#!/usr/bin/env python3
"""Stack overlap gate — does this branch touch a path another live stack owns?

Standalone and dependency-free: python3 (3.8+) and git, nothing else; reads only; every
git call is rooted at the repository toplevel, so the verdict does not change with the
directory it runs from. It carries its own base chain, so it works wherever python3 and
git do.

    python3 stack_overlap.py [base-ref] --owns 'src/billing/**' --owns 'migrations/*.sql'

`--owns` names the paths owned by the OTHER live stack — the fence this branch must not
cross — not the paths this stack owns. Input precedence, first hit wins:

  1. `--owns` arguments
  2. $STACK_OWNS
  3. `Owns:` lines parsed from the plan, minus the caller's own stack (`--stack A`)

The base is resolved the same way: the positional argument, then $STACK_OVERLAP_BASE,
then this branch's parent in a `gh stack`, then the base branch of its open PR, then the
repository's default branch.

Parsing the plan is the fallback, so it fails loudly: an unreadable plan, a plan with no
stack blocks, a stack with no `Owns` field, or a caller who did not say which stack is
theirs all exit 2. A false clean is the whole failure this gate exists to prevent.

Exit: 0 clean, 1 intersection found, 2 could not measure.

Two stacks in flight is the riskiest thing `implementing-stacked-plans` permits, because
the failure surfaces late — both stacks three PRs deep before the conflict appears. Run
this at review time, alongside the size gate, while a second stack is active.

See STACK_OVERLAP.md for the glob semantics and why plan-parsing ranks last.
"""

import argparse
import json
import os
import re
import subprocess
import sys

OWNS_ENV = "STACK_OWNS"
STACK_ENV = "STACK_ID"
PLAN_ENV = "STACK_PLAN"
BASE_ENV = "STACK_OVERLAP_BASE"

# The plan artifact's containing directory, matched anywhere in a path so a monorepo's
# nested `docs/plans/` is found the same way a root-level one is.
PLAN_DIR = "/docs/plans/"


# ---------------------------------------------------------------------------
# Git, and the base chain
# ---------------------------------------------------------------------------


class Git:
    def __init__(self, root):
        self.root = root

    def run(self, *args):
        """stdout as bytes, or None if git failed."""
        proc = subprocess.run(
            ("git", "-C", self.root, "-c", "core.quotePath=false", *args),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        return proc.stdout if proc.returncode == 0 else None

    def text(self, *args):
        out = self.run(*args)
        return out.decode("utf-8", "replace").strip() if out is not None else None

    def has_ref(self, ref):
        return self.run("rev-parse", "--verify", "--quiet", ref + "^{commit}") is not None


def tool(name):
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if directory and os.access(os.path.join(directory, name), os.X_OK):
            return True
    return False


def stack_parent(git, branch):
    """The parent branch in a `gh stack`, if this branch is in one. `gh stack view
    --json` reports `base` as a SHA rather than a name, so take the entry below this."""
    if not tool("gh"):
        return None
    proc = subprocess.run(
        ("gh", "stack", "view", "--json"),
        cwd=git.root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None
    # Shape verified against gh-stack v0.1.0: a top-level object with "branches", each
    # entry carrying "name". Degrade rather than raise if a future version changes it.
    branches = (data.get("branches") if isinstance(data, dict) else None) or []
    names = [b.get("name") for b in branches if isinstance(b, dict)]
    if branch in names:
        index = names.index(branch)
        if index > 0:
            return names[index - 1]
    return None


def pr_base(git):
    """The base branch of this branch's open PR, if it has one."""
    if not tool("gh"):
        return None
    proc = subprocess.run(
        ("gh", "pr", "view", "--json", "baseRefName", "-q", ".baseRefName"),
        cwd=git.root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace").strip() or None


def default_base(git):
    """The repository's default branch. Local checks first, so the common path costs no
    network and works offline; `gh` is a last resort."""
    head = git.text("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if head and head.startswith("refs/remotes/"):
        return head[len("refs/remotes/") :]

    for name in ("main", "master", "trunk", "develop"):
        if git.has_ref("origin/" + name):
            return "origin/" + name

    if tool("gh"):
        proc = subprocess.run(
            ("gh", "repo", "view", "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name"),
            cwd=git.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if proc.returncode == 0:
            name = proc.stdout.decode("utf-8", "replace").strip()
            if name and git.has_ref("origin/" + name):
                return "origin/" + name

    for name in ("main", "master", "trunk"):  # remote-less repo
        if git.has_ref(name):
            return name
    return "origin/main"


def resolve_base(git, argv_base, branch):
    if argv_base:
        return argv_base
    env_base = os.environ.get(BASE_ENV)
    if env_base:
        return env_base
    for name in (stack_parent(git, branch), pr_base(git)):
        if name:
            # Prefer origin's copy — that is what the PR is measured against — but fall
            # back to the local branch when the remote ref is not fetched.
            if git.has_ref("origin/" + name):
                return "origin/" + name
            if git.has_ref(name):
                return name
    return default_base(git)


# An `Owns` field with no paths. The em dash is what the template prescribes; the ASCII
# en dash and hyphen are accepted because a plan gets hand-edited.
NONE_MARKERS = ("\u2014", "\u2013", "-", "")


class PlanError(Exception):
    """The globs cannot be established. Always exit 2, never 0 and never 1."""


# ---------------------------------------------------------------------------
# Glob semantics
#
# `fnmatch` is deliberately not used: its `*` matches `/`, so `src/*.py` would match
# src/a/b.py. That both over-matches (a clean branch fails) and, with `**` translated to
# the same thing, under-matches relative to what the template promises. The template's
# format is gitignore-shaped, and this implements that:
#
#   *   any run of characters within one path segment, never `/`
#   ?   exactly one character, never `/`
#   **  as a WHOLE segment, zero or more segments (one or more when it ends the pattern,
#       so `src/**` matches src/x but not the file src itself)
#
# `**` that is not a whole segment (`src/**.py`) is not special and degrades to a single
# `*`, which is what gitignore does with consecutive asterisks it considers invalid.
#
# Gitignore syntax this does NOT implement is rejected rather than read as a literal:
# character classes (`[abc]`) and leading-`!` negation. `Owns` globs are gitignore-shaped,
# so someone will eventually write `migrations/2026[01]*_billing_*.sql`; matching that
# literally would quietly own nothing, which is a false clean — the one failure this gate
# exists to prevent. Unsupported syntax exits 2 instead, naming the pattern.
#
# One addition on top: a pattern that matches a directory matches everything under it,
# again as in gitignore — `src/billing` fences the whole tree. That is the safe direction
# for an ownership gate. Over-matching costs a human a look at a diff; under-matching is a
# false clean, and the entire point of this script is that a false clean does not happen.
# ---------------------------------------------------------------------------


def segment_re(seg):
    """Regex source for one path segment's glob. Never matches `/`."""
    out = []
    i, n = 0, len(seg)
    while i < n:
        ch = seg[i]
        if ch == "*":
            while i < n and seg[i] == "*":  # `**` inside a segment is just `*`
                i += 1
            out.append("[^/]*")
            continue
        out.append("[^/]" if ch == "?" else re.escape(ch))
        i += 1
    return "".join(out)


def normalize(path):
    while path.startswith("./"):
        path = path[2:]
    return path.strip("/")


def unsupported_syntax(pattern):
    """What gitignore feature `pattern` uses that this does not implement, or None."""
    if "[" in pattern:
        return "a character class"
    if pattern.startswith("!"):
        return "leading-`!` negation"
    return None


def compile_glob(pattern):
    what = unsupported_syntax(pattern)
    if what:
        raise PlanError(
            f"glob `{pattern}` uses {what}, which this gate does not implement. Rewrite it with "
            "`*`, `**` and literal path segments."
        )
    parts = [p for p in normalize(pattern).split("/") if p]
    if not parts:
        raise PlanError("empty glob")
    out = []
    for i, seg in enumerate(parts):
        last = i == len(parts) - 1
        if seg == "**":
            out.append("(?:[^/]+/)*[^/]+" if last else "(?:[^/]+/)*")
            if not last:
                continue  # the `/` is already inside the group
        else:
            out.append(segment_re(seg))
        if not last:
            out.append("/")
    # The trailing group is the directory rule: whatever the pattern matches, everything
    # beneath it matches too.
    return re.compile("(?:" + "".join(out) + ")(?:/(?:[^/]+/)*[^/]+)?")


def compile_globs(patterns):
    return [(p, compile_glob(p)) for p in patterns]


def match_any(path, compiled):
    """The first glob that owns `path`, or None."""
    path = normalize(path)
    for pattern, regex in compiled:
        if regex.fullmatch(path):
            return pattern
    return None


def split_globs(text, strict=False):
    """Comma-separated globs, backticks stripped, `—` meaning none.

    `strict` is the plan's format: every entry must be backticked, so prose or a missing
    comma is reported rather than compiled into a glob that matches nothing.
    """
    globs = []
    for raw in text.replace("\n", ",").split(","):
        token = raw.strip()
        quoted = len(token) >= 2 and token.startswith("`") and token.endswith("`")
        if quoted:
            token = token[1:-1].strip()
        if token in NONE_MARKERS:
            continue
        if strict and (not quoted or "`" in token):
            raise PlanError(f"Owns entry is not a single backticked glob: {raw.strip()!r}")
        globs.append(token)
    return globs


# ---------------------------------------------------------------------------
# The plan, as a data source of last resort
# ---------------------------------------------------------------------------

# re.M so the same pattern serves both the line-by-line parse and find_plan's whole-file
# search for a document that has stack blocks at all.
STACK_RE = re.compile(r"^###\s+Stack\s+([A-Za-z0-9]+)\b", re.M)
OWNS_RE = re.compile(r"^-\s+\*\*Owns:?\*\*:?\s*(.*)$")
BULLET_RE = re.compile(r"^-\s+\*\*")


def parse_plan(text):
    """{stack id: [globs]} for every `### Stack <id> — <name>` block in a plan.

    The format is `template.md`'s, exactly: one `- **Owns:** ` bullet per stack, holding
    comma-separated backticked globs, wrapping onto continuation lines indented two
    spaces, ending at the next `- **` bullet or at a blank line.
    """
    stacks, lines, current, i = {}, text.split("\n"), None, 0
    while i < len(lines):
        line = lines[i]
        head = STACK_RE.match(line)
        if head:
            current = head.group(1)
            if current in stacks:
                raise PlanError(f"stack {current} appears twice")
            stacks[current] = None
            i += 1
            continue
        owns = OWNS_RE.match(line)
        if owns and current:
            if stacks[current] is not None:
                raise PlanError(f"stack {current} has more than one Owns field")
            value = owns.group(1).strip()
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if (
                    not nxt.strip()
                    or not nxt.startswith("  ")
                    or BULLET_RE.match(nxt)
                    or STACK_RE.match(nxt)
                ):
                    break
                value += " " + nxt.strip()
                i += 1
            stacks[current] = split_globs(value, strict=True)
            continue
        i += 1
    if not stacks:
        raise PlanError("no `### Stack <id>` headings found")
    blank = sorted(k for k, v in stacks.items() if v is None)
    if blank:
        # Silence is not "owns nothing" — the template spells that `—`. A stack whose
        # paths were never written down cannot fence anyone.
        raise PlanError("stack(s) {} have no Owns field".format(", ".join(blank)))
    return stacks


def other_globs(stacks, mine):
    """Every stack's globs except the caller's own — a stack is never fenced by itself."""
    if mine not in stacks:
        raise PlanError(
            "stack {} is not in the plan (it has {})".format(mine, ", ".join(sorted(stacks)))
        )
    globs = []
    for sid in sorted(stacks):
        if sid != mine:
            globs.extend(stacks[sid])
    return globs


def find_plan(git):
    """The one plan under the plan directory that defines stacks. Ambiguity exits 2."""
    plan_dir = PLAN_DIR.strip("/")
    out = git.run("ls-files", "-z", "--", plan_dir)
    if out is None:
        raise PlanError(f"cannot list {plan_dir}")
    found = []
    for path in out.decode("utf-8", "replace").split("\0"):
        if not path.endswith(".md"):
            continue
        text = read_file(os.path.join(git.root, path))
        if text is not None and STACK_RE.search(text):
            found.append(path)
    if len(found) != 1:
        listed = ": " + ", ".join(found) if found else ""
        raise PlanError(
            f"expected exactly one plan under {plan_dir} with `### Stack` headings, "
            f"found {len(found)}{listed}; pass --plan"
        )
    return found[0]


def read_file(path):
    try:
        with open(path, "rb") as handle:
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return None


def resolve_owns(git, cli_owns, stack_id, plan_path):
    """(globs, where they came from). --owns → $STACK_OWNS → the plan."""
    if cli_owns:
        globs = []
        for value in cli_owns:
            globs.extend(split_globs(value))
        return globs, "--owns"

    env = os.environ.get(OWNS_ENV)
    if env:
        return split_globs(env), "$" + OWNS_ENV

    mine = stack_id or os.environ.get(STACK_ENV)
    if not mine:
        raise PlanError(
            f"no --owns and no ${OWNS_ENV}, so the globs must come from the plan — but nothing "
            f"says which stack is yours. Pass --stack <id> or set ${STACK_ENV}."
        )
    path = plan_path or os.environ.get(PLAN_ENV) or find_plan(git)
    text = read_file(path if os.path.isabs(path) else os.path.join(git.root, path))
    if text is None:
        raise PlanError(f"cannot read the plan at {path}")
    stacks = parse_plan(text)
    others = sorted(k for k in stacks if k != mine)
    return other_globs(stacks, mine), "plan {}, stack{} {} (excluding {})".format(
        path, "" if len(others) == 1 else "s", ", ".join(others) or "none", mine
    )


# ---------------------------------------------------------------------------
# git plumbing and report
# ---------------------------------------------------------------------------


def changed_paths(git, merge_base):
    """Every path this branch touches, or None if git could not say.

    `--no-renames` on purpose: moving another stack's file out from under it is touching
    it, so both the old and the new path are reported and checked.
    """
    out = git.run("diff", "--name-only", "-z", "--no-renames", merge_base, "HEAD")
    if out is None:
        return None
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


EPILOG = """globs are gitignore-shaped and relative to the repo root: `**` crosses directories, a
single `*` does not, and a pattern naming a directory owns its whole tree.

exit codes: 0 clean, 1 an overlap was found, 2 could not measure.
"""

RECOVER = """stack-overlap: park the later stack, land the earlier one, replant the parked stack on
stack-overlap: the new default branch, then re-run this. If the two stacks genuinely share
stack-overlap: this surface they are not peers — it is a third stack that lands first."""


def parse_args(argv):
    """argparse rather than a hand-rolled loop: its own error path already exits 2, which
    is this gate's "could not measure", and `--help` is generated rather than maintained."""
    parser = argparse.ArgumentParser(
        prog="stack_overlap.py",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Fails when this branch changes a path another live stack owns.",
    )
    parser.add_argument(
        "base",
        nargs="?",
        help=(
            "what to measure from. Overrides $STACK_OVERLAP_BASE. When neither is given the "
            "base is inferred: gh stack parent, then the open PR's base branch, then the "
            "repository's default branch."
        ),
    )
    parser.add_argument(
        "--owns",
        action="append",
        default=[],
        metavar="GLOBS",
        help=(
            "comma-separated globs owned by the OTHER stack — the fence, not your own paths. "
            "Repeatable. Overrides $STACK_OWNS and the plan."
        ),
    )
    parser.add_argument(
        "--stack",
        metavar="ID",
        help=(
            "your stack's id, so the plan's globs for it are excluded. Required when the "
            "globs come from the plan. Also $STACK_ID."
        ),
    )
    parser.add_argument(
        "--plan",
        metavar="FILE",
        help=(
            "the plan to parse. Defaults to $STACK_PLAN, else the one file under the plan "
            "directory carrying `### Stack` headings."
        ),
    )
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)

    root = subprocess.run(
        ("git", "rev-parse", "--show-toplevel"),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if root.returncode != 0:
        sys.stderr.write("stack-overlap: not inside a git repository.\n")
        return 2
    git = Git(root.stdout.decode("utf-8", "replace").strip())

    branch = git.text("rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
    base = resolve_base(git, args.base, branch)
    merge_base = git.text("merge-base", base, "HEAD")
    if not merge_base:
        short = base[len("origin/") :] if base.startswith("origin/") else base
        sys.stderr.write(
            f"stack-overlap: cannot resolve a merge base against '{base}'.\n"
            f"stack-overlap: fetch it (git fetch origin '{short}') or pass a base ref.\n"
        )
        return 2

    try:
        globs, source = resolve_owns(git, args.owns, args.stack, args.plan)
        compiled = compile_globs(globs)  # here, so an unusable glob exits 2 like a
    except PlanError as exc:  # unusable plan does, with the same message
        sys.stderr.write(f"stack-overlap: {exc}\n")
        sys.stderr.write(
            "stack-overlap: cannot measure — pass --owns explicitly, or fix "
            "the plan's stack blocks.\n"
        )
        return 2
    if not globs:
        # Nothing to intersect against is not a clean bill of health. Either no second
        # stack is live, in which case this gate does not apply, or the plan's stack
        # blocks all own `—` and the independence work was never done.
        sys.stderr.write(
            f"stack-overlap: no globs from {source} — nothing to check against.\n"
            "stack-overlap: this gate applies only while a second stack is active.\n"
        )
        return 2

    paths = changed_paths(git, merge_base)
    if paths is None:
        sys.stderr.write(f"stack-overlap: git diff failed against {merge_base}.\n")
        return 2

    hits = []
    for path in paths:
        owner = match_any(path, compiled)
        if owner:
            hits.append((path, owner))

    print(f"stack-overlap: {branch} vs {base} ({merge_base[:9]})")
    print(f"stack-overlap: {len(globs)} glob(s) from {source}")
    print(f"stack-overlap: {len(paths)} changed paths, {len(hits)} owned elsewhere")
    sys.stdout.flush()  # so the report stays above the failure detail when piped

    if not paths and merge_base == git.text("rev-parse", "HEAD"):
        # Measured against HEAD, not the working tree — uncommitted work is invisible
        # here. Say so rather than letting an empty branch read as a clean one.
        sys.stderr.write(
            "stack-overlap: nothing is committed past the base; commit "
            "before trusting this verdict.\n"
        )

    if hits:
        sys.stderr.write(
            f"stack-overlap: FAIL — {len(hits)} changed path(s) belong to another stack.\n"
        )
        for path, owner in hits:
            sys.stderr.write(f"stack-overlap:   {path}  <-  {owner}\n")
        sys.stderr.write(RECOVER + "\n")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:
        # Python exits 1 on an unhandled exception, and 1 means "overlap found" here. Any
        # crash would otherwise be reported as a verdict. Map it to 2 instead: a gate that
        # cannot measure must not claim one.
        sys.stderr.write(f"stack-overlap: {type(exc).__name__}: {exc}\n")
        sys.exit(2)
