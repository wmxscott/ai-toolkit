# diff_census.py — reference

`diff_census.py` counts the lines a change adds and removes and sorts them into buckets a
configuration defines. This document is its reference: what it compares, what it counts as
a line, where the configuration file lives, what it may contain, and what it rejects.

```sh
./diff_census.py --base main                  # the report, as JSON
./diff_census.py --base main --format text    # the same, for a person
./diff_census.py --explain src/api/handlers.py
./diff_census.py --print-config
```

The script declares its dependencies inline (PEP 723) and runs through `uv`, which
resolves them on invocation: `uv run --script diff_census.py`, or `./diff_census.py`, since
the shebang does the same. A bare `python3 diff_census.py` fails for want of `pathspec`.
`pathspec` is required; `pygments` is optional, and without it every line's comment state
is `unknown`.

Two modes. **Census** counts and reports. **Gate** does that and enforces the configured
limits through its exit code, and is the default as soon as the configuration defines a
group.

## What is compared

| Selection | Compares |
|---|---|
| default | the merge base of `--base` and `--head`, against `--head` |
| `--two-dot` | `--base` against `--head` directly |
| `--staged` | the index against `--head` |
| `--working-tree` | the working tree against `--head` |

`--base` defaults to the repository's default branch: whatever `refs/remotes/origin/HEAD`
points at, and failing that `main`, then `master`. `--head` defaults to `HEAD`.

Three-dot is the default because it measures only what the branch introduced. Two-dot
folds in every commit that landed on the base after the branch was cut, which inflates
every count for reasons that have nothing to do with the change under review.

A merge base that cannot be resolved is not a measurement of zero. It exits 2, as do a ref
that names nothing, a git invocation that fails, and a run outside a repository.

Every invocation is rooted at the repository toplevel, so the directory the command runs
from changes nothing about what it reports.

Rename detection is on. `--no-renames` turns it off, and a moved file is then a deletion
and an addition of its whole contents.

`--no-ext-diff` and `--no-textconv` are always passed, and there is no switch to restore
them. A repository configuring either in `.gitattributes` would otherwise spawn an
external program per file — a cost the script does not control, producing output it cannot
parse.

## What counts as a line

A counted line is a `+` or `-` line in the body of a hunk. The `diff --git`, `---`, `+++`
and `@@` lines, and the index and mode metadata, frame the change rather than being part
of it. The `\ No newline at end of file` marker reports on the line before it and is not
one either.

A modified line appears as a deletion and an addition, and both count. That is what
`git diff --numstat` reports, and what a budget on `changed` measures.

These count zero. Each is reported rather than dropped, so that nothing is silently
invisible:

| | Why |
|---|---|
| A binary file | git offers no line counts for one |
| A submodule | a gitlink names a commit, not content |
| A mode-only change | no line differs |
| A pure rename | no line differs |

A rename classifies under its **new** path — where the code now lives, and where a
reviewer will look for it. A rename that also edits counts its edits there.

A symlink is an ordinary one-line text change: its target is the line.

An empty diff counts zero everywhere and exits 0.

### The two ways of counting

Counts come from `git diff --numstat` with `--raw`, which answers per-file counts, modes
and blob names in one pass over a few hundred rows however large the diff is. When some
rule reads `content` or `comment`, the `-U0` patch is streamed instead and the lines are
counted directly.

Those two facets are the only ones that force the patch. `change` does not: which side a
count is on is a property of the count rather than of the text, so a numstat file charges
its adds and its deletions separately and a rule reading `change` fires without a line
ever being walked.

The choice is made from the configuration, at load. The two paths agree, and the tests
hold them to it; `--force-patch` runs the patch path on demand, which is how to see that
they do.

### What is never read

Every rule splits into the conjuncts a file answers — `path`, `dir`, `name`, `ext`,
`mime`, `size`, `mode`, and a `matches` resolving to those — and the conjuncts only a
line answers. Before any blob is read, each file is resolved against every rule list the
census consults, three-valued: in, out, or depends.

