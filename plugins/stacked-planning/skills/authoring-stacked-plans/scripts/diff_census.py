#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pathspec", "pygments"]
# ///
"""Diff census — counts the lines a change adds and removes into configured buckets.

    ./diff_census.py --base main
    ./diff_census.py --print-config

Runs as a script through `uv`, which resolves the two dependencies from the inline
metadata above; `python3 diff_census.py` finds neither and fails.

Three-dot by default: what the branch introduced, not what the base did afterwards. Every
counted line lands in exactly one of `exempt` and `total`, and the groups and reported
matchers a configuration defines are subsets of `total`.

Gate mode is the default once the configuration defines a group: exit 0 for limits
satisfied or inside their grace band, 1 for one past its band, 2 for a census that could
not be taken.

Configuration comes from the `[diff_census]` table of the stacked-planning config file,
resolved first hit wins:

  1. `--config PATH`
  2. $STACKED_PLANNING_CONFIG
  3. `.agents/plugins/stacked-planning/config.toml`, relative to the git toplevel

An absent file is not an error: the built-in defaults apply. A file that exists and
cannot be used is one, and every configuration problem exits 2 — never 0, and never 1,
which is reserved for a bucket over its limit.

See DIFF_CENSUS.md for the configuration reference.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import mimetypes
import operator
import os
import posixpath
import re
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, field
from functools import cached_property

from pathspec import PathSpec
from pathspec.patterns.gitignore import GitIgnorePatternError
from pathspec.patterns.gitignore.basic import GitIgnoreBasicPattern

CONFIG_ENV = "STACKED_PLANNING_CONFIG"
CONFIG_RELPATH = ".agents/plugins/stacked-planning/config.toml"

# The file is shared with the plugin's other tools, one top-level table per tool. Every
# other top-level table belongs to something else and is skipped rather than rejected.
CONFIG_SECTION = "diff_census"

SCHEMA_VERSION = 1


class ConfigError(Exception):
    """A configuration exists but cannot be used. Always exit 2."""


# ---------------------------------------------------------------------------
# Vocabulary
#
# The facets a rule may carry and the closed value sets. Matching semantics belong to a
# later phase; what is here parses facet values, checks them, and retains them.
# ---------------------------------------------------------------------------

# Facet -> the kind of value it carries, which is what decides how it is checked. Every
# facet takes a list; a bare scalar stands for a one-element list.
FACET_KINDS = {
    "path": "glob",  # repo-relative, no leading slash
    "path_regex": "regex",  # full repo-relative path
    "dir": "glob",  # dirname only
    "name": "glob",  # basename only
    "name_regex": "regex",  # basename only
    "ext": "plain",  # exact, case-folded, no leading dot; "" for none
    "mime": "plain",  # exact, or `type/*`
    "size": "size",
    "mode": "mode",
    "content": "content",  # line text, leading +/- stripped
    "change": "change",
    "comment": "comment",
    "matches": "plain",  # matcher name(s)
}

# The split that decides what a rule can be answered from. File facets are known as soon
# as the diff names a file; line facets need the line itself. `matches` is in neither —
# what it resolves to is what decides.
LINE_FACETS = ("content", "change", "comment")
FILE_FACETS = tuple(f for f in FACET_KINDS if f not in (*LINE_FACETS, "matches"))

# Of the line facets, the two that genuinely need the line's text. Which side a count is
# on is a property of the count rather than of the text, so numstat answers `change`
# without the patch ever being read — which is why it is not in here.
PATCH_FACETS = ("content", "comment")

# `mime` is derived from the path and never sniffed, so it is only as good as the map it
# reads. Python's own is wrong about some source extensions — `.ts` is a video stream
# there, `.rs` an XML service description — and silent about others, so this table is
# consulted first and `mimetypes` supplies the rest.
MIME_EXTRA = {
    "go": "text/x-go",
    "rs": "text/x-rust",
    "swift": "text/x-swift",
    "ts": "text/x-typescript",
    "tsx": "text/x-typescript",
    "jsx": "text/javascript",
    "rb": "text/x-ruby",
    "kt": "text/x-kotlin",
    "lua": "text/x-lua",
    "toml": "application/toml",
    "yaml": "application/yaml",
    "yml": "application/yaml",
    "md": "text/markdown",
    "mdx": "text/markdown",
    "rst": "text/x-rst",
    "zsh": "application/x-sh",
    "bash": "application/x-sh",
    "fish": "application/x-sh",
    "sql": "application/sql",
    "proto": "text/x-protobuf",
}

# What a file whose type nothing can name reports, so `mime` is always a string.
MIME_UNKNOWN = "application/octet-stream"

# Git's file modes, as the octal strings a diff reports.
MODES = ("100644", "100755", "120000", "160000")

CHANGES = ("add", "del")

# The four-valued comment state: comment-only line, code with a trailing comment, no
# comment, and no lexer able to say.
COMMENTS = ("only", "trailing", "none", "unknown")

# What a limit counts. `changed` is `added + deleted`.
METRICS = ("added", "deleted", "changed")

# How a line belonging to several groups is charged. `multi` charges every group it
# matches; `first_match_wins` charges the first in declaration order, which is why group
# order is preserved through parsing.
OVERLAPS = ("multi", "first_match_wins")

# Names the census uses for its own buckets, so neither a group nor a matcher may take
# one.
RESERVED_NAMES = ("total", "exempt", "unmatched", "global", "limits")

# The buckets `[diff_census.limits]` can budget. Groups carry their own limits, and
# `exempt` is by definition not review surface, so these are the two census-wide numbers
# worth a budget: the denominator, and the share of it no rule claimed. A limit on
# `unmatched` turns config coverage into a gate — it fails when the configuration has
# stopped describing the repository, which is otherwise only visible to someone reading
# the report.
LIMITABLE = ("total", "unmatched")

# `size` comparisons: an operator, a number, and an optional unit.
SIZE_RE = re.compile(r"^(<=|>=|==|!=|<|>)\s*(\d+)\s*([A-Za-z]*)$")
SIZE_UNITS = {"": 1, "b": 1, "kib": 1024, "mib": 1024**2, "gib": 1024**3}
SIZE_OPS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}

# Files nobody reviews under any policy, excluded before anything else looks at them.
# Deliberately conservative: generated code, tests and docs are review surfaces whose
# treatment is a per-repo decision, so they belong to groups and still count toward
# `total`. Active unless `[diff_census.global]` sets `extend_builtin = false`.
BUILTIN_GLOBAL_EXCLUDE = (
    "**/*.lock",
    "**/package-lock.json",
    "**/yarn.lock",
    "**/pnpm-lock.yaml",
    "**/Cargo.lock",
    "**/poetry.lock",
    "**/go.sum",
    "**/composer.lock",
    "**/vendor/**",
    "**/node_modules/**",
    "**/.venv/**",
    "**/venv/**",
    "**/*.min.js",
    "**/*.min.css",
    "**/*.map",
    "**/__snapshots__/**",
    "**/*.snap",
    "**/.git/**",
)


# ---------------------------------------------------------------------------
# The parsed shape
# ---------------------------------------------------------------------------


@dataclass
class Rule:
    """One conjunction of facets. Facets AND within a rule, values OR within a facet.

    `facets` is what the file said; `tests` is what it compiles to, filled in at load and
    ordered cheapest first, so evaluating a rule is one `all()` over callables."""

    facets: dict[str, list[str]] = field(default_factory=dict)
    key: str = ""  # where it came from, for error messages
    tests: list[Test] = field(default_factory=list)


@dataclass
class Matcher:
    name: str
    report: bool = False
    rules: list[Rule] = field(default_factory=list)


@dataclass
class Limit:
    """One budget. Every metric named must pass; `changed` is added + deleted."""

    metrics: dict[str, int] = field(default_factory=dict)
    grace: float = 0.0

    def hard(self, metric: str) -> int:
        """The threshold past which the verdict is `over` rather than `warn`."""
        return int(self.metrics[metric] * (1.0 + self.grace))


@dataclass
class Group:
    name: str
    limit: Limit | None = None
    include: list[Rule] = field(default_factory=list)  # empty means match-all
    exclude: list[Rule] = field(default_factory=list)


@dataclass
class Config:
    source: str | None = None
    version: int | None = SCHEMA_VERSION
    overlap: str = "multi"
    docstrings_as_comments: bool = True
    extend_builtin: bool = True
    exclude: list[Rule] = field(default_factory=list)  # the file's own global rules
    matchers: dict[str, Matcher] = field(default_factory=dict)
    groups: dict[str, Group] = field(default_factory=dict)
    limits: dict[str, Limit] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def builtin_exclude(self) -> list[Rule]:
        """The shipped list, as one rule, or nothing when it is switched off."""
        return [BUILTIN_RULE] if self.extend_builtin else []

    @property
    def global_exclude(self) -> list[Rule]:
        """The global exclusion rules actually applied, in evaluation order."""
        return self.builtin_exclude + self.exclude


# ---------------------------------------------------------------------------
# Subjects
#
# What a rule is asked about. The engine never touches git: a subject carries the facts
# and whoever assembled it decided where they came from, which is what keeps the rule
# algebra testable against facts written by hand.
# ---------------------------------------------------------------------------


@dataclass
class File:
    """One changed file. `size` and `mode` come from its blob and are None where there is
    no blob to ask — a submodule, a file the diff only renamed. Everything else derives
    from the path, `mime` included: it is path-derived by design, never sniffed."""

    path: str  # repo-relative, no leading slash
    size: int | None = None
    mode: str | None = None  # one of MODES

    @cached_property
    def dir(self) -> str:
        """The dirname, empty for a file at the repository root."""
        return posixpath.dirname(self.path)

    @cached_property
    def name(self) -> str:
        return posixpath.basename(self.path)

    @cached_property
    def ext(self) -> str:
        """Case-folded, no leading dot, and empty for a file that has none."""
        return posixpath.splitext(self.name)[1].lstrip(".").casefold()

    @cached_property
    def mime(self) -> str:
        return MIME_EXTRA.get(self.ext) or mimetypes.guess_type(self.name)[0] or MIME_UNKNOWN


@dataclass
class Subject:
    """A file, and optionally one counted line of it. The file is shared across every
    line, so its derived facets are computed once and read many times.

    A line-level fact left None is unanswerable rather than false, and every facet
    needing it reports no match. That keeps the algebra two-valued — `exclude` beating
    `include` stays unambiguous — and errs in the safe direction for a budget: a rule
    that cannot be answered fails to fire, so an unanswerable `exclude` leaves the line
    inside its group and an unanswerable `include` leaves it outside."""

    file: File
    text: bytes | None = None  # the line, without its leading `+` or `-`
    change: str | None = None  # one of CHANGES
    comment: str | None = None  # one of COMMENTS


# ---------------------------------------------------------------------------
# Compiled facets
#
# One class per way of matching, built once when the configuration loads and called once
# per subject. `cost` orders the conjuncts within a rule, so a set lookup on `ext` gets
# the chance to rule a rule out before a regex over line text is ever run.
# ---------------------------------------------------------------------------


class Test:
    """A compiled facet: a predicate over a Subject."""

    cost = 5
    line = False  # whether the answer can turn on the line, not only on the file

    def __call__(self, subject: Subject) -> bool:
        raise NotImplementedError

    def state(self, subject: Subject) -> bool | None:
        """What this says about every line of a file at once, or None where only a line
        can say. A file-level facet answers for all of them; a line-level one abstains,
        which is what the pre-pass reads as `depends`."""
        return None if self.line else self(subject)


class Glob(Test):
    """gitwildmatch over one derived path. A file at the repository root has no dirname,
    and an empty path matches no pattern."""

    cost = 3

    def __init__(self, patterns, attr):
        self.spec, self.attr = PathSpec(patterns), attr

    def __call__(self, subject):
        value = getattr(subject.file, self.attr)
        return bool(value) and self.spec.match_file(value)


class Regex(Test):
    """Unanchored search over one derived path: `^` and `$` are available, not implied."""

    cost = 4

    def __init__(self, patterns, attr):
        self.patterns, self.attr = tuple(patterns), attr

    def __call__(self, subject):
        return any(p.search(getattr(subject.file, self.attr)) for p in self.patterns)


class Content(Test):
    """The same search over the bytes of a line, which a file-only subject lacks."""

    cost = 6
    line = True

    def __init__(self, patterns):
        self.patterns = tuple(patterns)

    def __call__(self, subject):
        return subject.text is not None and any(p.search(subject.text) for p in self.patterns)


class Ext(Test):
    cost = 0

    def __init__(self, values):
        # A configured extension is spelled without its dot, and one written with it
        # means the same thing rather than silently matching nothing.
        self.values = frozenset(v.lstrip(".").casefold() for v in values)

    def __call__(self, subject):
        return subject.file.ext in self.values


class Mime(Test):
    """Exact, or a `type/*` wildcard over the type half."""

    cost = 1

    def __init__(self, values):
        folded = [v.casefold() for v in values]
        self.exact = frozenset(v for v in folded if not v.endswith("/*"))
        self.prefixes = tuple(v[:-1] for v in folded if v.endswith("/*"))

    def __call__(self, subject):
        mime = subject.file.mime
        return mime in self.exact or mime.startswith(self.prefixes)


class Size(Test):
    """Any of the comparisons holding. A file of unknown size satisfies none of them."""

    cost = 0

    def __init__(self, comparisons):
        self.comparisons = tuple((SIZE_OPS[op], n) for op, n in comparisons)

    def __call__(self, subject):
        size = subject.file.size
        return size is not None and any(op(size, n) for op, n in self.comparisons)


class OneOf(Test):
    """A closed value set read off the subject. A fact the subject does not carry is None,
    which is not one of the values, so it does not match."""

    cost = 0

    def __init__(self, values, get, line=False):
        self.values, self.get, self.line = frozenset(values), get, line

    def __call__(self, subject):
        return self.get(subject) in self.values


class Reference(Test):
    """The `matches` facet, resolved to the matchers themselves. Cycles are rejected at
    load, so the recursion terminates."""

    cost = 7

    def __init__(self, matchers):
        self.matchers = tuple(matchers)

    @cached_property
    def rules(self) -> list[Rule]:
        """Every rule the reference reaches, as the one list they OR as.

        Flattened on first use rather than at construction: a rule naming a matcher may
        itself be compiled before that matcher's rules are."""
        return [rule for matcher in self.matchers for rule in matcher.rules]

    def __call__(self, subject):
        return matches_any(self.rules, subject)

    def state(self, subject):
        """Three-valued, so a reference is only as line-level as what it resolves to. A
        `matches` naming a purely path-based matcher settles a file outright."""
        return any_state(self.rules, subject)[0]


