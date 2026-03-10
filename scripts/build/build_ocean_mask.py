#!/usr/bin/env python3
"""
Build a global ocean mask raster for fast ocean-name lookup in the API.

Output files:
  - NPZ mask with:
      data: 2D int array (0=land, >0=ocean_id)
      deg: cell size in degrees
      lat_max: northern bound (typically 90.0)
      lon_min: western bound (typically -180.0)
  - JSON name map:
      {"1": "Pacific Ocean", "2": "Atlantic Ocean", ...}

Input data should be ocean polygons (GeoJSON/Shapefile/etc.).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import urllib.request

import numpy as np

from climate.geo.marine import (
    NATURAL_EARTH_MARINE_POLYS_FALLBACK_URLS,
    normalize_marine_name,
)


def _load_ocean_shapes(
    input_path: Path | str,
    *,
    name_field: str,
    id_field: str | None,
) -> tuple[list[tuple[dict, int]], dict[int, str]]:
    try:
        import fiona
    except Exception as exc:
        raise RuntimeError(
            "fiona is required to read vector files. Install with: pip install fiona"
        ) from exc

    shapes: list[tuple[dict, int]] = []
    id_to_name: dict[int, str] = {}
    name_to_id: dict[str, int] = {}
    next_id = 1

    with fiona.open(str(input_path), "r") as src:
        for feat in src:
            geom = feat.get("geometry")
            if not geom:
                continue

            props = feat.get("properties") or {}
            name = normalize_marine_name(str(props.get(name_field) or "").strip())
            if not name:
                continue

            if id_field:
                raw_id = props.get(id_field)
                if raw_id is None:
                    continue
                try:
                    ocean_id = int(raw_id)
                except Exception:
                    continue
            else:
                # Stable assignment by first appearance of each name.
                ocean_id = name_to_id.get(name)
                if ocean_id is None:
                    ocean_id = next_id
                    next_id += 1
                    name_to_id[name] = ocean_id

            shapes.append((geom, ocean_id))
            if ocean_id not in id_to_name:
                id_to_name[ocean_id] = name

    if not shapes:
        raise RuntimeError(
            f"No ocean shapes loaded from {input_path}. "
            f"Check --name-field and optional --id-field."
        )

    return shapes, id_to_name


def _download_file(url: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        tmp.write_bytes(resp.read())
    tmp.replace(out_path)
    return out_path


def _prepare_input(
    *,
    input_path: Path | None,
    source: str,
    cache_dir: Path,
) -> Path:
    if input_path is not None:
        return Path(input_path)

    if source != "natural_earth":
        raise ValueError("When --input is omitted, --source must be natural_earth.")

    zip_path = cache_dir / "ne_10m_geography_marine_polys.zip"
    if not zip_path.exists() or zip_path.stat().st_size == 0:
        last_err = None
        for url in NATURAL_EARTH_MARINE_POLYS_FALLBACK_URLS:
            try:
                print(f"[download] {url} -> {zip_path}")
                _download_file(url, zip_path)
                last_err = None
                break
            except Exception as exc:
                last_err = exc
        if last_err is not None:
            raise RuntimeError(
                "Failed to download Natural Earth marine polygons from all sources."
            ) from last_err
    return zip_path


def build_mask(
    *,
    input_path: Path,
    output_npz: Path,
    output_names_json: Path,
    deg: float,
    name_field: str,
    id_field: str | None,
    lat_max: float = 90.0,
    lon_min: float = -180.0,
) -> None:
    try:
        from rasterio.features import rasterize
        from rasterio.transform import from_origin
    except Exception as exc:
        raise RuntimeError(
            "rasterio is required to rasterize polygons. "
            "Install with: pip install rasterio"
        ) from exc

    if deg <= 0:
        raise ValueError("--deg must be > 0.")

    input_resolved = Path(input_path)
    if input_resolved.suffix.lower() == ".zip":
        # fiona reads zipped datasets via the zip:// virtual filesystem.
        read_path: Path | str = f"zip://{input_resolved}"
    else:
        read_path = input_resolved

    shapes, id_to_name = _load_ocean_shapes(
        read_path,
        name_field=name_field,
        id_field=id_field,
    )

    nlat = int(round((2.0 * lat_max) / deg))
    nlon = int(round(360.0 / deg))
    transform = from_origin(lon_min, lat_max, deg, deg)

    mask = rasterize(
        shapes=shapes,
        out_shape=(nlat, nlon),
        transform=transform,
        fill=0,
        dtype="int32",
        all_touched=False,
    )

    output_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_npz,
        data=mask.astype(np.int32, copy=False),
        deg=np.float64(deg),
        lat_max=np.float64(lat_max),
        lon_min=np.float64(lon_min),
    )

    output_names_json.parent.mkdir(parents=True, exist_ok=True)
    names_payload = {str(k): v for k, v in sorted(id_to_name.items())}
    output_names_json.write_text(
        json.dumps(names_payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"[ok] wrote mask: {output_npz} shape={mask.shape} deg={deg}")
    print(f"[ok] wrote names: {output_names_json} oceans={len(id_to_name)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Input ocean polygons (GeoJSON/Shapefile/zip). If omitted, Natural Earth is downloaded.",
    )
    ap.add_argument(
        "--source",
        type=str,
        default="natural_earth",
        choices=["natural_earth"],
        help='Built-in source to download when --input is omitted (default: "natural_earth").',
    )
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache/geodata"),
        help='Download cache directory (default: "data/cache/geodata").',
    )
    ap.add_argument(
        "--output-npz",
        type=Path,
        default=Path("data/locations/ocean_mask.npz"),
        help='Output NPZ path (default: "data/locations/ocean_mask.npz").',
    )
    ap.add_argument(
        "--output-names",
        type=Path,
        default=Path("data/locations/ocean_names.json"),
        help='Output ocean names JSON (default: "data/locations/ocean_names.json").',
    )
    ap.add_argument(
        "--deg",
        type=float,
        default=0.25,
        help="Grid resolution in degrees (default: 0.25).",
    )
    ap.add_argument(
        "--name-field",
        type=str,
        default="name",
        help='Property field for ocean name (default: "name").',
    )
    ap.add_argument(
        "--id-field",
        type=str,
        default=None,
        help="Optional property field for stable ocean id. If omitted, ids are assigned by encountered names.",
    )
    args = ap.parse_args()

    input_path = _prepare_input(
        input_path=args.input,
        source=args.source,
        cache_dir=args.cache_dir,
    )

    build_mask(
        input_path=input_path,
        output_npz=args.output_npz,
        output_names_json=args.output_names,
        deg=float(args.deg),
        name_field=args.name_field,
        id_field=args.id_field,
    )


if __name__ == "__main__":
    main()
