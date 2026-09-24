# stack_overlap.py — reference

A plan's independence claim — landing stack A and stack B in either order gives the same
result — is a judgement call until something checks it. `stack_overlap.py` is the check:
does this branch change a path another live stack owns? It earns its place because the
failure it catches surfaces *late*, both stacks several PRs deep, where the only recovery
is to park a stack and replant it.

```sh
python3 stack_overlap.py [base-ref] --stack <this stack's id> [--owns '<glob>' …]
```

Standard library only, reads only, every git call rooted at the toplevel, exit `0` clean
/ `1` overlap / `2` could not measure. It carries its own base chain and depends on
nothing but `python3` and `git`, so it keeps working wherever those do.

The base is the positional argument, else `$STACK_OVERLAP_BASE`, else this branch's parent
in a `gh stack`, else the base branch of its open PR, else the repository's default branch.
`gh` is consulted only after the local checks miss, so the common path costs no network.

## What `--owns` means

`--owns` takes the fence, not the territory: `--owns 'src/billing/**'` on stack A's branch
means "B owns this, stay out". The other reading — everything I changed must be inside my
own globs — is a worse check, firing on every unowned file a stack legitimately touches
(README, the plan artifact) while saying nothing about the peer it should protect.

## Glob semantics, and why not `fnmatch`

`fnmatch`'s `*` matches `/`, so `src/*.py` matches `src/a/b.py` and `**` means nothing in
particular. `template.md` promises gitignore-shaped globs, so each pattern is translated to
a regex implementing that instead:

- `*` — any run of characters inside one segment, never `/`. `?` — one character, never `/`.
- `**` **as a whole segment** — zero or more segments, or one or more when it ends the
  pattern: `src/**` matches `src/x` but not the file `src` itself.
- `**` inside a segment (`src/**.py`) — not special, degrading to a single `*`, which is
  what gitignore does with consecutive asterisks it considers invalid.

One rule on top of gitignore's: a pattern matching a directory matches everything under it,
so `src/billing` fences that tree and `src/*` reaches `src/a/b.py` by way of the directory
`src/a`. That over-matches deliberately. Over-matching costs a human one look at a diff;
under-matching is a false clean, the failure this gate exists to prevent, so every
divergence resolves in that direction.

## Why plan-parsing ranks last

Precedence for the fence is `--owns` → `$STACK_OWNS` → the plan, the same shape as the
base chain above. The first two are what the caller means *now*; the plan may be stale,
half-edited, or written before the stacks were settled. It ranks last for being the least
trustworthy input, not the most convenient one — and so it never degrades into a clean
verdict. Exit 2, never 0, for: no `### Stack` heading; a stack with no `Owns` field
(silence is not "owns nothing" — the template spells that `—`); two `Owns` fields in one
stack; an entry that is not a single backticked glob; more than one plan carrying stack
headings; and an empty fence after exclusion, meaning either no second stack is live or
every stack owns `—`.

Excluding the caller's own stack is not optional — without it every PR fails on its own
paths — so the script is **told** which stack that is: `--stack A`, else `$STACK_ID`. It
is never inferred from the branch name: branch names carry a phase, not a stack, and a
wrong guess excludes the wrong stack, which is a false clean.

## Known limits

- Measured against `HEAD`, not the working tree. The question this answers is what a
  reviewer is handed, so uncommitted work is deliberately out of scope. An empty diff warns
  rather than reading as clean.
- Every other stack in the plan counts as live. The ledger's `State` column could narrow
  that to `active` rows; it is not parsed, and the wider fence is the safe side.
- Character classes (`[abc]`) and leading-`!` negation are not implemented. `template.md`
  promises `*`, `**` and repo-relative paths, and no `Owns` field has wanted more. They are
  **rejected**, not read as literals: `Owns` globs are gitignore-shaped, so someone will
  eventually write `migrations/2026[01]*_billing_*.sql`, and matching that literally would
  quietly own nothing — a false clean, the one failure this gate exists to prevent. Exit 2
  names the pattern instead. A typo'd glob does still own nothing, which no glob matcher can
  detect; the difference is that a typo is not valid syntax somewhere else.
