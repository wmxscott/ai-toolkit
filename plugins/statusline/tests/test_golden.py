import subprocess
import sys
from pathlib import Path

GENERATOR = Path(__file__).resolve().parent / "gen_golden.py"


def test_golden_files_match_statusline_py():
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr + "run gen_golden.py to update them"
