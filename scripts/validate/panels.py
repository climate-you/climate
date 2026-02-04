#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

from climate.registry.panels import (
    DEFAULT_PANELS_PATH,
    DEFAULT_PANELS_SCHEMA_PATH,
    PanelsSchemaError,
    load_panels,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate registry/panels.json against schema")
    parser.add_argument("--panels", default=str(DEFAULT_PANELS_PATH))
    parser.add_argument("--schema", default=str(DEFAULT_PANELS_SCHEMA_PATH))
    args = parser.parse_args()

    try:
        load_panels(Path(args.panels), schema_path=Path(args.schema), validate=True)
    except PanelsSchemaError as exc:
        print(str(exc))
        return 1

    print(f"OK: {args.panels}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
