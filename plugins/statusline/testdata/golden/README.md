Golden output of `scripts/statusline.py`, written by `tests/gen_golden.py`. Do not edit by hand.

Each `<case>.json` is a statusline input; `<case>.dark.txt` and `<case>.light.txt` are the exact
stdout of `render(input, theme)`. They were recorded with:

- now: 2026-01-01T12:00:00Z
- HOME: /home/user
- process working directory (inputs with no `workspace.current_dir` or `cwd`): /home/user/nowhere
- no git repository at any working directory (line 1 shows the path)
