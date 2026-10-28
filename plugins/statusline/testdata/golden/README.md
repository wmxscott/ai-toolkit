Golden output recorded from the retired Python statusline (`scripts/statusline.py`, version 1.x). The script is gone, so they are fixed fixtures now: change one only when the Go statusline's output is meant to change. `../constants.json` holds its palettes, icons and other constants, recorded at the same time.

Each `<case>.json` is a statusline input; `<case>.dark.txt` and `<case>.light.txt` are the exact
stdout of `render(input, theme)`. They were recorded with:

- now: 2026-01-01T12:00:00Z
- HOME: /home/user
- process working directory (inputs with no `workspace.current_dir` or `cwd`): /home/user/nowhere
- no git repository at any working directory (line 1 shows the path)
