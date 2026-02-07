#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

from climate.registry.panels import (
    DEFAULT_PANELS_PATH,
    DEFAULT_PANELS_SCHEMA_PATH,
    PanelsSchemaError,
    load_panels,
    validate_panels_against_metrics,
)
from climate.registry.metrics import (
    DEFAULT_METRICS_PATH,
    DEFAULT_SCHEMA_PATH,
    DEFAULT_DATASETS_PATH,
    DEFAULT_DATASETS_SCHEMA_PATH,
    load_metrics,
    MetricsSchemaError,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate registry/panels.json against schema")
    parser.add_argument("--panels", default=str(DEFAULT_PANELS_PATH))
    parser.add_argument("--schema", default=str(DEFAULT_PANELS_SCHEMA_PATH))
    parser.add_argument("--metrics", default=str(DEFAULT_METRICS_PATH))
    parser.add_argument("--metrics-schema", default=str(DEFAULT_SCHEMA_PATH))
    parser.add_argument("--datasets", default=str(DEFAULT_DATASETS_PATH))
    parser.add_argument("--datasets-schema", default=str(DEFAULT_DATASETS_SCHEMA_PATH))
    args = parser.parse_args()

    try:
        panels = load_panels(Path(args.panels), schema_path=Path(args.schema), validate=True)
        metrics = load_metrics(
            Path(args.metrics),
            schema_path=Path(args.metrics_schema),
            datasets_path=Path(args.datasets),
            datasets_schema_path=Path(args.datasets_schema),
            validate=True,
        )
        validate_panels_against_metrics(panels, metrics)
    except PanelsSchemaError as exc:
        print(str(exc))
        return 1
    except MetricsSchemaError as exc:
        print(str(exc))
        return 1

    print(f"OK: {args.panels}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
