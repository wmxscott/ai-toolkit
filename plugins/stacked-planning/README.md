# stacked-planning

> [!WARNING]
> **Experimental.** The skills, the plan format and the gates' configuration may still change in ways that break existing plans and configs. Expect rough edges, and review what the agent plans and lands before relying on it.

Plans and lands work that is too big for one pull request. The work is split into stacks of small PRs, each stack a linear chain, written down as a plan before the first PR. The agent then implements the plan one PR at a time, with every PR checked against a size gate and, when two stacks run at once, an overlap gate.

## Skills

| Skill | Use it when |
|---|---|
| `stacked-planning` | It's unclear whether to write a plan or carry out an existing one. Routes to one of the next two. |
| `authoring-stacked-plans` | Work is known to need more than one PR, a PR has passed the size cap and is still growing, or a stack is nearing a fourth PR with no plan. Writes `docs/plans/<base36>-slug.md` from the bundled template. |
| `implementing-stacked-plans` | A plan exists and you ask the agent to carry it out. The agent orchestrates one subagent per PR, each in its own worktree, and reviews and lands each PR before starting the next. |
| `landing-changes` | Any change: branch and worktree first, land through a PR, and wait for its checks to go green. |

## Install

Claude Code:

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install stacked-planning@ai-toolkit
```

Codex:

```sh
codex plugin marketplace add wmxscott/ai-toolkit
codex plugin add stacked-planning@ai-toolkit
```

Pi:

```sh
pi install git:github.com/wmxscott/ai-toolkit
```

OpenCode: add the repository to `opencode.json` and restart OpenCode. The key is `plugin` in OpenCode 1 and `plugins` in OpenCode 2.

```json
{
  "plugin": ["ai-toolkit@git+https://github.com/wmxscott/ai-toolkit.git"]
}
```

The Pi package and the OpenCode plugin bring in every ai-toolkit plugin that supports that agent, which are those ticked in the [main README](../../README.md#plugins). The Pi package also brings in the [Pi extensions](../../README.md#pi-extensions); the main README shows how to filter them out.

## Requirements

- `git` and [`gh`](https://cli.github.com/), for branches, worktrees and pull requests.
- [`uv`](https://docs.astral.sh/uv/), to run the size gate. It declares its dependencies (`pathspec`, `pygments`) inline and `uv` installs them on first run.
- `python3` 3.8 or later, for the overlap gate. It needs nothing else.

Optional:

- [gh-stack](https://github.com/github/gh-stack) (`gh extension install github/gh-stack`) links each stack's PRs on GitHub and replants a child after its parent merges. Without it, the agent opens each PR against its parent branch and replants by hand.
- [herdr-wkt](https://github.com/wmxscott/herdr-wkt) (`brew install wmxscott/tap/herdr-wkt`) provides `wkt`, which creates worktrees for Herdr. Without it, the agent uses `git worktree add`.

## The gates

Both scripts live in `skills/authoring-stacked-plans/scripts/`, each with a reference beside it.

**Size gate**, `diff_census.py` ([reference](skills/authoring-stacked-plans/scripts/DIFF_CENSUS.md)). Counts the lines a branch adds and removes, sorts them into buckets, and fails a PR over its budget. Exit `0` pass or warn, `1` over, `2` couldn't measure.

```sh
uv run --script skills/authoring-stacked-plans/scripts/diff_census.py --base origin/<parent> --format text
```

**Overlap gate**, `stack_overlap.py` ([reference](skills/authoring-stacked-plans/scripts/STACK_OVERLAP.md)). Reads each stack's `Owns` globs from the plan and fails a branch that changes a path another stack owns. Exit `0` clean, `1` overlap, `2` couldn't measure.

```sh
python3 skills/authoring-stacked-plans/scripts/stack_overlap.py origin/<base> --stack A
```

Either can run as a pre-push hook or a CI check.

### Configuring the size gate

The budgets are configuration, not code. `diff_census.py` reads the first of:

1. `--config PATH`
2. `$STACKED_PLANNING_CONFIG`
3. `.agents/plugins/stacked-planning/config.toml` at the repository's toplevel

To adopt the default policy, copy [`config.example.toml`](skills/authoring-stacked-plans/scripts/config.example.toml) to that path and commit it: 400 production lines and 1200 in all, additions plus deletions, each with a 10% grace band that warns before it fails. Tests, the plan and comments are outside the production budget. Lockfiles, generated code, build output and general documentation are exempt from both. With no configuration, the script only counts and never fails, so the skills fall back to the example when a repository has none.

`--print-config` shows the configuration in force and `--explain PATH` shows how a file was classified.

## Agent support

All four agents load the same `skills/` directory:

| Agent | Loaded through |
|---|---|
| Claude Code | `.claude-plugin/plugin.json` |
| Codex | `plugin.json` ([Agent Plugins](https://agent-plugins.org) format) |
| Pi | the repository's root `package.json`, `pi.skills` |
| OpenCode | the repository's root plugin, `.opencode/plugins/ai-toolkit.js`, which adds this `skills/` directory to `skills.paths` in OpenCode 1 and registers each skill through `ctx.skill.transform` in OpenCode 2 |

The skills find their bundled files relative to their own directory, which each agent reports when it loads a skill, not through an agent-specific variable such as `${CLAUDE_PLUGIN_ROOT}`. The gate scripts live in `authoring-stacked-plans`, and `implementing-stacked-plans` reaches them as `../authoring-stacked-plans/scripts`, so install the skills together.

## Design

[`docs/diff-census-design.md`](docs/diff-census-design.md) is the design the size gate was built from. Where it and the reference differ, the reference describes the script as built.
