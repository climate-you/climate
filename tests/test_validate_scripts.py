from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_validate_all_script() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = "."

    result = subprocess.run(
        [sys.executable, "scripts/validate/all.py"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "validate/all.py failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
