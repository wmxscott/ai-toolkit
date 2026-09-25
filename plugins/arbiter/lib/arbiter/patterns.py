"""Glob matching for path gating.

fnmatch is unusable here because it treats ``*`` as matching separators, so
``*.py`` would match ``src/a.py``. PurePath.full_match has the right semantics
but needs Python 3.13, and this ships against 3.11.
"""

import re
from functools import lru_cache


@lru_cache(maxsize=256)
def glob_to_regex(pattern: str) -> re.Pattern:
    """Translate a gitignore-style glob to an anchored regex.

    Supports ``**`` spanning separators, ``*`` and ``?`` within a single
    segment, and character classes.
    """
    out = ["^"]
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern[i : i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        if c == "[":
            j = pattern.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
                i += 1
                continue
            out.append(pattern[i : j + 1])
            i = j + 1
            continue
        out.append(re.escape(c))
        i += 1
    out.append("$")
    return re.compile("".join(out))


def matches(path: str, patterns: list[str]) -> bool:
    """True if ``path`` matches any pattern."""
    return any(glob_to_regex(p).search(path) for p in patterns)
