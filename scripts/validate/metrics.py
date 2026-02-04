#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

from climate.registry.metrics import (
    DEFAULT_METRICS_PATH,
    DEFAULT_SCHEMA_PATH,
    MetricsSchemaError,
    load_metrics,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate registry/metrics.json against schema")
    parser.add_argument("--metrics", default=str(DEFAULT_METRICS_PATH))
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH))
    args = parser.parse_args()

    try:
        load_metrics(Path(args.metrics), schema_path=Path(args.schema), validate=True)
    except MetricsSchemaError as exc:
        print(str(exc))
        return 1

    print(f"OK: {args.metrics}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
