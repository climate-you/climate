#!/usr/bin/env python
from __future__ import annotations

import subprocess
from pathlib import Path


def run(cmd: list[str]) -> int:
    result = subprocess.run(cmd)
    return int(result.returncode)


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    scripts_dir = root / "scripts" / "validate"

    commands = [
        ["python", str(scripts_dir / "metrics.py")],
        ["python", str(scripts_dir / "panels.py")],
    ]

    for cmd in commands:
        code = run(cmd)
        if code != 0:
            return code

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