# Facet -> how its checked values become a predicate. `matches` is the only one that
# needs anything beyond its own values, and what it needs is the matcher table.
BUILDERS = {
    "path": lambda values, ms: Glob(values, "path"),
    "path_regex": lambda values, ms: Regex(values, "path"),
    "dir": lambda values, ms: Glob(values, "dir"),
    "name": lambda values, ms: Glob(values, "name"),
    "name_regex": lambda values, ms: Regex(values, "name"),
    "ext": lambda values, ms: Ext(values),
    "mime": lambda values, ms: Mime(values),
    "size": lambda values, ms: Size(values),
    "mode": lambda values, ms: OneOf(values, lambda s: s.file.mode),
    "content": lambda values, ms: Content(values),
    "change": lambda values, ms: OneOf(values, lambda s: s.change),
    "comment": lambda values, ms: OneOf(values, lambda s: s.comment, line=True),
    "matches": lambda values, ms: Reference([ms[name] for name in values]),
}

# The built-in exclusions as the single rule they evaluate as, compiled here because they
# are the script's own and cannot fail. Every Config that keeps them shares this object.
BUILTIN_RULE = Rule(facets={"path": list(BUILTIN_GLOBAL_EXCLUDE)}, key="builtin")
BUILTIN_RULE.tests = [Glob([GitIgnoreBasicPattern(p) for p in BUILTIN_GLOBAL_EXCLUDE], "path")]


# ---------------------------------------------------------------------------
# Evaluation
#
# Disjunctive normal form: facets AND within a rule, values OR within a facet, rules OR
# across a list. There is no `not` — `exclude` is what negation is for.
# ---------------------------------------------------------------------------


def matches(rule: Rule, subject: Subject) -> bool:
    """One rule. Its facets AND together, cheapest conjunct first."""
    return all(test(subject) for test in rule.tests)


def matches_any(rules, subject: Subject) -> bool:
    """A rule list. Its rules OR together, so an empty list matches nothing."""
    return any(matches(rule, subject) for rule in rules)


def first_match(rules, subject: Subject) -> int | None:
    """The index of the first rule that matches, or None where none does.

    Rules OR across a list, so any match settles the question and the first is as good as
    the rest — with the difference that it is the one a trace can name. Everything that
    has to explain itself asks this rather than `matches_any`."""
    for index, rule in enumerate(rules):
        if matches(rule, subject):
            return index
    return None


# ---------------------------------------------------------------------------
# The three-valued reading
#
# The same algebra asked a weaker question: not "does this line match" but "does this
# file settle it, either way, without a line". `True` and `False` are the two answers a
# file's own facets can give for all of its lines at once; `None` is `depends`, the case
# where the lines have to be walked after all.
#
# Sound by construction: an answer other than `None` is reached only through conjuncts
# that read nothing but the file, so it is the answer every line of that file would have
# given individually.
# ---------------------------------------------------------------------------


def rule_state(rule: Rule, subject: Subject) -> bool | None:
    """One rule, over a subject carrying a file and a side but no line.

    Conjuncts are ordered cheapest first, so an `ext` that already says no ends the rule
    before a `content` search is reached — which is the whole reason the pre-pass is
    cheaper than the walk it replaces."""
    settled = True
    for test in rule.tests:
        answer = test.state(subject)
        if answer is False:
            return False
        settled = settled and answer is not None
    return True if settled else None


def any_state(rules, subject: Subject) -> tuple[bool | None, int | None]:
    """A rule list ORed together, with the index `first_match` would have returned.

    A rule the lines decide ends the scan rather than being skipped over: a later rule
    that certainly matches would leave which of the two a trace should name unanswered,
    and being conservative here costs a walk rather than an answer."""
    for index, rule in enumerate(rules):
        answer = rule_state(rule, subject)
        if answer is None:
            return None, None
        if answer:
            return True, index
    return False, None


def membership(group: Group, subject: Subject) -> tuple[bool, int | None, int | None]:
    """Whether the line belongs to the group, with the `include` and `exclude` rules that
    decided it. An omitted `include` stands for match-all and names no rule."""
    included = first_match(group.include, subject) if group.include else None
    if group.include and included is None:
        return False, None, None
    excluded = first_match(group.exclude, subject)
    return excluded is None, included, excluded


def member(group: Group, subject: Subject) -> bool:
    """`matches_any(include) AND NOT matches_any(exclude)`. An omitted `include` stands
    for match-all, which makes an exclusion-only group the degenerate case of the same
    mechanism rather than a special form."""
    return membership(group, subject)[0]


# ---------------------------------------------------------------------------
# Parsing
#
# Every error names the key it came from, spelled as the reader finds it in the file —
# `diff_census.groups.production.limit`, not "limit".
# ---------------------------------------------------------------------------


class Parser:
    """Turns the `[diff_census]` table into a Config. Structural only: it checks that
    each key is known and each value carries the right TOML type, and leaves the
    semantic rules — closed value sets, cross-references, compilable patterns — to
    `validate`."""

    def __init__(self, source: str):
        self.source = source

    def fail(self, key, problem, hint=""):
        suffix = "\n  " + hint if hint else ""
        raise ConfigError(f"{self.source}: {key}: {problem}{suffix}")

    def typed(self, key, value, kind, want):
        ok = isinstance(value, kind)
        if kind is not bool and isinstance(value, bool):
            ok = False  # bool is an int in Python; `version = true` is not one
        if not ok:
            self.fail(key, f"must be {want}")
        return value

    def table(self, key, value):
        return self.typed(key, value, dict, "a table")

    def string(self, key, value):
        return self.typed(key, value, str, "a string")

    def boolean(self, key, value):
        return self.typed(key, value, bool, "true or false")

    def integer(self, key, value):
        return self.typed(key, value, int, "an integer")

    def strings(self, key, value):
        """A list of strings, or a bare string standing for a one-element list."""
        if isinstance(value, str):
            return [value]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            self.fail(key, "must be a string or a list of strings")
        return list(value)

    def known(self, key, table, allowed):
        for name in table:
            if name not in allowed:
                self.fail(
                    f"{key}.{name}", "unknown key; {} takes {}".format(key, ", ".join(allowed))
                )

    # -- rules ------------------------------------------------------------

    def rule(self, key, value) -> Rule:
        self.table(key, value)
        if not value:
            self.fail(key, "a rule needs at least one facet")
        rule = Rule(key=key)
        for facet, raw in value.items():
            fkey = f"{key}.{facet}"
            if facet not in FACET_KINDS:
                self.fail(
                    fkey, "unknown facet", "known facets: {}".format(", ".join(sorted(FACET_KINDS)))
                )
            values = self.strings(fkey, raw)
            if not values:
                self.fail(fkey, "a facet needs at least one value")
            rule.facets[facet] = values
        return rule

    def rules(self, key, value) -> list[Rule]:
        """A rule list: an array of rule tables, inline or as `[[...]]` sections."""
        if not isinstance(value, list):
            self.fail(key, "must be a list of rule tables")
        return [self.rule(f"{key}[{i}]", item) for i, item in enumerate(value)]

    def limit(self, key, value) -> Limit:
        self.table(key, value)
        self.known(key, value, (*METRICS, "grace"))
        limit = Limit()
        for metric in METRICS:
            if metric in value:
                limit.metrics[metric] = self.integer(f"{key}.{metric}", value[metric])
        if not limit.metrics:
            self.fail(key, "a limit needs at least one of {}".format(", ".join(METRICS)))
        if "grace" in value:
            raw = value["grace"]
            if not isinstance(raw, (int, float)) or isinstance(raw, bool):
                self.fail(key + ".grace", "must be a number")
            limit.grace = float(raw)
        return limit

    # -- sections ---------------------------------------------------------

    def globals(self, key, value, config):
        self.table(key, value)
        self.known(key, value, ("extend_builtin", "exclude"))
        if "extend_builtin" in value:
            config.extend_builtin = self.boolean(key + ".extend_builtin", value["extend_builtin"])
        if "exclude" in value:
            config.exclude = self.rules(key + ".exclude", value["exclude"])

    def matchers(self, key, value, config):
        self.table(key, value)
        for name, body in value.items():
            mkey = f"{key}.{name}"
            self.table(mkey, body)
            self.known(mkey, body, ("report", "rules"))
            matcher = Matcher(name=name)
            if "report" in body:
                matcher.report = self.boolean(mkey + ".report", body["report"])
            if "rules" not in body:
                self.fail(mkey, "a matcher needs `rules`")
            matcher.rules = self.rules(mkey + ".rules", body["rules"])
            if not matcher.rules:
                self.fail(mkey + ".rules", "a matcher needs at least one rule")
            config.matchers[name] = matcher

    def groups(self, key, value, config):
        self.table(key, value)
        for name, body in value.items():
            gkey = f"{key}.{name}"
            self.table(gkey, body)
            self.known(gkey, body, ("limit", "include", "exclude"))
            group = Group(name=name)
            if "limit" in body:
                group.limit = self.limit(gkey + ".limit", body["limit"])
            if "include" in body:
                group.include = self.rules(gkey + ".include", body["include"])
            if "exclude" in body:
                group.exclude = self.rules(gkey + ".exclude", body["exclude"])
            config.groups[name] = group

    def limits(self, key, value, config):
        self.table(key, value)
        self.known(key, value, LIMITABLE)
        for name, body in value.items():
            config.limits[name] = self.limit(f"{key}.{name}", body)

    def parse(self, table: dict) -> Config:
        config = Config(source=self.source, version=None)
        top = CONFIG_SECTION
        self.known(
            top,
            table,
            (
                "version",
                "overlap",
                "docstrings_as_comments",
                "global",
                "matchers",
                "groups",
                "limits",
            ),
        )
        if "version" in table:
            config.version = self.integer(top + ".version", table["version"])
        if "overlap" in table:
            config.overlap = self.string(top + ".overlap", table["overlap"])
        if "docstrings_as_comments" in table:
            config.docstrings_as_comments = self.boolean(
                top + ".docstrings_as_comments", table["docstrings_as_comments"]
            )
        if "global" in table:
            self.globals(top + ".global", table["global"], config)
        if "matchers" in table:
            self.matchers(top + ".matchers", table["matchers"], config)
        if "groups" in table:
            self.groups(top + ".groups", table["groups"], config)
        if "limits" in table:
            self.limits(top + ".limits", table["limits"], config)
        return config


