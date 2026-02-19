#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

from climate.registry.layers import (
    DEFAULT_LAYERS_PATH,
    DEFAULT_LAYERS_SCHEMA_PATH,
    LayersSchemaError,
    load_layers,
    validate_layers_against_maps,
)
from climate.registry.maps import (
    DEFAULT_MAPS_PATH,
    DEFAULT_MAPS_SCHEMA_PATH,
    MapsSchemaError,
    load_maps,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate registry/layers.json against schema")
    parser.add_argument("--layers", default=str(DEFAULT_LAYERS_PATH))
    parser.add_argument("--schema", default=str(DEFAULT_LAYERS_SCHEMA_PATH))
    parser.add_argument("--maps", default=str(DEFAULT_MAPS_PATH))
    parser.add_argument("--maps-schema", default=str(DEFAULT_MAPS_SCHEMA_PATH))
    args = parser.parse_args()

    try:
        layers = load_layers(Path(args.layers), schema_path=Path(args.schema), validate=True)
        maps = load_maps(Path(args.maps), schema_path=Path(args.maps_schema), validate=True)
        validate_layers_against_maps(layers, maps)
    except LayersSchemaError as exc:
        print(str(exc))
        return 1
    except MapsSchemaError as exc:
        print(str(exc))
        return 1

    print(f"OK: {args.layers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
