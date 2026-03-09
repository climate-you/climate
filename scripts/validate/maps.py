#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

from climate.registry.maps import (
    DEFAULT_MAPS_PATH,
    DEFAULT_MAPS_SCHEMA_PATH,
    MapsSchemaError,
    load_maps,
    validate_maps_against_metrics,
    validate_maps_mobile_output_requirements,
)
from climate.registry.layers import (
    DEFAULT_LAYERS_PATH,
    DEFAULT_LAYERS_SCHEMA_PATH,
    LayersSchemaError,
    load_layers,
)
from climate.registry.metrics import (
    DEFAULT_DATASETS_PATH,
    DEFAULT_DATASETS_SCHEMA_PATH,
    DEFAULT_METRICS_PATH,
    DEFAULT_SCHEMA_PATH,
    MetricsSchemaError,
    load_metrics,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate registry/maps.json against schema"
    )
    parser.add_argument("--maps", default=str(DEFAULT_MAPS_PATH))
    parser.add_argument("--schema", default=str(DEFAULT_MAPS_SCHEMA_PATH))
    parser.add_argument("--metrics", default=str(DEFAULT_METRICS_PATH))
    parser.add_argument("--metrics-schema", default=str(DEFAULT_SCHEMA_PATH))
    parser.add_argument("--datasets", default=str(DEFAULT_DATASETS_PATH))
    parser.add_argument("--datasets-schema", default=str(DEFAULT_DATASETS_SCHEMA_PATH))
    parser.add_argument("--layers", default=str(DEFAULT_LAYERS_PATH))
    parser.add_argument("--layers-schema", default=str(DEFAULT_LAYERS_SCHEMA_PATH))
    args = parser.parse_args()

    try:
        maps = load_maps(Path(args.maps), schema_path=Path(args.schema), validate=True)
        metrics = load_metrics(
            Path(args.metrics),
            schema_path=Path(args.metrics_schema),
            datasets_path=Path(args.datasets),
            datasets_schema_path=Path(args.datasets_schema),
            validate=True,
        )
        layers = load_layers(
            Path(args.layers),
            schema_path=Path(args.layers_schema),
            validate=True,
        )
        validate_maps_against_metrics(maps, metrics)
        validate_maps_mobile_output_requirements(
            maps_manifest=maps,
            metrics_manifest=metrics,
            layers_manifest=layers,
        )
    except MapsSchemaError as exc:
        print(str(exc))
        return 1
    except LayersSchemaError as exc:
        print(str(exc))
        return 1
    except MetricsSchemaError as exc:
        print(str(exc))
        return 1

    print(f"OK: {args.maps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