A file that resolves is charged in bulk; its lines are never walked and its blobs never
lexed. The order the questions come in is what makes this pay. Global exclusion is
terminal, so a file it catches settles before a matcher is asked, and an `include` that
says no makes the `exclude` beside it irrelevant — so a `comment` rule inside a
path-scoped group costs nothing on the files that group does not admit, which on an
ordinary change is most of them.

The shape that defeats it is a **reported matcher whose only facet is a line facet**: it
is asked about every file, so nothing settles and every blob is lexed. Give such a matcher
a path or an extension as well, if the cost shows up.

## File facts read from the diff

`size` and `mode` come from the post-image — the file as the change leaves it — except for
a deletion, where the pre-image is the only image there is. Sizes come from one long-lived
`git cat-file --batch-check` rather than a subprocess per file.

A submodule has no blob and so no size. A working-tree comparison has no object for its
post-image either, since a file is not written to the object store until it is added, so
there the file on disk is measured directly.

## Comment detection

The `comment` facet has four values, and a line has exactly one of them:

| Value | Meaning |
|---|---|
| `only` | Every non-whitespace token on the line is a comment token |
| `trailing` | Code and a comment on the same line |
| `none` | No comment tokens |
| `unknown` | Nothing could classify the line |

`unknown` is deliberately not folded into `none`, because the two ways of being wrong are
not symmetric. A line counted as `none` counts in full, which is the safe direction for a
budget. One counted as `only` can be excluded from a group, so an unfamiliar file extension
would silently zero out a large change. Everything that cannot be classified therefore
counts as code, and the run says how much of that there was.

Comment state is a property of the **file**, not of the line. A `+` line inside an open
block comment cannot be recognised from the hunk it arrived in, and the `-U0` patch carries
no context at all. So the whole image is fetched and lexed once, and the counted lines index
the result by their line numbers: a `+` line reads the post-image, a `-` line the
pre-image, and a rename reads its pre-image under the old path.