# ---------------------------------------------------------------------------
# Validation
#
# The semantic rules, over an already well-formed shape. Patterns are compiled here so
# an unusable one is a load error rather than a surprise mid-census, and so the later
# phases inherit compiled objects rather than strings.
# ---------------------------------------------------------------------------


def check_glob(parser, key, value):
    """gitwildmatch, via pathspec. A pattern gitignore treats as a comment or a blank
    line compiles to nothing at all, which would silently match nothing — as much a
    configuration error as a syntactically invalid one, so both are rejected."""
    try:
        pattern = GitIgnoreBasicPattern(value)
    except (GitIgnorePatternError, re.error) as exc:
        parser.fail(key, f"invalid glob {value!r}: {exc}")
    if pattern.regex is None:
        parser.fail(
            key,
            f"invalid glob {value!r}: matches nothing",
            "a leading `#` or `!` is gitignore syntax, not a path",
        )
    return pattern


def check_regex(parser, key, value):
    try:
        return re.compile(value)
    except re.error as exc:
        parser.fail(key, f"invalid regex {value!r}: {exc}")


def check_content(parser, key, value):
    """`content` is applied to the raw bytes of a line rather than to decoded text, so it
    compiles to a bytes pattern — and `\\w`, `\\s` and `\\b` carry their ASCII meanings.
    The text form is compiled first, because it gives the clearer message for the errors
    both forms share."""
    check_regex(parser, key, value)
    try:
        return re.compile(value.encode("utf-8"))
    except re.error as exc:
        parser.fail(key, f"invalid regex {value!r} as bytes: {exc}")


def check_size(parser, key, value):
    """`<op><space?><number><unit?>`, e.g. `> 1MiB` or `<= 4096`."""
    match = SIZE_RE.match(value.strip())
    if not match:
        parser.fail(
            key,
            f"malformed size comparison {value!r}",
            "expected an operator, a number and an optional unit, as in `> 1MiB` or `<= 4096`",
        )
    op, number, unit = match.groups()
    if unit.lower() not in SIZE_UNITS:
        parser.fail(key, f"unknown size unit {unit!r} in {value!r}", "units: B, KiB, MiB, GiB")
    return op, int(number) * SIZE_UNITS[unit.lower()]


def check_member(parser, key, value, allowed, what):
    if value not in allowed:
        parser.fail(key, "{} {!r} is not one of {}".format(what, value, ", ".join(allowed)))
    return value


CHECKS = {
    "glob": check_glob,
    "regex": check_regex,
    "content": check_content,
    "size": check_size,
    "mode": lambda p, k, v: check_member(p, k, v, MODES, "file mode"),
    "change": lambda p, k, v: check_member(p, k, v, CHANGES, "change"),
    "comment": lambda p, k, v: check_member(p, k, v, COMMENTS, "comment state"),
    "plain": lambda p, k, v: v,
}


def iter_rules(config):
    """Every rule in the configuration, with the rules the file itself declares. The
    built-in exclusions are not walked: they are the script's own and always valid."""
    yield from config.exclude
    for matcher in config.matchers.values():
        yield from matcher.rules
    for group in config.groups.values():
        yield from group.include
        yield from group.exclude


def compile_rules(parser, config):
    """Check every facet value and build the predicate each facet compiles to. This is
    the only place a pattern is ever compiled: what evaluation sees is objects, so a
    census pays nothing per line for syntax the configuration settled at load."""
    for rule in iter_rules(config):
        tests = []
        for facet, values in rule.facets.items():
            check = CHECKS[FACET_KINDS[facet]]
            checked = [
                check(parser, f"{rule.key}.{facet}[{i}]", value) for i, value in enumerate(values)
            ]
            tests.append(BUILDERS[facet](checked, config.matchers))
        rule.tests = sorted(tests, key=lambda test: test.cost)


def check_references(parser, config):
    """Every `matches` names a defined matcher, and no matcher reaches itself."""
    for rule in iter_rules(config):
        for name in rule.facets.get("matches", ()):
            if name not in config.matchers:
                parser.fail(
                    rule.key + ".matches",
                    f"undefined matcher {name!r}",
                    "defined matchers: {}".format(", ".join(config.matchers) or "none"),
                )

    edges = {
        name: [ref for rule in matcher.rules for ref in rule.facets.get("matches", ())]
        for name, matcher in config.matchers.items()
    }
    # Depth-first, carrying the path so a cycle can be named rather than merely
    # reported. `done` keeps it linear over configs where matchers share references.
    done, path, seen = set(), [], set()

    def walk(name):
        if name in done:
            return
        if name in seen:
            cycle = [*path[path.index(name) :], name]
            parser.fail(
                f"{CONFIG_SECTION}.matchers.{name}", "reference cycle: " + " -> ".join(cycle)
            )
        seen.add(name)
        path.append(name)
        for ref in edges[name]:
            walk(ref)
        path.pop()
        seen.discard(name)
        done.add(name)

    for name in edges:
        walk(name)


def check_names(parser, config):
    for kind, names in (("groups", config.groups), ("matchers", config.matchers)):
        for name in names:
            if name in RESERVED_NAMES:
                parser.fail(
                    f"{CONFIG_SECTION}.{kind}.{name}",
                    f"{name!r} is a reserved bucket name",
                    "reserved: {}".format(", ".join(RESERVED_NAMES)),
                )
    for name in config.groups:
        if name in config.matchers:
            parser.fail(
                f"{CONFIG_SECTION}.groups.{name}",
                f"{name!r} names both a group and a matcher",
                "one name, one object — rename one of them",
            )


def check_limits(parser, config):
    for group in config.groups.values():
        key = f"{CONFIG_SECTION}.groups.{group.name}"
        if group.limit is None:
            parser.fail(
                key,
                "a group needs `limit`",
                "a bucket that needs no budget is a matcher with `report = true`, not a group",
            )
    for owner, limit in [(g.name, g.limit) for g in config.groups.values()] + list(
        config.limits.items()
    ):
        if not 0.0 <= limit.grace < 1.0:
            where = (
                f"{CONFIG_SECTION}.limits.{owner}"
                if owner in config.limits
                else f"{CONFIG_SECTION}.groups.{owner}.limit"
            )
            parser.fail(where + ".grace", f"grace {limit.grace} is outside [0, 1)")


def subsumes(wide: Rule, narrow: Rule) -> bool:
    """True when `narrow` matching guarantees `wide` matches: every facet `wide`
    constrains, `narrow` constrains too, with a value list `wide`'s covers.

    Deliberately narrow. Values are compared as written, so nothing here reasons about
    whether two different globs overlap — which keeps the answer sound, and keeps it from
    firing on a configuration that is merely hard to read."""
    for facet, values in wide.facets.items():
        theirs = narrow.facets.get(facet)
        if theirs is None or not set(theirs) <= set(values):
            return False
    return True


def check_reachable(config: Config):
    """Warn — never fail — when a group's `exclude` covers every one of its `include`
    rules, so no line can be a member of it.

    File-level facets only, per the specification: a rule carrying `content`, `comment`,
    `change` or `matches` may be false for reasons this cannot see, so it is not treated
    as something that blocks. A group with no `include` matches everything, and the
    grammar has no unconditional rule to exclude it with, so there is nothing to say."""
    for group in config.groups.values():
        blockers = [
            rule for rule in group.exclude if all(facet in FILE_FACETS for facet in rule.facets)
        ]
        if not group.include or not blockers:
            continue
        if all(any(subsumes(block, rule) for block in blockers) for rule in group.include):
            config.warnings.append(
                f"{CONFIG_SECTION}.groups.{group.name}: no line can match — "
                "every `include` rule is covered by an `exclude` rule"
            )