Lexing is [pygments](https://pygments.org). A regex cannot do this job. `^\s*#` fires on
shebangs, on `#include`, on markdown headings, on heredoc bodies and on `color = "#000000"`,
and it misses every continuation line of a block comment and every language whose comment
token is not `#`. A gate that silently undercounts is worse than one that declines to
classify.

Two token types pygments files under `Token.Comment` are **not** comments here, because no
reviewer would call them commentary: `Comment.Preproc`, where `#include <stdio.h>` lands,
and `Comment.Hashbang`, the interpreter a file runs under. Both are functional lines and
both count as code.

A blank line inside a block comment belongs to the comment. A blank line anywhere else is
`none`.

`docstrings_as_comments` decides whether a docstring is a comment. It defaults to `true`,
and switches on `Token.Literal.String.Doc`, which pygments tags distinctly from
`Token.Comment` — so it is a clean switch rather than a heuristic, and it applies to every
language whose lexer emits that token, not only to Python.

Lexing runs only when some rule in the configuration uses the `comment` facet. When none
does, no blob is read and no line is classified, and the facet has nothing to answer with.

### When a line cannot be classified

Each of these classifies `unknown` and is counted in its own diagnostic, so that a missing
language profile is noticed deliberately rather than through a change that sailed past a
gate because nothing could read it:

| | |
|---|---|
| pygments is not installed | a warning naming it goes to standard error, and the run continues |
| No lexer knows the file | `unknown_lexer_files` |
| The blob is over 1 MiB | `oversize_skipped_files` |

pygments is an optional dependency. Its absence is not a failure to measure: every line
classifies `unknown`, every one of them counts, and the exit code is unchanged.

### The blob cache

A blob's name is its content, so a classification of one is valid forever. Lexed images are
cached under `diff_census/` in the repository's **common** git directory — the one
`git rev-parse --git-common-dir` names, not `.git`, which in a linked worktree is a file
rather than a directory. One cache therefore serves every worktree of a repository.

The cache key covers the blob name, the pygments version, the `docstrings_as_comments`
setting and the lexer, so an upgrade, a configuration change, or the same bytes under a
different filename each invalidate cleanly rather than being answered from a stale entry.

`--no-cache` neither reads nor writes it, and produces the same classification. A cache that
cannot be read or written is treated as one that is not there: nothing about it can turn a
measurement into a failure to measure.

### `--jobs`

Lexing is CPU-bound and shares nothing between files, so `--jobs N` will do it over a
process pool. It **defaults to 1** and should usually stay there: a worker costs more to
start than an ordinary pull request's worth of lexing costs to do, and a warm cache lexes
nothing at all. On a first run over a very large range it is worth a factor of about 1.5
at four workers, with little past that. A pool the platform will not give is a warning in
the diagnostics, not a failure: the run lexes serially instead.

## Where the configuration comes from

First hit wins:

1. `--config PATH`
2. `$STACKED_PLANNING_CONFIG`
3. `.agents/plugins/stacked-planning/config.toml`, relative to the git toplevel

The third is a repository path rather than one in the home directory, which is what makes
a checkout carry its own policy. `config.example.toml`, next to this file, is a starting
point for it. Resolution is rooted at the toplevel, so the answer does not change
with the directory the script runs from.

A path named explicitly — by `--config` or by the environment — that is not a readable
file is an error. The repository path is discovered rather than named, so its absence is
not: with no file at all the built-in global exclusions apply, and there are no matchers
and no groups.

The file is shared with the plugin's other tools, one top-level table per tool.
`diff_census.py` reads `[diff_census]` and skips every sibling table, so another tool's
table is left alone rather than rejected as an unknown key. A file with no `[diff_census]`
table is a file with no configuration for this tool, and the defaults apply.

**Every configuration problem exits 2**, and the message names the offending key by its
full path as the file spells it:

```
diff-census: config: config.toml: diff_census.groups.g: a group needs `limit`
  a bucket that needs no budget is a matcher with `report = true`, not a group
```

The first line is the source, the key and the problem; where there is something useful to
say beyond naming the fault, a second indented line says it.

Exit 1 is reserved for a bucket over its limit, so a broken configuration never reads as
a measurement.

## The three kinds of object

| Object | Purpose | Produces a bucket | Carries a limit |
|---|---|---|---|
| **Global exclusion** | Lines that are not review surface at all | `exempt` | No |
| **Matcher** | A named, reusable definition | Only with `report = true` | No |
| **Group** | A budgeted category of change | Yes | Required |

Keeping them distinct is the structural idea. A matcher is a *definition* — what counts as
generated code. A group is a *budget* — production code stays under 400 lines. Groups
reach definitions through the `matches` facet, which is how `production` is expressed as
source directories minus generated, tests and docs without restating any of them.

A bucket that needs no budget is a matcher with `report = true`, not a group. A group
without `limit` is rejected, and the error says so.

## Buckets

Every changed line lands in exactly one of `exempt` and `total`.

| Bucket | Holds |
|---|---|
| `exempt` | lines a global exclusion rule caught, broken down by which rule caught them |
| `total` | everything else — the denominator all group accounting is against |
| a group, a reported matcher | a subset of `total`; a line may belong to none, one or several |
| `unmatched` | lines in `total` that no group and no reported matcher claimed |

Group memberships need not sum to `total`, and under `multi` they may sum past it. The
grand total is `total` plus `exempt`; it is deliberately not reported as a field of its
own, so there is one obvious way to read each number rather than two that can disagree.

`unmatched` is the coverage metric. It grows when the configuration has stopped describing
the repository, and a limit on it turns that into a gate.

## The classification pipeline

Per counted line, in order:

1. **Global exclusion**, and it is **terminal**. A line that matches is charged to
   `exempt`, attributed to the rule that caught it, and stops there.
2. `total`.
3. Every **reported matcher**, always in full. Matchers are observational rather than
   budgeted, so the overlap policy does not apply to them.
4. Every **group**, subject to the overlap policy.
5. `unmatched`, if nothing claimed the line.

Terminal means terminal: an excluded line is invisible to every matcher and every group,
and nothing rescues it. That is what makes `total` and `exempt` a genuine partition of the
diff, keeps classification a single forward pass with no back-references, and lets
`--explain` print one linear story per line. The composition a rescue mechanism would
serve is what matchers are for.

`overlap` decides how a line belonging to several groups is charged. `multi`, the default,
charges every group it matches. `first_match_wins` charges the first matching group in
**declaration order in the file**, which the loader preserves; the line is claimed either
way, so `unmatched` reads the same under both.

## Keys

```toml
[diff_census]
version = 1                      # required, must be 1
overlap = "multi"                # "multi" (default) or "first_match_wins"
docstrings_as_comments = true    # default true

[diff_census.global]
extend_builtin = true            # false replaces the built-in list rather than adding to it
exclude = [ … ]                  # a rule list

[diff_census.matchers.<name>]
report = false                   # true puts the matcher in the output as a bucket
rules = [ … ]                    # a rule list, required

[diff_census.groups.<name>]
limit = { changed = 400, grace = 0.10 }   # required
include = [ … ]                  # a rule list; omitted means match-all
exclude = [ … ]                  # a rule list

[diff_census.limits]
total = { changed = 1200, grace = 0.10 }  # a budget on the denominator
unmatched = { changed = 50 }              # a budget on config coverage
```

`overlap` decides how a line belonging to several groups is charged. `multi` charges every
group it matches, so group counts may sum to more than the total. `first_match_wins`
charges the first matching group in **declaration order in the file**, which the loader
preserves.

A `limit` names any of `added`, `deleted` and `changed`, where `changed` is added plus
deleted, and every metric named must pass. `grace` is a fraction in `[0, 1)`, defaulting to
`0.0`; the hard threshold for a limit `L` is `L * (1 + grace)`. The grace band warns rather
than moving the limit.

`[diff_census.limits]` budgets `total`, the denominator every group is a subset of, and
`unmatched`, the part of it no group and no reported matcher claimed. Groups carry their own
limits, and `exempt` is by definition not review surface, so neither is budgeted here.

A limit on `unmatched` turns configuration coverage into a gate. `unmatched` grows when the
configuration has stopped describing the repository — a new directory no rule mentions, a
language nobody added a matcher for — and without a budget that is visible only to someone
reading the report. Budgeting it makes the configuration fail when it goes stale rather than
quietly measuring less and less of the change.

## Rules and facets

A **rule** is a table of facets. A **rule list** is an array of rules.

- Facets **AND** within a rule: `{ path = ["src/**"], ext = ["py"] }` requires both.
- Values **OR** within a facet: `path = ["src/**", "lib/**"]` is either.
- Rules **OR** across a list: each entry is an alternative.

That is disjunctive normal form. There is no `not` operator — `exclude` is what negation
is for:

```
member(line, group) := matches_any(group.include) AND NOT matches_any(group.exclude)
```

`include` omitted means match-all, which makes an exclusion-only group the degenerate case
of the same mechanism rather than a special form.

Rule lists are arrays. Inline tables keep them readable at this nesting depth, and the
array-of-tables form is equivalent for rules too long for one line:

```toml
[[diff_census.groups.production.include]]
path = ["src/**", "lib/**"]
```

The two styles cannot be mixed for the same key.

| Facet | Matches on | Notes |
|---|---|---|
| `path` | glob | repo-relative, no leading slash |
| `path_regex` | regex | full repo-relative path |
| `dir` | glob | dirname only |
| `name` | glob | basename only |
| `name_regex` | regex | basename only |
| `ext` | exact, case-folded | no leading dot; `""` matches a file with no extension |
| `mime` | exact or `type/*` | `"text/x-python"`, `"image/*"` |
| `size` | comparison | `"> 1MiB"`, `"<= 4096"` |
| `mode` | exact octal | `100644`, `100755`, `120000`, `160000` |
| `content` | regex | line text, leading `+`/`-` stripped |
| `change` | `add`, `del` | |
| `comment` | `only`, `trailing`, `none`, `unknown` | |
| `matches` | matcher names | |

Every facet accepts a scalar or an array; a scalar is a one-element array.

**Globs** are gitwildmatch — gitignore semantics, via `pathspec`. `*` does not cross a
directory separator and `**` does, and character classes such as `*.[ch]` are available. A
pattern gitignore would read as a comment or a negation (a leading `#` or `!`) is rejected
rather than silently matching nothing.

**Regexes** are Python `re` syntax, compiled when the configuration loads, so an unusable
pattern is a load error rather than a surprise partway through a run. They **search**
rather than anchor: `src/` matches anywhere in the value, and `^src/` is how to say the
value begins with it.

### What each facet matches

`path`, `path_regex` — the whole repository-relative path, with no leading slash.

`dir` — the dirname alone. A file at the repository root has none, so it matches no `dir`
pattern; reach those with `path` or `name`.

`name`, `name_regex` — the basename alone, so a pattern for it never has to account for
the directories above it.

`ext` — the extension, case-folded and without its dot, so `a.PY` has extension `py`. `""`
matches a file with no extension at all, which covers a dotfile such as `.gitignore` as
well as a name such as `Makefile`. A configured value written with its dot means the same
as one written without.

`mime` — the type derived from the path, either exactly or as a `type/*` wildcard. It is
derived, never sniffed: no file is read to answer it. The script's own table covers the
source extensions Python's map is silent or wrong about, and Python's map supplies the
rest; a path nothing can name reports `application/octet-stream`.

`size` — `<op><number><unit?>`, where the operator is one of `< <= > >= == !=` and the
unit is one of `B`, `KiB`, `MiB`, `GiB`, case-insensitive. A bare number is bytes. A file
of unknown size — a submodule, or a working-tree file that cannot be read — matches no
comparison.

`mode` — the git file mode as an exact octal string. A file of unknown mode matches none.

`content` — a regex over the text of one line, its leading `+` or `-` already stripped.
It is applied to the raw bytes rather than to decoded text, so `\w`, `\s` and `\b` carry
their ASCII meanings.

`change` — which side of the diff the line is on, `add` or `del`.

`comment` — the line's comment state: `only`, `trailing`, `none` or `unknown`. Read off the
whole file rather than the line, and only when some rule asks for it. See **Comment
detection**.

`matches` — an ordinary facet naming matchers. It ANDs with its siblings and ORs across
its own list, so `{ matches = ["generated"], dir = ["src/api/**"] }` is generated files
under one directory. Matchers may reference other matchers to any depth.

### File facts and line facts

`path`, `path_regex`, `dir`, `name`, `name_regex`, `ext`, `mime`, `size` and `mode` are
answerable from a file. `content`, `change` and `comment` need the line itself.

A line fact that has not been supplied is unanswerable rather than false, and every facet
needing it reports no match. That keeps the algebra two-valued, so `exclude` beating
`include` stays unambiguous, and it puts the error in the safe direction for a budget: a
rule that cannot be answered does not fire, so an unanswerable `exclude` leaves the line
inside its group and an unanswerable `include` leaves it outside. Nothing is quietly
dropped from a count on the strength of something nobody measured.

## Built-in global exclusions

Applied unless `[diff_census.global]` sets `extend_builtin = false`, in which case the
file's own `exclude` rules are the whole list:

```
**/*.lock  **/package-lock.json  **/yarn.lock  **/pnpm-lock.yaml
**/Cargo.lock  **/poetry.lock  **/go.sum  **/composer.lock
**/vendor/**  **/node_modules/**  **/.venv/**  **/venv/**
**/*.min.js  **/*.min.css  **/*.map
**/__snapshots__/**  **/*.snap
**/.git/**
```

The list is deliberately conservative: it covers files nobody reviews under any policy.
Generated code, tests and documentation are not here. Those are review surfaces whose
treatment is a per-repository decision, so they belong to groups and matchers, where they
still count toward the total.

## What the loader rejects

Each of these exits 2 with a message naming the key:

- An unknown top-level key, an unknown key inside a matcher, group, limit or
  `[diff_census.global]`, and an unknown facet name.
- `version` absent, or any value other than `1`.
- `overlap` other than `multi` or `first_match_wins`.
- A group without `limit`. The message points at `report = true` on a matcher as the way
  to get a bucket that needs no budget.
- A group or matcher named `total`, `exempt`, `unmatched`, `global` or `limits`, which the
  census uses for its own buckets.
- One name used for both a group and a matcher.
- A limit with no metric, or a metric other than `added`, `deleted` or `changed`.
- `grace` outside `[0, 1)`.
- An invalid regex, an invalid glob, a malformed `size` comparison, a `mode` that is not a
  git file mode, a `change` or `comment` outside its value set.
- `matches` naming a matcher that is not defined, or a reference cycle — the message names
  the cycle, as `a -> b -> c -> a`.

A value inside a facet is named by its index, so `path[2]` is the third pattern in that
list rather than the whole rule.

## What the loader warns about

A warning goes to standard error and the load continues. Nothing here changes an exit
code.

**A group no line can match.** When every one of a group's `include` rules is covered by
one of its `exclude` rules, the group is dead configuration, and the warning names it.

The analysis is deliberately narrow, so that it fires on a real mistake rather than on a
configuration that is merely hard to read. An `exclude` rule covers an `include` rule when
it constrains only facets the `include` rule constrains too, with a value list that covers
the `include` rule's — values compared as written, with no reasoning about whether two
different globs happen to overlap. Only file-level facets count: an `exclude` rule
carrying `content`, `comment`, `change` or `matches` may be false for reasons this cannot
see, so it is not treated as covering anything.

## The report

`--format json`, the default, is the machine-readable one:

```json
{
  "schema_version": 1,
  "refs": { "base": "main", "head": "HEAD", "merge_base": "a1b2c3d", "mode": "three-dot" },
  "groups": {
    "production": {
      "adds": 1200, "dels": 34, "changed": 1234, "files": 18,
      "limit": { "metric": "changed", "value": 400, "grace": 0.10, "hard": 440 },
      "status": "over"
    }
  },
  "matchers": { "tests": { "adds": 210, "dels": 12, "changed": 222, "files": 7 } },
  "totals": {
    "total":     { "adds": 1291, "dels": 34, "changed": 1325, "files": 22 },
    "unmatched": { "adds": 50, "dels": 0, "changed": 50, "files": 1 },
    "exempt": {
      "adds": 881, "dels": 113, "changed": 994, "files": 9,
      "by_rule": { "global[1]": { "adds": 261, "dels": 109, "changed": 370 } }
    }
  },
  "diagnostics": {
    "binary_files": 2, "submodule_changes": 0, "unknown_lexer_files": 1,
    "oversize_skipped_files": 0, "files_read": 14, "blobs_lexed": 9,
    "cache_hits": 31, "elapsed_ms": 412, "warnings": []
  }
}
```

`files` counts the files contributing at least one line to that bucket, so a binary, a
gitlink, a mode flip and a bare rename count toward none of them.

`limit` and `status` appear **only** where a limit is configured, so their presence is the
signal that a bucket is budgeted at all. `status` is `ok`, `warn` or `over`, and takes the
worst of every metric the limit names. A limit naming one metric reports as the object
above; one naming several reports as a list of those objects, in the order `added`,
`deleted`, `changed`, since each is a budget that must pass on its own.

`by_rule` names the rule that caught each exempt line. The file's own rules are
`global[0]`, `global[1]` and so on, by their position in `[diff_census.global].exclude`;
the shipped list is `builtin`. A rule that caught nothing has no entry.

Every diagnostic has a real source. `warnings` carries what the configuration loader
warned about and the note that pygments is missing, both of which also go to standard
error.

`--format text` prints the same census as an aligned table of groups, then matchers, then
the census-wide buckets, with a diagnostics footer and a banner for any limit that is not
comfortable. It is for a person reading a gate failure in a CI log. **Nothing should parse
it** — that is what the schema is for.

## Gate mode and exit codes

| Code | Meaning |
|---|---|
| `0` | every limit satisfied, or inside its grace band, or reporting only |
| `1` | at least one limit past its grace band |
| `2` | the census could not be taken |

Gate mode is the default once the configuration defines at least one group. `--census`
forces reporting only, whatever the limits say; `--gate` forces enforcement.

**Gate mode with no groups defined exits 2.** This is checked when the gate runs rather
than when the configuration loads, because a configuration with matchers and no groups is
a perfectly good census — which is what the tool is named for. It is only as a gate that
it is broken, and a gate with nothing to enforce must not pass everything.

Exit 2 also covers a configuration named explicitly but absent, an invalid configuration,
a failed git invocation, an unresolvable merge base, and a run outside a repository.

**The grace band.** For a limit `L` with grace `g`, the hard threshold is `L * (1 + g)`.
Below `L` is `ok`. From `L` to the threshold inclusive is `warn`, reported prominently and
exiting 0. Above it is `over`, exiting 1. The band warns; it does not move the limit, so a
change that reaches `L` exactly is already saying so.

Every metric a limit names must pass, and every configured limit must pass.

## `--explain`

`--explain` traces how each file was classified; `--explain PATH` traces the one file. It
prints instead of the report, and the exit code is unchanged.

```
src/api/handlers.py  (+120 -8)
  facets:     ext=py mime=text/x-python mode=100644 size=8.2KiB
  global:     no match
  matchers:   comments <- rules[0] comment="only"  (12 lines)
  groups:     production  (112 lines counted)
                  include[0] path="src/**"  (120 lines)
                  exclude: no match
  counted:    total +120 -8 | comments +12 -0 | production +112 -8

vendor/lib/thing.go  (+620 -4)
  global:     EXEMPT <- global[1] path="**/vendor/**"  (624 lines)
```

A rule reading line text — `content`, `comment`, `change` — is true of some of a file's
lines and false of others, so it reports how many lines it matched rather than a verdict
for the file.

It names the rule, not only the outcome, because the rule is the thing that has to change.
This is the first thing to reach for when a number looks wrong.

## Example

```toml
[diff_census]
version = 1
overlap = "multi"

[diff_census.global]
exclude = [
  { content = '^\s*$' },
]

[diff_census.matchers.generated]
report = true
rules = [
  { content = '@generated|Code generated by' },
  { path = ["**/*.pb.go", "**/*_pb2.py", "**/migrations/**"] },
]

[diff_census.matchers.tests]
report = true
rules = [
  { path = ["tests/**", "**/*_test.py", "**/conftest.py"] },
]

[diff_census.matchers.docs]
report = true
rules = [
  { ext = ["md", "rst", "txt"] },
  { path = ["docs/**"] },
]

[diff_census.groups.production]
limit = { changed = 400, grace = 0.10 }
include = [{ path = ["src/**", "lib/**"] }]
exclude = [
  { matches = ["generated", "tests", "docs"] },
  { comment = ["only", "trailing"] },
]

[diff_census.limits]
total = { changed = 1200, grace = 0.10 }
```

## Tests

The suite is in the plugin's `tests/` directory. From the repository root:

```sh
uv run pytest plugins/stacked-planning
```