def validate(parser: Parser, config: Config):
    if config.version is None:
        parser.fail(CONFIG_SECTION + ".version", "required", f"set `version = {SCHEMA_VERSION}`")
    if config.version != SCHEMA_VERSION:
        parser.fail(
            CONFIG_SECTION + ".version",
            f"unsupported version {config.version}; this script speaks {SCHEMA_VERSION}",
        )
    check_member(parser, CONFIG_SECTION + ".overlap", config.overlap, OVERLAPS, "overlap policy")
    check_names(parser, config)
    check_limits(parser, config)
    # References before patterns: `matches` compiles to the matchers themselves, so every
    # name has to be known good before anything resolves one.
    check_references(parser, config)
    compile_rules(parser, config)
    check_reachable(config)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def git_toplevel(start: str | None = None) -> str | None:
    proc = subprocess.run(
        ("git", "rev-parse", "--show-toplevel"),
        cwd=start,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace").strip()


def config_path(explicit: str | None) -> tuple[str | None, bool]:
    """The file to read, and whether the caller named it. A named file that is missing
    is an error; the discovered one simply may not exist."""
    if explicit:
        return explicit, True
    override = os.environ.get(CONFIG_ENV)
    if override:
        return override, True
    top = git_toplevel()
    if top is None:
        return None, False
    return os.path.join(top, *CONFIG_RELPATH.split("/")), False


def load_config(explicit: str | None = None) -> Config:
    """The configuration in force. An absent file yields the built-in defaults; a file
    that exists and cannot be used raises."""
    path, named = config_path(explicit)
    if path is None or not os.path.isfile(path):
        if named:
            raise ConfigError(f"{path}: not a file")
        return Config()
    try:
        with open(path, "rb") as handle:
            table = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    section = table.get(CONFIG_SECTION)
    if section is None:
        return Config(source=path)
    parser = Parser(path)
    parser.table(CONFIG_SECTION, section)
    config = parser.parse(section)
    validate(parser, config)
    return config


# ---------------------------------------------------------------------------
# Git
#
# Every invocation is rooted at the repository toplevel, so where the caller happened to
# stand changes nothing about what is measured, and every path the diff reports is
# repo-relative without further work.
# ---------------------------------------------------------------------------


class GitError(Exception):
    """Git could not answer. Like a configuration problem, always exit 2: the census was
    not measured, which is a different outcome from measuring it and finding it large."""


class Git:
    def __init__(self, root: str):
        self.root = root

    @classmethod
    def open(cls, start: str | None = None) -> Git:
        top = git_toplevel(start)
        if top is None:
            raise GitError("not inside a git repository")
        return cls(top)

    def run(self, *args: str) -> bytes:
        """Raw stdout. A non-zero exit carries git's own message, which says more about
        an unknown ref or a broken repository than anything this could add."""
        proc = subprocess.run(("git", *args), cwd=self.root, capture_output=True)
        if proc.returncode != 0:
            raise GitError(
                "git {}: {}".format(
                    " ".join(args),
                    proc.stderr.decode("utf-8", "replace").strip() or f"exited {proc.returncode}",
                )
            )
        return proc.stdout

    def stream(self, *args: str):
        """The same output a line at a time, without its newline.

        A patch is the one thing git is asked for that has no bound: `run` would hold a
        50k-line diff in memory only to split it, where this keeps memory flat whatever
        the diff's size. The exit status is checked once the output is exhausted, so a git
        that failed partway through still raises rather than reading as a short diff."""
        proc = subprocess.Popen(
            ("git", *args), cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        with proc.stdout:
            for raw in proc.stdout:
                yield raw[:-1] if raw.endswith(b"\n") else raw
        problem = proc.stderr.read().decode("utf-8", "replace").strip()
        proc.stderr.close()
        if proc.wait() != 0:
            raise GitError(
                "git {}: {}".format(" ".join(args), problem or f"exited {proc.returncode}")
            )

    def text(self, *args: str) -> str | None:
        """The one-line answer, or None where git declined to give one. For the questions
        whose answer is allowed to be "there isn't one"."""
        try:
            return self.run(*args).decode("utf-8", "replace").strip() or None
        except GitError:
            return None


class Blobs:
    """Object sizes and object contents, from long-lived `git cat-file` processes — one
    for `--batch-check`, one for `--batch`, each started on the first question put to it.

    A subprocess per file dominates every other cost past a few hundred of them, so a
    process starts once and answers every question after it."""

    CHUNK = 1 << 20  # what an oversize body is drained in

    def __init__(self, git: Git):
        self.git, self.procs = git, {}

    def ask(self, mode: str, oid: str) -> tuple[subprocess.Popen, list[str]]:
        """One object name in, one header line back: `<oid> <type> <size>`, or
        `<name> missing` for an object that is not there."""
        proc = self.procs.get(mode)
        if proc is None:
            proc = self.procs[mode] = subprocess.Popen(
                ("git", "cat-file", mode),
                cwd=self.git.root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        proc.stdin.write(oid.encode("ascii") + b"\n")
        proc.stdin.flush()
        return proc, proc.stdout.readline().decode("ascii", "replace").split()

    def size(self, oid: str) -> int | None:
        """The blob's size in bytes, or None for anything git cannot produce as one."""
        _, fields = self.ask("--batch-check", oid)
        if len(fields) != 3 or fields[1] != "blob":
            return None
        return int(fields[2])

    def data(self, oid: str, cap: int | None = None) -> bytes | None:
        """The blob's bytes, or None where there is no blob or it is over `cap`.

        The body is consumed either way. The process is shared, so a body left unread
        would be read back as the answer to the next question."""
        proc, fields = self.ask("--batch", oid)
        if len(fields) != 3 or fields[1] != "blob":
            return None
        size = int(fields[2])
        if cap is not None and size > cap:
            remaining = size + 1  # the newline git writes after the body
            while remaining > 0:
                remaining -= len(proc.stdout.read(min(remaining, self.CHUNK)))
            return None
        return proc.stdout.read(size + 1)[:size]

    def close(self):
        for proc in self.procs.values():
            proc.stdin.close()
            proc.stdout.close()
            proc.wait()
        self.procs.clear()


# ---------------------------------------------------------------------------
# Refs
# ---------------------------------------------------------------------------

THREE_DOT, TWO_DOT, STAGED, WORKING_TREE = ("three-dot", "two-dot", "staged", "working-tree")

# Where to look for the branch everything is measured against, after origin's own answer.
DEFAULT_BASES = ("main", "master")


@dataclass
class Refs:
    """What is being compared. `merge_base` is the commit three-dot actually diffs from,
    resolved up front so the report can name it and an unresolvable one fails before any
    counting starts."""

    mode: str = THREE_DOT
    base: str | None = None
    head: str = "HEAD"
    merge_base: str | None = None

    @property
    def options(self) -> tuple[str, ...]:
        return {THREE_DOT: ("--merge-base",), STAGED: ("--cached",)}.get(self.mode, ())

    @property
    def revs(self) -> tuple[str, ...]:
        if self.mode in (STAGED, WORKING_TREE):
            return (self.head,)
        return (self.base, self.head)

    def describe(self) -> str:
        if self.mode == STAGED:
            return f"the index against {self.head}"
        if self.mode == WORKING_TREE:
            return f"the working tree against {self.head}"
        joiner = "..." if self.mode == THREE_DOT else ".."
        return f"{self.base}{joiner}{joiner}"


def default_base(git: Git) -> str:
    """The branch a change is measured against when the caller names none: whatever
    origin calls its default, and failing that the conventional local names."""
    head = git.text("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if head and head.startswith("refs/remotes/"):
        return head[len("refs/remotes/") :]
    for name in DEFAULT_BASES:
        if git.text("rev-parse", "--verify", "--quiet", name + "^{commit}"):
            return name
    return DEFAULT_BASES[0]


def resolve_refs(
    git: Git, mode: str = THREE_DOT, base: str | None = None, head: str = "HEAD"
) -> Refs:
    """The comparison to make, with everything about it settled.

    Three-dot is the default because it measures only what the branch introduced. Two-dot
    would fold in every commit that landed on the base after the branch was cut, so a gate
    would fire for reasons that have nothing to do with the change under review."""
    if mode in (STAGED, WORKING_TREE):
        return Refs(mode=mode, head=head)
    refs = Refs(mode=mode, base=base or default_base(git), head=head)
    if mode == THREE_DOT:
        refs.merge_base = git.text("merge-base", refs.base, refs.head)
        if refs.merge_base is None:
            raise GitError(f"cannot resolve a merge base between {refs.base!r} and {refs.head!r}")
    return refs


# ---------------------------------------------------------------------------
# Diff acquisition
#
# Two paths over the same diff. `--numstat` with `--raw` answers per-file counts, modes
# and blob names in one pass over a few hundred rows; the `-U0` patch answers the same
# counts by walking the lines, and is what a rule reading line text needs. They agree by
# construction — the same records decide which files exist and which of them count zero —
# and the tests hold them to it.
# ---------------------------------------------------------------------------

# Modes a diff reports for something that is not a blob, or for the absent side of an add
# or a delete.
MODE_SUBMODULE = "160000"
MODE_ABSENT = "000000"

# Statuses carrying two paths: the old one, then the new one.
MOVED = ("R", "C")

NUMSTAT, PATCH = "numstat", "patch"

# `@@ -<old start>[,<len>] +<new start>[,<len>] @@`, and whatever git appends for context.
HUNK_RE = re.compile(rb"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass
class Line:
    """One counted line. `text` is bytes because that is what git wrote: a diff carries
    whatever encoding each file uses, and decoding it would be a guess this does not have
    to make.

    `number` is what makes comment detection possible: the state of a line is read off the
    whole image it belongs to, and this is the key into it. `comment` stays None until
    something asks for it, which nothing does unless a rule uses the facet."""

    change: str  # one of CHANGES
    text: bytes  # without the leading `+` or `-`
    number: int  # in the image the line belongs to
    comment: str | None = None  # one of COMMENTS


@dataclass
class FileDiff:
    """One changed file. A rename classifies under its new path — that is where the code
    now lives and where a reviewer will look for it — with `old_path` keeping where it
    came from."""

    file: File
    status: str = "M"  # A C D M R T, a rename's score dropped
    old_path: str | None = None
    adds: int = 0
    dels: int = 0
    binary: bool = False
    submodule: bool = False
    pre_oid: str | None = None  # the blob a `-` line is read from
    post_oid: str | None = None  # the blob a `+` line is read from
    lines: list[Line] | None = None  # None where the counts came from numstat

    @property
    def path(self) -> str:
        return self.file.path

    @property
    def oid(self) -> str | None:
        """The blob the file's facets describe: the post-image, which is the file as the
        change leaves it, except for a deletion where the pre-image is the only one."""
        return self.pre_oid if self.status == "D" else self.post_oid

    @property
    def changed(self) -> int:
        return self.adds + self.dels


@dataclass
class Diff:
    """Everything one comparison found, before anything classifies it."""

    refs: Refs
    files: list[FileDiff] = field(default_factory=list)
    via: str = NUMSTAT  # which acquisition path produced the counts
    diagnostics: Diagnostics | None = None  # None until something classifies lines
    prepass: Prepass | None = None  # which files settled without their lines

    @property
    def adds(self) -> int:
        return sum(f.adds for f in self.files)

    @property
    def dels(self) -> int:
        return sum(f.dels for f in self.files)

    @property
    def changed(self) -> int:
        return self.adds + self.dels

    @property
    def binary_files(self) -> int:
        return sum(1 for f in self.files if f.binary)

    @property
    def submodule_changes(self) -> int:
        return sum(1 for f in self.files if f.submodule)


def diff_command(refs: Refs, renames: bool, *extra: str) -> tuple[str, ...]:
    """`git diff` with the invariants this script always wants.

    `--no-ext-diff` and `--no-textconv` are not optional: a repository configuring either
    in `.gitattributes` would otherwise spawn an external program per file — a cost this
    does not control, producing output it cannot parse."""
    return (
        "diff",
        *refs.options,
        "--no-ext-diff",
        "--no-textconv",
        "--no-color",
        "-M" if renames else "--no-renames",
        *extra,
        *refs.revs,
    )


def records(data: bytes):
    """The records of a NUL-separated raw-and-numstat stream, in the order git wrote them.

    Raw records come first, each `:<src mode> <dst mode> <src oid> <dst oid> <status>`
    followed by one path, or by two when the status is a rename or a copy. Numstat records
    follow, each `<adds>\\t<dels>\\t<path>` — with the path field left empty and the two
    paths following as their own fields when the change moved the file.

    Paths are decoded with `surrogateescape` rather than being rejected: a path that is
    not UTF-8 is a path this still has to report."""
    fields = [f.decode("utf-8", "surrogateescape") for f in data.split(b"\0")]
    if fields and not fields[-1]:
        fields.pop()
    index = 0
    while index < len(fields):
        head, index = fields[index], index + 1
        if head.startswith(":"):
            meta = head[1:].split()
            paths, index = fields[index : index + 2], index + 2
            if meta[4][0] not in MOVED:
                paths, index = paths[:1], index - 1
            yield ("raw", meta, paths)
        else:
            counts = head.split("\t", 2)
            if counts[2]:
                paths = [counts[2]]
            else:
                paths, index = fields[index : index + 2], index + 2
            yield ("numstat", counts[:2], paths)


def file_diff(meta: list[str], paths: list[str]) -> FileDiff:
    """A raw record as the changed file it describes.

    `size` and `mode` come from the post-image, which is the file as the change leaves it
    — except for a deletion, where the pre-image is the only image there is."""
    src_mode, dst_mode, src_oid, dst_oid, status = meta
    mode = src_mode if status[0] == "D" else dst_mode

    def named(oid):
        return None if set(oid) == {"0"} else oid

    return FileDiff(
        file=File(paths[-1], mode=None if mode == MODE_ABSENT else mode),
        status=status[0],
        old_path=paths[0] if len(paths) > 1 else None,
        submodule=MODE_SUBMODULE in (src_mode, dst_mode),
        pre_oid=named(src_oid),
        post_oid=named(dst_oid),
    )


def attach_sizes(git: Git, refs: Refs, files: list[FileDiff]):
    """Blob sizes for every file that has a blob, over one batch-check process.

    A working-tree comparison has no object for its post-image — the file is not written
    to the store until it is added — so there the file on disk is the post-image, and it
    is measured directly."""
    blobs = Blobs(git)
    try:
        for changed in files:
            if changed.submodule:
                continue  # a gitlink names a commit, not a blob
            if changed.oid is not None:
                changed.file.size = blobs.size(changed.oid)
            elif refs.mode == WORKING_TREE and changed.status != "D":
                with contextlib.suppress(OSError):
                    changed.file.size = os.path.getsize(os.path.join(git.root, changed.path))
    finally:
        blobs.close()


def settle(changed: FileDiff):
    """Zero what has no reviewable line in it, whichever path counted it.

    Both paths need this and for the same reason. Numstat reports a gitlink bump as one
    line each way; the patch writes it as a `-Subproject commit`/`+Subproject commit`
    pair. Neither is a line anybody wrote, so a submodule counts nothing and is recorded
    instead. A binary is the same story from the other direction — git offers no line
    counts at all, and the patch says only that the two differ."""
    if changed.binary or changed.submodule:
        changed.adds = changed.dels = 0
        if changed.lines is not None:
            changed.lines = []


def count_patch(git: Git, refs: Refs, renames: bool, files: list[FileDiff]):
    """Count by walking the `-U0` patch as git writes it, keeping every line it counted.

    Patch blocks arrive in the order the raw records did — one block per changed file,
    including the mode-only and pure-rename changes whose block has no body — so the file
    a line belongs to is its position, never a path parsed back out of a header that may
    be quoted.

    A counted line is a `+` or `-` inside a hunk. That excludes the `---` and `+++` file
    headers, which precede the first hunk, and it means a deleted line whose own text
    looks like patch framing is still just a line."""
    for changed in files:
        changed.lines = []
    index, current, old_no, new_no = -1, None, 0, 0
    for raw in git.stream(*diff_command(refs, renames, "-U0")):
        if raw.startswith(b"diff --git "):
            index += 1
            current = files[index] if index < len(files) else None
            old_no = new_no = 0
        elif current is None:
            continue
        elif raw.startswith(b"@@"):
            hunk = HUNK_RE.match(raw)
            if hunk:
                old_no, new_no = int(hunk.group(1)), int(hunk.group(2))
        elif not new_no and not old_no:
            # Still in the block's header, where `Binary files ... differ` stands in for
            # a body git will not write and `+++`/`---` name the two images.
            current.binary = current.binary or raw.startswith(
                (b"Binary files ", b"GIT binary patch")
            )
        elif raw.startswith(b"+"):
            current.lines.append(Line("add", raw[1:], new_no))
            current.adds, new_no = current.adds + 1, new_no + 1
        elif raw.startswith(b"-"):
            current.lines.append(Line("del", raw[1:], old_no))
            current.dels, old_no = current.dels + 1, old_no + 1
        # Anything else in a hunk is the `\ No newline at end of file` marker, which
        # reports on the line before it rather than being one.


def acquire(git: Git, refs: Refs, renames: bool = True, patch: bool = False) -> Diff:
    """Read the diff and count it, per file.

    A binary file has no lines for git to count, a gitlink names a commit rather than
    content, and a change to neither — a mode flipped, a file moved untouched — has no
    line to count either. All three land at zero and are recorded, so nothing is silently
    invisible."""
    diff = Diff(refs=refs, via=PATCH if patch else NUMSTAT)
    numstat = () if patch else ("--numstat",)
    counted = 0
    # Raw records come first and numstat records follow in the same order, so a numstat
    # record belongs to the file that many raw records in.
    for kind, values, paths in records(
        git.run(*diff_command(refs, renames, "--raw", "-z", "--no-abbrev", *numstat))
    ):
        if kind == "raw":
            diff.files.append(file_diff(values, paths))
        else:
            adds, dels = values
            diff.files[counted].binary = adds == "-"
            if not diff.files[counted].binary:
                diff.files[counted].adds, diff.files[counted].dels = (int(adds), int(dels))
            counted += 1
    if patch:
        count_patch(git, refs, renames, diff.files)
    for changed in diff.files:
        settle(changed)
    attach_sizes(git, refs, diff.files)
    return diff


# ---------------------------------------------------------------------------
# Comment detection
#
# Comment state is a property of the file, not of the line. A `+` line inside an open
# block comment cannot be told from the hunk it arrived in, and `-U0` supplies no context
# at all, so the whole image is fetched, lexed once, and reduced to one letter per line —
# which the counted lines then index by the line numbers the hunk headers gave them.
#
# A regex cannot do this. `^\s*#` fires on shebangs, on `#include`, on markdown headings
# and on `color = "#000000"`, and misses every continuation line of a block comment and
# every language whose comment token is not `#`. A gate that silently undercounts is worse
# than one that declines to classify.
# ---------------------------------------------------------------------------

# The four states, as the letters a cache entry stores them in — one per line, so a lexed
# file costs about as many bytes as it has lines.
CODES = {"o": "only", "t": "trailing", "n": "none", "u": "unknown"}

# Blobs above this are classified `unknown` rather than lexed. Pygments is the only
# genuinely expensive component here, and a megabyte of anything is not a file whose
# comment density a reviewer is weighing.
LEX_CAP = 1 << 20

# Where the cache lives, under the common git directory. The format is part of the cache
# key rather than of the file, so a change to how a line is spelled invalidates every
# entry the same way a pygments upgrade does.
CACHE_DIR = "diff_census"
CACHE_FORMAT = 1


class Pygments:
    """The optional dependency, and the token-type questions asked of it.

    Imported in `__init__` rather than at module scope so that absence is a value this
    can carry rather than a failure to start — and so a test can simulate absence without
    uninstalling anything."""

    def __init__(self):
        import pygments
        from pygments.lexers import get_lexer_for_filename
        from pygments.token import Comment, String
        from pygments.util import ClassNotFound

        self.version = pygments.__version__
        self.lexer_for, self.missing = get_lexer_for_filename, ClassNotFound
        self.comment, self.docstring = Comment, String.Doc
        # Pygments files two functional things under `Token.Comment` that no reviewer
        # would call commentary: the C preprocessor, where `#include <stdio.h>` is
        # `Comment.Preproc`, and the shebang, where the interpreter a file runs under is
        # `Comment.Hashbang`. Both are code, and both count.
        self.not_comment = (Comment.Preproc, Comment.PreprocFile, Comment.Hashbang)

    def lexer(self, filename: str):
        """A lexer for this filename, or None where pygments knows of none.

        `stripnl` is off because it is not optional here: left on, a leading blank line is
        dropped from the token stream and every line number after it is wrong by one."""
        try:
            return self.lexer_for(filename, stripnl=False)
        except self.missing:
            return None

    def commentish(self, token, docstrings: bool) -> bool:
        if token in self.docstring:
            return docstrings
        return token in self.comment and not any(token in kind for kind in self.not_comment)


def classify(text: str, lexer, pygments: Pygments, docstrings: bool) -> str:
    """One letter per line of `text`, in order, from its token stream.

    A line is `only` when every non-whitespace token on it is a comment token, `trailing`
    when it carries both, and `none` otherwise. A token spanning newlines is split across
    the lines it covers; an *interior* empty piece still counts as covered, which is what
    makes a blank line in the middle of a block comment part of the comment rather than a
    line of nothing."""
    total = text.count("\n") + 1
    commented, coded = [False] * total, [False] * total
    number = 0
    for token, value in lexer.get_tokens(text):
        comment = pygments.commentish(token, docstrings)
        pieces = value.split("\n")
        for index, piece in enumerate(pieces):
            interior = index < len(pieces) - 1
            if number < total:
                if comment:
                    if piece.strip() or interior:
                        commented[number] = True
                elif piece.strip():
                    coded[number] = True
            number += interior
    return "".join(
        "t" if c and k else "o" if c else "n" for c, k in zip(commented, coded, strict=False)
    )


@dataclass
class Diagnostics:
    """What the census could not do, and what it cost. Counted so that a missing language
    profile is noticed deliberately rather than through a change that sailed past a gate
    because nothing could read it."""

    unknown_lexer_files: int = 0
    oversize_skipped_files: int = 0
    files_read: int = 0
    blobs_lexed: int = 0
    cache_hits: int = 0
    warnings: list[str] = field(default_factory=list)


class Comments:
    """Comment state for the lines of a diff, one blob at a time.

    Whole blobs are lexed and the result is cached under the blob's own name, which is
    what makes a re-run cheap: a branch being iterated on relexes only what it touched,
    and a rerun on an unchanged head lexes nothing at all."""

    def __init__(self, git: Git, docstrings: bool = True, cache: bool = True, cap: int = LEX_CAP):
        self.git, self.docstrings, self.cap = git, docstrings, cap
        self.diagnostics = Diagnostics()
        self.lexers = {}  # extension or basename -> lexer, or None
        self.states = {}  # cache key -> letters, within this run
        self.seen = set()  # paths already counted in the diagnostics
        self.dir = cache_dir(git) if cache else None
        try:
            self.pygments = Pygments()
        except ImportError as exc:
            self.pygments = None
            self.diagnostics.warnings.append(
                f"pygments is not installed, so every line is `unknown` and counts as code: {exc}"
            )

    @staticmethod
    def hint(file: File) -> str:
        """The name a lexer is chosen by. A file with an extension is known by it and
        nothing else; one without — a `Makefile`, a `.gitignore` — has only its whole
        name to go on."""
        return "_." + file.ext if file.ext else file.name

    def lexer(self, file: File):
        """The lexer for a file, cached by extension.

        `get_lexer_for_filename` guesses at the filesystem on every call, so the answer is
        kept. Extension is the key the specification names; a file that has none is keyed
        by its whole name, which is the same thing the hint is."""
        key = file.ext or file.name
        if key not in self.lexers:
            self.lexers[key] = self.pygments.lexer(self.hint(file))
        return self.lexers[key]

    # -- the cache --------------------------------------------------------

    def key(self, oid: str, lexer) -> str:
        """What a cached classification is valid for.

        The blob names the content, and blobs are immutable, so it alone would be enough
        were nothing else free to change. The pygments version and the docstring setting
        both change the answer for identical content, and so does the lexer, since the
        same bytes at two paths are two different files."""
        material = "\0".join(
            (
                str(CACHE_FORMAT),
                oid,
                self.pygments.version,
                str(self.docstrings),
                type(lexer).__name__,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def cached(self, key: str) -> str | None:
        """A stored classification, or None. A cache that cannot be read is a cache that
        is not there: nothing about it may fail a run."""
        if self.dir is None:
            return None
        try:
            with open(os.path.join(self.dir, key[:2], key[2:])) as handle:
                return handle.read()
        except OSError:
            return None

    def store(self, key: str, letters: str):
        """Write through a temporary name, so a reader never sees a half-written entry and
        two runs racing on the same blob cannot corrupt one."""
        if self.dir is None:
            return
        path = os.path.join(self.dir, key[:2], key[2:])
        temp = f"{path}.{os.getpid()}.tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(temp, "w") as handle:
                handle.write(letters)
            os.replace(temp, path)
        except OSError:
            pass

    # -- classification ---------------------------------------------------

    def note(self, path: str, counter: str):
        """Count a file against a diagnostic once, however many images of it are read."""
        if (path, counter) not in self.seen:
            self.seen.add((path, counter))
            setattr(self.diagnostics, counter, getattr(self.diagnostics, counter) + 1)

    def source(self, blobs: Blobs, refs: Refs, changed: FileDiff, side: str, queued=()):
        """Everything lexing one image needs — its cache key, its lexer, the name that
        lexer was chosen by, and its bytes — with the bytes None wherever there is nothing
        left to lex: no pygments, no lexer, no blob, too much blob, or an answer already
        known: already in `states`, or in the `queued` keys a caller has taken but not yet
        answered. Two files can be the same blob — a copy, a rename the diff scored below
        the threshold — and neither should be read twice.

        The one place any of that is decided. `letters` reads it and so does the
        pre-lexing `--jobs` does, which is what keeps a parallel run from asking a
        different question from a serial one.

        A `+` line is read from the post-image and a `-` line from the pre-image, because
        those are the files those lines are in. A rename reads its pre-image under the old
        path, which is the name its language was known by."""
        if self.pygments is None:
            return None, None, None, None
        oid = changed.pre_oid if side == "del" else changed.post_oid
        file = File(changed.old_path or changed.path) if side == "del" else changed.file
        lexer, hint = self.lexer(file), self.hint(file)
        if lexer is None:
            self.note(changed.path, "unknown_lexer_files")
            return None, None, None, None
        key = self.key(oid, lexer) if oid else None
        if key is not None:
            if key in self.states or key in queued:
                return key, lexer, hint, None
            stored = self.cached(key)
            if stored is not None:
                self.diagnostics.cache_hits += 1
                self.states[key] = stored
                return key, lexer, hint, None
        data = self.blob(blobs, refs, changed, side, oid)
        if data is None:
            self.note(changed.path, "oversize_skipped_files")
            return key, lexer, hint, None
        self.note(changed.path, "files_read")
        return key, lexer, hint, data

    def learn(self, key: str | None, letters: str) -> str:
        """Keep a fresh classification — for the rest of this run, and for the next one."""
        self.diagnostics.blobs_lexed += 1
        if key is not None:
            self.states[key] = letters
            self.store(key, letters)
        return letters

    def letters(self, blobs: Blobs, refs: Refs, changed: FileDiff, side: str) -> str:
        """The classification of one image of one file, empty where there is none."""
        key, lexer, _, data = self.source(blobs, refs, changed, side)
        if key is not None and key in self.states:
            return self.states[key]
        if data is None:
            return ""
        return self.learn(
            key, classify(data.decode("utf-8", "replace"), lexer, self.pygments, self.docstrings)
        )

    def blob(
        self, blobs: Blobs, refs: Refs, changed: FileDiff, side: str, oid: str | None
    ) -> bytes | None:
        """The bytes of one image, over the shared `cat-file` process.

        A working-tree comparison has no object for its post-image — a file is not written
        to the store until it is added — so there the file on disk is that image."""
        if oid is not None:
            return blobs.data(oid, cap=self.cap)
        if refs.mode != WORKING_TREE or side == "del":
            return None
        try:
            path = os.path.join(self.git.root, changed.path)
            if os.path.getsize(path) > self.cap:
                return None
            with open(path, "rb") as handle:
                return handle.read()
        except OSError:
            return None


def cache_dir(git: Git) -> str | None:
    """Where lexed blobs are remembered.

    `--git-common-dir`, never `.git`. In a linked worktree `.git` is a file rather than a
    directory, and this tool is run from linked worktrees by design. The common directory
    is also the right place on the merits: the cache is keyed on blob names, which every
    worktree of a repository agrees about."""
    common = git.text("rev-parse", "--git-common-dir")
    if common is None:
        return None
    return os.path.join(git.root, common, CACHE_DIR)


def annotate(git: Git, diff: Diff, comments: Comments, prepass=None):
    """Give every counted line its comment state.

    Each image is classified once and read many times: the two sides of a file are at most
    two blobs however many lines of it changed. A line the classification does not reach —
    no lexer, an oversize blob, no pygments at all — is `unknown`, which counts as code.
    That is the safe direction for a budget. The other one would let an unfamiliar
    extension silently zero out a large change.

    A `prepass` narrows this to the files whose classification anything will ask about.
    Lexing is the one genuinely expensive step, and a file the configuration already
    settled from its path is a file whose comment state no rule will ever consult — so its
    lines keep the `None` that means unanswerable, which is what they would have been
    asked as."""
    blobs = Blobs(git)
    try:
        for changed in diff.files:
            if prepass is not None and prepass.resolved(changed):
                continue
            images = {}
            for line in changed.lines or ():
                if line.change not in images:
                    images[line.change] = comments.letters(blobs, diff.refs, changed, line.change)
                letters = images[line.change]
                index = line.number - 1
                line.comment = CODES[letters[index]] if 0 <= index < len(letters) else "unknown"
    finally:
        blobs.close()
    diff.diagnostics = comments.diagnostics


def lex(text: str, hint: str, docstrings: bool) -> str:
    """One blob's classification, from plain data alone.

    A worker builds its own pygments and its own lexer from the filename hint rather than
    being handed either. A lexer is not data, and what crosses a process boundary has to
    be — pickling one would ship token types whose identity is what `classify` compares
    against."""
    pygments = Pygments()
    lexer = pygments.lexer(hint)
    return classify(text, lexer, pygments, docstrings) if lexer is not None else ""


def prelex(git: Git, diff: Diff, comments: Comments, jobs: int, prepass=None):
    """Lex every blob the walk will ask about, over a pool, before it asks.

    Per-file lexing is CPU-bound and shares nothing, so it parallelises perfectly — but a
    worker costs more to start than an ordinary pull request's worth of lexing costs to
    do, which is why `--jobs` defaults to 1 and this is not reached at all. Answers land
    in the store a serial run fills, so nothing downstream can tell which happened.

    A pool that will not start is not a failure: the walk lexes what is left, serially,
    and the run is slow rather than broken."""
    import concurrent.futures
    import multiprocessing

    work, blobs = {}, Blobs(git)
    try:
        for changed in diff.files:
            if prepass is not None and prepass.resolved(changed):
                continue
            for side in sorted({line.change for line in changed.lines or ()}):
                key, _, hint, data = comments.source(blobs, diff.refs, changed, side, queued=work)
                # A keyless image cannot be remembered under a name the walk would look
                # it up by, so it is left for the walk to lex where it stands.
                if key is not None and data is not None:
                    work[key] = (data.decode("utf-8", "replace"), hint)
    finally:
        blobs.close()
    if not work:
        return
    try:
        context = multiprocessing.get_context("fork")
    except ValueError:
        context = None
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=jobs, mp_context=context) as pool:
            done = {
                key: pool.submit(lex, text, hint, comments.docstrings)
                for key, (text, hint) in work.items()
            }
            for key, future in done.items():
                comments.learn(key, future.result())
    except Exception as exc:  # a pool this platform will not give
        comments.diagnostics.warnings.append(
            f"--jobs could not start a worker pool, so lexing ran serially: {exc}"
        )


def uses_facet(config: Config, facet: str) -> bool:
    """Whether any rule in the configuration reads a facet.

    Comment detection is the one classification that costs real work, so it runs only when
    something asks for it. This over-approximates — a matcher neither reported nor
    referenced still counts — which is the safe direction, and the compiled rule set is
    where a sharper answer belongs."""
    return any(facet in rule.facets for rule in iter_rules(config))


def needs_patch(config: Config) -> bool:
    """Whether counting under this configuration has to read the patch at all.

    Only `content` and `comment` do. Everything else — which files changed, their modes
    and blob names, how many lines each gained and lost, and which side a count is on —
    comes from `--raw` with `--numstat`, which collapses a 50k-line diff to a few hundred
    rows and iterates no lines whatever. The answer is read off the compiled rule set at
    load, so nothing about the choice depends on how large the diff turns out to be."""
    return any(uses_facet(config, facet) for facet in PATCH_FACETS)


# ---------------------------------------------------------------------------
# The census
#
# One forward pass per counted line, in the order the specification gives: global
# exclusion, `total`, every reported matcher, every group, and `unmatched` for a line
# nothing claimed.
#
# Global exclusion runs first and is terminal. An excluded line is charged to `exempt`,
# attributed to the rule that caught it, and never seen again — no matcher and no group
# is asked about it, and nothing rescues it. That is what makes `total` and `exempt` a
# genuine partition of the diff, and what lets a trace be one linear story per line rather
# than a graph.
# ---------------------------------------------------------------------------

# What a limit makes of a bucket. `warn` is the grace band: reported, and not a failure.
OK, WARN, OVER = "ok", "warn", "over"

# How a census reports. JSON is the schema; text is for a human reading a gate failure.
JSON, TEXT = "json", "text"

# A metric names a count. `changed` is added plus deleted, which is what a modified line
# contributes and what a budget on churn measures.
METRIC_FIELDS = {"added": "adds", "deleted": "dels", "changed": "changed"}

# What the shipped exclusions are called where a rule is attributed. The file's own are
# `global[0]`, `global[1]`, by their position in `[diff_census.global].exclude`.
BUILTIN_LABEL = "builtin"


@dataclass
class Bucket:
    """One count. `paths` is a set rather than a number because a file offers many lines
    to a bucket and is meant to be counted once."""

    adds: int = 0
    dels: int = 0
    paths: set[str] = field(default_factory=set)

    def charge(self, path: str, adds: int, dels: int):
        self.adds, self.dels = self.adds + adds, self.dels + dels
        self.paths.add(path)

    @property
    def changed(self) -> int:
        return self.adds + self.dels

    @property
    def files(self) -> int:
        """Files contributing at least one line, which is the only thing charged."""
        return len(self.paths)

    def value(self, metric: str) -> int:
        return getattr(self, METRIC_FIELDS[metric])


class NoTrace:
    """The trace nobody asked for. Every recording does nothing, so the pipeline has one
    shape rather than a traced one and an untraced one that can drift apart."""

    def caught(self, label, adds, dels):
        pass

    def matched(self, name, label, adds, dels):
        pass

    def grouped(self, name, label, adds, dels):
        pass

    def tally(self, name, adds, dels):
        pass


NO_TRACE = NoTrace()


@dataclass
class Trace(NoTrace):
    """Why one file's lines landed where they did.

    Counted rather than decided. A rule reading line text is true of some of a file's
    lines and false of others, so the only honest answer at file granularity is how
    many — which is what makes a trace usable on the file whose number looks wrong."""

    changed: FileDiff
    exempt: dict[str, int] = field(default_factory=dict)
    matchers: dict[str, dict[str, int]] = field(default_factory=dict)
    groups: dict[str, dict[str, int]] = field(default_factory=dict)
    buckets: dict[str, Bucket] = field(default_factory=dict)

    @staticmethod
    def bump(counts: dict, label: str, lines: int):
        counts[label] = counts.get(label, 0) + lines

    def caught(self, label, adds, dels):
        self.bump(self.exempt, label, adds + dels)

    def matched(self, name, label, adds, dels):
        self.bump(self.matchers.setdefault(name, {}), label, adds + dels)

    def grouped(self, name, label, adds, dels):
        self.bump(self.groups.setdefault(name, {}), label, adds + dels)

    def tally(self, name, adds, dels):
        self.buckets.setdefault(name, Bucket()).charge(self.changed.path, adds, dels)


@dataclass
class Census:
    """What the classification found, and the configuration it was found under — the two
    are read together everywhere downstream, since a count without its budget is not yet
    a verdict."""

    refs: Refs
    config: Config
    via: str = NUMSTAT
    total: Bucket = field(default_factory=Bucket)
    unmatched: Bucket = field(default_factory=Bucket)
    exempt: Bucket = field(default_factory=Bucket)
    by_rule: dict[str, Bucket] = field(default_factory=dict)
    groups: dict[str, Bucket] = field(default_factory=dict)
    matchers: dict[str, Bucket] = field(default_factory=dict)
    diagnostics: Diagnostics = field(default_factory=Diagnostics)
    binary_files: int = 0
    submodule_changes: int = 0
    elapsed_ms: int = 0
    warnings: list[str] = field(default_factory=list)
    traces: list[Trace] = field(default_factory=list)  # only where one was asked for


def global_rules(config: Config) -> list[tuple[str, Rule]]:
    """The global exclusion rules in evaluation order, each under the name its `by_rule`
    entry carries. The shipped list evaluates as one rule and is named for what it is."""
    return [(BUILTIN_LABEL, rule) for rule in config.builtin_exclude] + [
        (f"global[{index}]", rule) for index, rule in enumerate(config.exclude)
    ]


class Prepass:
    """Which files a configuration settles without reading a line of them.

    Every rule splits into the conjuncts a file answers — `path`, `dir`, `name`, `ext`,
    `mime`, `size`, `mode`, and a `matches` resolving to those — and the conjuncts only a
    line answers. Where the file-level ones already decide every rule list a census
    consults, the file's counts are charged in bulk against one subject per side, its
    lines are never walked, and its blobs are never lexed.

    On an ordinary change most files land here, because a rule reading `comment` is
    almost always paired with an `include` that rules most of the tree out first. The
    exception is a reported matcher whose only facet is a line facet: it is asked about
    every file, so nothing settles."""

    def __init__(self, config: Config):
        self.excluders = [rule for _, rule in global_rules(config)]
        self.matchers = [m.rules for m in config.matchers.values() if m.report]
        self.groups = list(config.groups.values())
        self.settled = {}

    def decided(self, subject: Subject) -> bool:
        """The census's own order of questions, asked three-valued. Which questions go
        unasked is half of what makes this cheap: global exclusion is terminal, so a file
        it certainly catches settles without a matcher or a group being consulted."""
        caught = any_state(self.excluders, subject)[0]
        if caught is None:
            return False
        if caught:
            return True
        if any(any_state(rules, subject)[0] is None for rules in self.matchers):
            return False
        return all(self.grouped(group, subject) for group in self.groups)

    def grouped(self, group: Group, subject: Subject) -> bool:
        """`include` and then `exclude`, in that order and only that far. An `include` that
        already says no makes the `exclude` beside it irrelevant — which is exactly the
        shape a `comment` exclusion inside a path-scoped group takes, and the reason most
        of a tree never reaches the lexer."""
        if group.include:
            included = any_state(group.include, subject)[0]
            if included is None:
                return False
            if not included:
                return True
        return any_state(group.exclude, subject)[0] is not None

    def resolved(self, changed: FileDiff) -> bool:
        """Whether this file's every side settles. Kept, because the answer is wanted once
        before the blobs are read and again while the census is taken."""
        if changed.path not in self.settled:
            self.settled[changed.path] = all(
                self.decided(Subject(changed.file, change=side))
                for side, count in (("add", changed.adds), ("del", changed.dels))
                if count
            )
        return self.settled[changed.path]


def charges(changed: FileDiff, resolved: bool = False):
    """Every `(subject, adds, dels)` a file contributes.

    A file counted from the patch offers one charge per line, which is what a rule reading
    line text needs. A file counted from numstat has no lines to offer and contributes one
    charge per side: its adds against a subject that says `add`, its dels against one that
    says `del`. Two charges rather than one is what keeps `change` answerable off numstat,
    and it charges every bucket exactly what a single combined charge would have — the
    same subject decides both, and a bucket sums.

    `resolved` says the pre-pass settled every rule list from the file's facets alone, so
    a file the patch did supply lines for is charged the same way a numstat one is — the
    lines are there, and nothing left has a question to put to them.

    A file with nothing to count offers nothing, so a binary, a gitlink, a mode flip and a
    bare rename join no bucket rather than joining one at zero."""
    if changed.lines is None or resolved:
        if changed.adds:
            yield Subject(changed.file, change="add"), changed.adds, 0
        if changed.dels:
            yield Subject(changed.file, change="del"), 0, changed.dels
        return
    for line in changed.lines:
        yield (
            Subject(changed.file, text=line.text, change=line.change, comment=line.comment),
            int(line.change == "add"),
            int(line.change == "del"),
        )


def take_census(diff: Diff, config: Config, trace: bool = False) -> Census:
    """Sort every counted line of the diff into the buckets the configuration defines.

    A file the pre-pass settled is charged in bulk, one subject per side, rather than a
    line at a time. Which files those are is decided before the blobs are read, so the
    same answer is reused here rather than recomputed.

    With `trace`, keep a per-file account of which rule decided what, which is what
    `--explain` reads. A bulk charge traces the same rules a walk would name, because the
    pre-pass reached them through the very conjuncts a walk would have evaluated."""
    prepass = diff.prepass or Prepass(config)
    diagnostics = diff.diagnostics or Diagnostics()
    census = Census(
        refs=diff.refs,
        config=config,
        via=diff.via,
        diagnostics=diagnostics,
        binary_files=diff.binary_files,
        submodule_changes=diff.submodule_changes,
        warnings=list(config.warnings) + list(diagnostics.warnings),
    )
    labels = [label for label, _ in global_rules(config)]
    excluders = [rule for _, rule in global_rules(config)]
    matchers = [m for m in config.matchers.values() if m.report]
    # Declaration order, which is the order `first_match_wins` charges in.
    groups = list(config.groups.values())
    census.matchers = {m.name: Bucket() for m in matchers}
    census.groups = {g.name: Bucket() for g in groups}
    single = config.overlap == "first_match_wins"

    for changed in diff.files:
        path = changed.path
        story = Trace(changed) if trace else NO_TRACE
        for subject, adds, dels in charges(changed, prepass.resolved(changed)):
            caught = first_match(excluders, subject)
            if caught is not None:
                census.exempt.charge(path, adds, dels)
                census.by_rule.setdefault(labels[caught], Bucket()).charge(path, adds, dels)
                story.caught(labels[caught], adds, dels)
                story.tally("exempt", adds, dels)
                continue
            census.total.charge(path, adds, dels)
            story.tally("total", adds, dels)
            claimed = charged = False
            for matcher in matchers:
                hit = first_match(matcher.rules, subject)
                if hit is None:
                    continue
                census.matchers[matcher.name].charge(path, adds, dels)
                story.matched(matcher.name, f"rules[{hit}]", adds, dels)
                story.tally(matcher.name, adds, dels)
                claimed = True
            for group in groups:
                inside, included, excluded = membership(group, subject)
                if included is not None:
                    story.grouped(group.name, f"include[{included}]", adds, dels)
                if excluded is not None:
                    story.grouped(group.name, f"exclude[{excluded}]", adds, dels)
                if not inside:
                    continue
                claimed = True
                if single and charged:
                    continue  # a member, and already charged elsewhere
                census.groups[group.name].charge(path, adds, dels)
                story.tally(group.name, adds, dels)
                charged = True
                if single and not trace:
                    # Nothing later can be charged, so nothing later need be asked —
                    # except while a trace is being kept, which has to be able to say
                    # that a later group would have matched too.
                    break
            if not claimed:
                census.unmatched.charge(path, adds, dels)
                story.tally("unmatched", adds, dels)
        if trace:
            census.traces.append(story)
    return census


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def verdict(limit: Limit, bucket: Bucket) -> str:
    """What a limit makes of a bucket, taking the worst any of its metrics has to say.

    Below the limit is `ok`. From the limit to the hard threshold inclusive is `warn`: the
    grace band is reported prominently and passes, because it warns rather than moving the
    limit. Past the threshold is `over`."""
    worst = OK
    for metric, value in limit.metrics.items():
        count = bucket.value(metric)
        if count > limit.hard(metric):
            return OVER
        if count >= value:
            worst = WARN
    return worst


def verdicts(census: Census) -> list[tuple[str, Limit, Bucket, str]]:
    """Every configured limit, the bucket it budgets, and what it makes of it.

    Limits live on groups and on `[diff_census.limits]`, which budgets `total`, the
    denominator every group is a subset of, and `unmatched`, the part of it nothing
    claimed."""
    budgeted = [(g.name, g.limit, census.groups[g.name]) for g in census.config.groups.values()]
    budgeted += [
        (name, limit, getattr(census, name)) for name, limit in census.config.limits.items()
    ]
    return [(name, limit, bucket, verdict(limit, bucket)) for name, limit, bucket in budgeted]


def gating(gate: bool | None, config: Config) -> bool:
    """Whether this run enforces. Gate mode is the default as soon as the configuration
    defines a group, because a group is a budget and a budget nobody checks is a
    comment; `--census` and `--gate` say so outright."""
    return bool(config.groups) if gate is None else gate


def exit_code(gate: bool, results) -> int:
    """0 for satisfied or within a band or reporting only, 1 for a limit past its band.
    2 is for a census that could not be taken and is never decided here."""
    return 1 if gate and any(status == OVER for *_, status in results) else 0


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def limit_json(limit: Limit | None) -> dict | None:
    if limit is None:
        return None
    return {
        "metrics": limit.metrics,
        "grace": limit.grace,
        "hard": {m: limit.hard(m) for m in limit.metrics},
    }


def config_json(config: Config) -> dict:
    """The parsed configuration, as data. Matchers and groups are arrays rather than
    objects so declaration order survives the round trip."""
    return {
        "config": {
            "source": config.source,
            "version": config.version,
            "overlap": config.overlap,
            "docstrings_as_comments": config.docstrings_as_comments,
            "global": {
                "extend_builtin": config.extend_builtin,
                "exclude": [r.facets for r in config.exclude],
                "effective": [r.facets for r in config.global_exclude],
            },
            "matchers": [
                {"name": m.name, "report": m.report, "rules": [r.facets for r in m.rules]}
                for m in config.matchers.values()
            ],
            "groups": [
                {
                    "name": g.name,
                    "limit": limit_json(g.limit),
                    "include": [r.facets for r in g.include],
                    "exclude": [r.facets for r in g.exclude],
                }
                for g in config.groups.values()
            ],
            "limits": {name: limit_json(limit) for name, limit in config.limits.items()},
            "warnings": list(config.warnings),
        }
    }


def bucket_json(bucket: Bucket) -> dict:
    return {
        "adds": bucket.adds,
        "dels": bucket.dels,
        "changed": bucket.changed,
        "files": bucket.files,
    }


def budget_json(limit: Limit) -> dict | list:
    """A limit as the report carries it: the metric, its value, the grace fraction, and
    the hard threshold the band ends at.

    A limit naming several metrics is several budgets, each of which must pass on its
    own, so it reports as a list of them in the order the metrics are documented."""
    each = [
        {
            "metric": metric,
            "value": limit.metrics[metric],
            "grace": limit.grace,
            "hard": limit.hard(metric),
        }
        for metric in METRICS
        if metric in limit.metrics
    ]
    return each[0] if len(each) == 1 else each


def diagnostics_json(census: Census) -> dict:
    """What the census could not do, and what it cost. Every number has a real source:
    nothing here is a placeholder for work a later phase does."""
    counted = census.diagnostics
    return {
        "binary_files": census.binary_files,
        "submodule_changes": census.submodule_changes,
        "unknown_lexer_files": counted.unknown_lexer_files,
        "oversize_skipped_files": counted.oversize_skipped_files,
        "files_read": counted.files_read,
        "blobs_lexed": counted.blobs_lexed,
        "cache_hits": counted.cache_hits,
        "elapsed_ms": census.elapsed_ms,
        "warnings": list(census.warnings),
    }


def census_json(census: Census) -> dict:
    """The report, per the schema.

    `limit` and `status` appear only where a limit is configured, so their presence is
    the signal that a bucket is budgeted at all. The grand total — `total` plus `exempt` —
    is deliberately not a field of its own, so there is one obvious way to read each
    number rather than two that can disagree."""
    budgets = {name: (limit, status) for name, limit, _, status in verdicts(census)}

    def budgeted(name: str, bucket: Bucket) -> dict:
        out = bucket_json(bucket)
        if name in budgets:
            limit, status = budgets[name]
            out["limit"], out["status"] = budget_json(limit), status
        return out

    exempt = bucket_json(census.exempt)
    exempt["by_rule"] = {
        label: {"adds": caught.adds, "dels": caught.dels, "changed": caught.changed}
        for label, caught in (
            (label, census.by_rule.get(label)) for label, _ in global_rules(census.config)
        )
        if caught is not None
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "refs": {
            "base": census.refs.base,
            "head": census.refs.head,
            "merge_base": census.refs.merge_base,
            "mode": census.refs.mode,
        },
        "groups": {name: budgeted(name, bucket) for name, bucket in census.groups.items()},
        "matchers": {name: bucket_json(bucket) for name, bucket in census.matchers.items()},
        "totals": {
            "total": budgeted("total", census.total),
            "unmatched": budgeted("unmatched", census.unmatched),
            "exempt": exempt,
        },
        "diagnostics": diagnostics_json(census),
    }


# ---------------------------------------------------------------------------
# The text report
#
# For a person reading a gate failure in a CI log, where the question is which bucket went
# over and by how much. Nothing parses it, and nothing should: the schema is what a machine
# reads.
# ---------------------------------------------------------------------------

SIZE_UNIT_NAMES = ("B", "KiB", "MiB", "GiB")


def human_size(size: int | None) -> str:
    """A blob size as a reader would say it, or `?` where there is none to say."""
    if size is None:
        return "?"
    scaled = float(size)
    for unit in SIZE_UNIT_NAMES:
        if scaled < 1024 or unit == SIZE_UNIT_NAMES[-1]:
            return f"{round(scaled, 1):g}{unit}"
        scaled /= 1024


def budget_text(limit: Limit) -> str:
    """A limit as one cell: every metric it names, and the band where there is one."""
    named = ", ".join(
        f"{limit.metrics[metric]} {metric}" for metric in METRICS if metric in limit.metrics
    )
    return named + (f" +{limit.grace * 100:g}%" if limit.grace else "")


def table(headings, rows) -> list[str]:
    """Rows under headings, each column as wide as its widest cell.

    A column of numbers lines up on the right and a column of words on the left, which is
    the whole of what alignment is for here. A row shorter than the headings is padded
    rather than rejected, since a bucket with no limit has nothing to say in those two
    columns."""
    filled = [list(row) + [""] * (len(headings) - len(row)) for row in rows]
    columns = list(range(len(headings)))
    widths = [max(len(str(row[column])) for row in [list(headings), *filled]) for column in columns]
    numeric = [any(isinstance(row[column], int) for row in filled) for column in columns]
    out = []
    for row in [list(headings), *filled]:
        cells = [
            str(cell).rjust(width) if right else str(cell).ljust(width)
            for cell, width, right in zip(row, widths, numeric, strict=False)
        ]
        out.append("  " + "  ".join(cells).rstrip())
    return out


def bucket_row(name: str, bucket: Bucket, budgets: dict) -> list:
    row = [name, bucket.adds, bucket.dels, bucket.changed, bucket.files]
    if name in budgets:
        limit, status = budgets[name]
        row += [budget_text(limit), status]
    return row


def strained(limit: Limit, bucket: Bucket):
    """Every metric of a limit that is not comfortable, as `(status, metric, count,
    value, hard)`. A comfortable limit yields nothing, so a clean census says nothing."""
    for metric in METRICS:
        if metric not in limit.metrics:
            continue
        count, value = bucket.value(metric), limit.metrics[metric]
        hard = limit.hard(metric)
        if count > hard:
            yield OVER, metric, count, value, hard
        elif count >= value:
            yield WARN, metric, count, value, hard


def banner(census: Census) -> list[str]:
    """The lines a reader has to see. The grace band is reported prominently precisely
    because it passes: a warning nobody notices is a limit that quietly moved."""
    out = []
    for name, limit, bucket, _ in verdicts(census):
        for status, metric, count, value, hard in strained(limit, bucket):
            out.append(
                "{}  {}: {} {} against a limit of {}, {}".format(
                    status.upper(),
                    name,
                    count,
                    metric,
                    value,
                    f"past the {hard} its grace band ends at"
                    if status == OVER
                    else f"inside the grace band ending at {hard}",
                )
            )
    return out


def census_text(census: Census) -> str:
    """The census as a table of groups, then matchers, then the census-wide buckets."""
    budgets = {name: (limit, status) for name, limit, _, status in verdicts(census)}
    counts = ("adds", "dels", "changed", "files")
    header = f"{census.refs.describe()}  {census.refs.mode}, via {census.via}"
    if census.refs.merge_base:
        header += f", merge base {census.refs.merge_base[:9]}"
    out = [header, ""]
    if census.groups:
        out += [
            *table(
                ("group", *counts, "limit", "status"),
                [bucket_row(name, bucket, budgets) for name, bucket in census.groups.items()],
            ),
            "",
        ]
    if census.matchers:
        out += [
            *table(
                ("matcher", *counts),
                [bucket_row(name, bucket, {}) for name, bucket in census.matchers.items()],
            ),
            "",
        ]
    rows = [
        bucket_row("total", census.total, budgets),
        bucket_row("unmatched", census.unmatched, budgets),
        bucket_row("exempt", census.exempt, {}),
    ]
    rows += [
        ["  " + label, caught.adds, caught.dels, caught.changed, caught.files]
        for label, caught in census.by_rule.items()
    ]
    out += [*table(("census", *counts, "limit", "status"), rows), ""]
    diagnostics = census.diagnostics
    out += [
        f"  diagnostics  {census.binary_files} binary, {census.submodule_changes} submodule, "
        f"{diagnostics.unknown_lexer_files} without a lexer, "
        f"{diagnostics.oversize_skipped_files} oversize",
        f"               {diagnostics.files_read} files read, {diagnostics.blobs_lexed} lexed, "
        f"{diagnostics.cache_hits} from the cache, {census.elapsed_ms} ms",
    ]
    out += ["  warning      " + warning for warning in census.warnings]
    raised = banner(census)
    if raised:
        out += [""] + ["  " + line for line in raised]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# --explain
#
# One linear story per file: what it is, whether a global rule took it, which matchers
# claimed it, which group rule let it in and which kept it out, and what it ended up
# contributing. Global exclusion being terminal is what makes the story linear.
#
# A rules engine without this is undebuggable, and this is the first thing anyone reaches
# for when a number looks wrong — so it names the rule, never only the outcome.
# ---------------------------------------------------------------------------

INDENT = 14


def rule_text(rule: Rule) -> str:
    """A rule as its facets, spelled the way the configuration spells them."""
    return " ".join(
        "{}={}".format(facet, ",".join(f'"{v}"' for v in values))
        for facet, values in rule.facets.items()
    )


def labelled_rule(rules: list[Rule], label: str) -> Rule:
    """The rule an `include[2]`-style label names."""
    return rules[int(label[label.index("[") + 1 : -1])]


def section(name: str, lines: list[str]) -> list[str]:
    head = f"  {name}:".ljust(INDENT)
    return [head + lines[0]] + [" " * INDENT + line for line in lines[1:]]


def facet_text(file: File) -> str:
    return "ext={} mime={} mode={} size={}".format(
        file.ext or "(none)", file.mime, file.mode or "?", human_size(file.size)
    )


def exempt_lines(census: Census, story: Trace) -> list[str]:
    rules = dict(global_rules(census.config))
    return [
        f"EXEMPT <- {label}  {rule_text(rules[label])}  ({lines} lines)"
        for label, lines in story.exempt.items()
    ]


def matcher_lines(census: Census, story: Trace) -> list[str]:
    out = []
    for name, hits in story.matchers.items():
        rules = census.config.matchers[name].rules
        out += [
            f"{name} <- {label} {rule_text(labelled_rule(rules, label))}  ({lines} lines)"
            for label, lines in hits.items()
        ]
    return out


def group_lines(census: Census, story: Trace) -> list[str]:
    """Every group, and what it made of this file — including the ones that took none of
    it, since "which group did not claim these lines" is half the question."""
    out = []
    for name, group in census.config.groups.items():
        hits = story.groups.get(name, {})
        counted = story.buckets.get(name)
        out.append(f"{name}  ({counted.changed if counted else 0} lines counted)")
        for key, rules in (("include", group.include), ("exclude", group.exclude)):
            matched = [(label, lines) for label, lines in hits.items() if label.startswith(key)]
            if not rules:
                out.append(
                    f"    {key}: omitted, matches every line"
                    if key == "include"
                    else "    exclude: none"
                )
            elif not matched:
                out.append(f"    {key}: no match")
            out += [
                f"    {label} {rule_text(labelled_rule(rules, label))}  ({lines} lines)"
                for label, lines in matched
            ]
    return out


def counted_text(story: Trace) -> str:
    if not story.buckets:
        return "nothing — this file counts no lines"
    return " | ".join(
        f"{name} +{bucket.adds} -{bucket.dels}" for name, bucket in story.buckets.items()
    )


def file_note(changed: FileDiff) -> str:
    parts = ["binary"] if changed.binary else ["submodule"] if changed.submodule else []
    if changed.old_path:
        parts.append(f"renamed from {changed.old_path}")
    return "  ({})".format(", ".join(parts)) if parts else ""


def explain_file(census: Census, story: Trace) -> list[str]:
    changed = story.changed
    out = [f"{changed.path}  (+{changed.adds} -{changed.dels}){file_note(changed)}"]
    out += section("facets", [facet_text(changed.file)])
    out += section("global", exempt_lines(census, story) or ["no match"])
    out += section("matchers", matcher_lines(census, story) or ["no match"])
    out += section("groups", group_lines(census, story) or ["none defined"])
    out += section("counted", [counted_text(story)])
    return out


def explain_text(census: Census, only: str | None = None) -> str:
    """The trace for every file, or for the one path named."""
    wanted = [story for story in census.traces if only is None or story.changed.path == only]
    if not wanted:
        return f"diff-census: no file at {only!r} in this diff\n"
    blocks = [explain_file(census, story) for story in wanted]
    return "\n\n".join("\n".join(block) for block in blocks) + "\n"


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="diff_census.py", description="Counts changed lines into configured buckets."
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help=(
            f"the configuration to read. Overrides ${CONFIG_ENV} and the repository's "
            f"{CONFIG_RELPATH}. A path that is not a file is an error."
        ),
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help=("print the parsed configuration as JSON and exit, counting nothing."),
    )
    parser.add_argument(
        "--base",
        metavar="REF",
        help=("what to measure against. Defaults to the repository's default branch."),
    )
    parser.add_argument(
        "--head",
        metavar="REF",
        default="HEAD",
        help=("the end of the comparison. Defaults to HEAD."),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--two-dot",
        dest="mode",
        action="store_const",
        const=TWO_DOT,
        help="compare the base and the head directly, rather than from their merge base.",
    )
    mode.add_argument(
        "--staged",
        dest="mode",
        action="store_const",
        const=STAGED,
        help="compare the index against the head.",
    )
    mode.add_argument(
        "--working-tree",
        dest="mode",
        action="store_const",
        const=WORKING_TREE,
        help="compare the working tree against the head.",
    )
    parser.set_defaults(mode=THREE_DOT)
    parser.add_argument(
        "--no-renames",
        dest="renames",
        action="store_false",
        help=("count a moved file as a deletion and an addition rather than a rename."),
    )
    parser.add_argument(
        "--force-patch",
        dest="patch",
        action="store_true",
        help=(
            "count by walking the patch rather than by reading numstat. The two agree; this "
            "is how to see that they do."
        ),
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        metavar="N",
        help=(
            "lex up to N blobs at once. Defaults to 1, and should usually stay there: a "
            "worker costs more to start than an ordinary pull request's worth of lexing "
            "costs to do. An escape hatch for a very large change, not a setting to raise."
        ),
    )
    parser.add_argument(
        "--no-cache",
        dest="cache",
        action="store_false",
        help=(
            "lex every blob afresh rather than reading the cache under the common git "
            "directory. The counts are the same either way."
        ),
    )
    parser.add_argument(
        "--format",
        dest="format",
        choices=(JSON, TEXT),
        default=JSON,
        help="how to report. JSON is the schema; text is for a human "
        "reading a gate failure in a CI log.",
    )
    parser.add_argument(
        "--explain",
        nargs="?",
        metavar="PATH",
        const="",
        default=None,
        help="trace how every file, or the one named, was classified: "
        "its facets, the rules that claimed it, and what it "
        "contributed. Printed instead of the report.",
    )
    enforcement = parser.add_mutually_exclusive_group()
    enforcement.add_argument(
        "--gate",
        dest="gate",
        action="store_true",
        default=None,
        help="enforce the configured limits. The default once the configuration defines a group.",
    )
    enforcement.add_argument(
        "--census",
        dest="gate",
        action="store_false",
        default=None,
        help="report without a verdict, whatever the limits say.",
    )
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    return args


def measure(args, config: Config) -> Diff:
    """Read the diff, and classify comment state where some rule asks for it.

    Which acquisition path is taken is decided from the configuration rather than by the
    caller: a rule reading line text needs the patch, nothing else does, and a run that
    does not need it iterates no lines at all. `--force-patch` overrides the decision, so
    the two paths can be held to the same answer on a configuration both can serve.

    Lexing is the one classification that costs real work, so the blobs are read only when
    the `comment` facet is actually used."""
    git = Git.open()
    refs = resolve_refs(git, args.mode, base=args.base, head=args.head)
    diff = acquire(git, refs, renames=args.renames, patch=args.patch or needs_patch(config))
    diff.prepass = Prepass(config)
    if uses_facet(config, "comment"):
        comments = Comments(git, docstrings=config.docstrings_as_comments, cache=args.cache)
        if args.jobs > 1:
            prelex(git, diff, comments, args.jobs, prepass=diff.prepass)
        annotate(git, diff, comments, prepass=diff.prepass)
        for warning in comments.diagnostics.warnings:
            sys.stderr.write(f"diff-census: {warning}\n")
    return diff


def main(argv):
    args = parse_args(argv)
    started = time.monotonic()
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        sys.stderr.write(f"diff-census: config: {exc}\n")
        return 2
    for warning in config.warnings:
        sys.stderr.write(f"diff-census: {config.source}: {warning}\n")
    if args.print_config:
        json.dump(config_json(config), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    gate = gating(args.gate, config)
    # Checked here rather than at load: a configuration with matchers and no groups is a
    # perfectly good census, which is what the tool is named for. It is only as a gate
    # that it is broken — and a gate with nothing to enforce must not pass everything.
    if gate and not config.groups:
        sys.stderr.write(
            "diff-census: gate: no groups are defined, so there is nothing to enforce\n"
            "  define a group, or run with --census to report without a verdict\n"
        )
        return 2
    try:
        diff = measure(args, config)
    except GitError as exc:
        sys.stderr.write(f"diff-census: {exc}\n")
        return 2
    census = take_census(diff, config, trace=args.explain is not None)
    census.elapsed_ms = int((time.monotonic() - started) * 1000)
    if args.explain is not None:
        sys.stdout.write(explain_text(census, args.explain or None))
    elif args.format == TEXT:
        sys.stdout.write(census_text(census))
    else:
        json.dump(census_json(census), sys.stdout, indent=2)
        sys.stdout.write("\n")
    return exit_code(gate, verdicts(census))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
