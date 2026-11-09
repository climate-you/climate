# climate/tiles/zarr_tiles.py
"""Zarr v3 tile storage: one sharded array per metric.

Layout, under a metric's root (the directory that holds ``time/`` and, in the
old format, ``z64/``)::

    zarr/zarr.json            array metadata
    zarr/c/<t>/<r>/<c>        one shard file per tile x time block (series)
    zarr/c/<r>/<c>            one shard file per tile (scalar metrics)

The array is (time, lat, lon) for a series and (lat, lon) for a scalar metric,
on the metric's whole grid (no padding). A shard covers one 64 x 64 tile and
``shard_time`` steps; its inner chunks are (shard_time, 8, 8), so a single-cell
read decodes one small chunk per shard. Codecs, in order: an optional
numcodecs Delta, little-endian bytes, Blosc (zstd 9, bitshuffle); the shard
index sits at the end of the file with a crc32c.

Values are stored either as float32 or as int16/uint16 with CF-style
``scale_factor`` / ``add_offset`` attributes; the fill value stands for NaN.
Encoding refuses values it cannot represent rather than clipping them. As in
the old format, every tile is stored, an empty one included (an empty reef
shard is about 4 KB), so a missing shard means a missing tile, not one with no
data.

The packager writes with zarr-python. The API reads single cells through
``read_cell``, which reads this exact layout directly (shard index, one chunk)
and is several times faster than zarr-python per call — see the Stream D
numbers in docs/plans/wip/v3-master-plan.md.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import struct
import tempfile
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from numcodecs import blosc as _blosc

from climate.tiles.layout import GridSpec

ZARR_DIRNAME = "zarr"
INNER_CHUNK = 8
BLOSC_CLEVEL = 9

# Time steps per shard when the registry does not say otherwise: a year of
# days, a decade of months; anything else keeps its whole series in one shard.
DEFAULT_SHARD_TIME = {"daily": 366, "monthly": 120}

_FILL = {
    np.dtype("<f4"): float("nan"),
    np.dtype("<i2"): -32768,
    np.dtype("<u2"): 65535,
}
# Largest representable range once the fill value is reserved.
_RANGE = {
    np.dtype("<i2"): (-32767, 32767),
    np.dtype("<u2"): (0, 65534),
}
_EMPTY = 0xFFFFFFFFFFFFFFFF


def zarr_dir(metric_root: str | Path) -> Path:
    return Path(metric_root) / ZARR_DIRNAME


@dataclass(frozen=True)
class Encoding:
    """How a metric's values are stored."""

    dtype: np.dtype = np.dtype("<f4")
    scale: float = 1.0
    offset: float = 0.0
    delta: bool = False

    def __post_init__(self) -> None:
        dt = np.dtype(self.dtype).newbyteorder("<")
        if dt not in _FILL:
            raise ValueError(f"Unsupported storage dtype: {self.dtype}")
        object.__setattr__(self, "dtype", dt)
        if self.is_float and (self.scale != 1.0 or self.offset != 0.0):
            raise ValueError("float32 storage takes no scale/offset")
        if self.scale <= 0:
            raise ValueError(f"scale must be positive, got {self.scale}")

    @property
    def is_float(self) -> bool:
        return self.dtype.kind == "f"

    @property
    def fill_value(self) -> float | int:
        return _FILL[self.dtype]

    @classmethod
    def from_storage(cls, storage: dict[str, Any] | None) -> "Encoding":
        enc = (storage or {}).get("encoding") or {}
        return cls(
            dtype=np.dtype(enc.get("dtype", "float32")),
            scale=float(enc.get("scale", 1.0)),
            offset=float(enc.get("offset", 0.0)),
            delta=bool(enc.get("delta", False)),
        )

    def encode(self, values: np.ndarray, *, label: str = "") -> np.ndarray:
        """Float values (NaN = missing) -> stored dtype. Raises instead of clipping."""
        values = np.asarray(values)
        if self.is_float:
            return values.astype(self.dtype)
        finite = np.isfinite(values)
        x = np.where(finite, values, self.offset).astype(np.float64)
        q = np.round((x - self.offset) / self.scale)
        lo, hi = _RANGE[self.dtype]
        bad = finite & ((q < lo) | (q > hi))
        if bad.any():
            v = values[bad]
            raise ValueError(
                f"{label or 'values'}: {int(bad.sum())} value(s) outside what "
                f"{self.dtype.name} at step {self.scale} can hold "
                f"[{lo * self.scale + self.offset}, {hi * self.scale + self.offset}] "
                f"(min {float(v.min())}, max {float(v.max())}); refusing to clip"
            )
        return np.where(finite, q, self.fill_value).astype(self.dtype)

    def decode(self, stored: np.ndarray) -> np.ndarray:
        stored = np.asarray(stored)
        if self.is_float:
            return stored.astype(np.float32)
        out = stored.astype(np.float32) * np.float32(self.scale) + np.float32(
            self.offset
        )
        out[stored == self.fill_value] = np.nan
        return out

    def attributes(self) -> dict[str, float]:
        if self.is_float:
            return {}
        return {"scale_factor": self.scale, "add_offset": self.offset}


def shard_time_for(
    storage: dict[str, Any] | None, time_axis: str | None, ntime: int
) -> int:
    """Time steps per shard for a metric (registry override, else by axis)."""
    explicit = (storage or {}).get("shard_time")
    if explicit is not None:
        return max(1, int(explicit))
    default = DEFAULT_SHARD_TIME.get(str(time_axis or ""))
    return max(1, default if default is not None else ntime)


# ----------------------------------------------------------------------------
# Writing (zarr-python)
# ----------------------------------------------------------------------------


class ZarrTileWriter:
    """Writes a metric tile by tile, mirroring the old per-tile writer.

    ``write`` takes the same padded (tile, tile[, ntime]) arrays the old
    format's ``write_tile`` takes, and crops them to the grid. ``exists`` tells
    ``--resume`` which tiles are on disk; an empty tile still writes its shards.

    The packager writes a metric's batches from several processes. Each
    process opens its own writer: the first one creates the array, under a
    lock, and the others find it and open it. An existing array with the same
    layout is reused, so tiles outside a run's tile range survive, as they do
    in the old format; one with another layout is recreated, or refused under
    ``resume``.
    """

    def __init__(
        self,
        metric_root: str | Path,
        *,
        grid: GridSpec,
        ntime: int,
        encoding: Encoding,
        shard_time: int | None = None,
        resume: bool = False,
    ) -> None:
        import zarr

        self.grid = grid
        self.ntime = int(ntime)
        self.encoding = encoding
        self.path = zarr_dir(metric_root)
        ts = int(grid.tile_size)
        if ts % INNER_CHUNK:
            raise ValueError(f"tile size {ts} is not a multiple of {INNER_CHUNK}")
        st = max(1, int(shard_time or self.ntime or 1))
        self.shard_time = min(st, self.ntime) if self.ntime else 0

        if self.ntime:
            shape = (self.ntime, grid.nlat, grid.nlon)
            chunks = (self.shard_time, INNER_CHUNK, INNER_CHUNK)
            shards = (self.shard_time, ts, ts)
        else:
            shape = (grid.nlat, grid.nlon)
            chunks = (ts, ts)
            shards = (ts, ts)

        # Store every tile, an empty one included, so that a missing shard is an
        # error. zarr reads this setting when it opens the array, not when it
        # writes.
        with (
            _creation_lock(self.path),
            zarr.config.set({"array.write_empty_chunks": True}),
            warnings.catch_warnings(),
        ):
            # Delta is a numcodecs codec, outside the zarr v3 core spec; that is
            # deliberate (decision recorded in the Stream D plan).
            warnings.filterwarnings(
                "ignore", message="Numcodecs codecs are not in the Zarr"
            )
            existing = _existing_layout(self.path)
            wanted = _layout(shape, shards, chunks, encoding)
            if existing == wanted:
                self.array = zarr.open_array(str(self.path), mode="r+")
                return
            if existing is not None and resume:
                raise SystemExit(
                    f"{self.path}: existing array has layout {existing}, the run wants "
                    f"{wanted}; re-run without --resume so every tile is rewritten."
                )
            self.array = _create(self.path, shape, shards, chunks, encoding)

    def _shard_paths(self, tile_r: int, tile_c: int) -> list[Path]:
        if not self.ntime:
            return [self.path / "c" / str(tile_r) / str(tile_c)]
        n = -(-self.ntime // self.shard_time)
        return [self.path / "c" / str(k) / str(tile_r) / str(tile_c) for k in range(n)]

    def exists(self, tile_r: int, tile_c: int) -> bool:
        return all(p.exists() for p in self._shard_paths(tile_r, tile_c))

    def write(
        self,
        tile_r: int,
        tile_c: int,
        tile: np.ndarray,
        *,
        fill: float | int | None = None,
        label: str = "",
    ) -> None:
        """Write one padded tile. ``fill`` marks missing values when they are not NaN."""
        ts = int(self.grid.tile_size)
        r0, c0 = tile_r * ts, tile_c * ts
        h = min(ts, self.grid.nlat - r0)
        w = min(ts, self.grid.nlon - c0)
        tile = np.asarray(tile)
        if fill is not None and not np.isnan(fill):
            tile = np.where(tile == fill, np.nan, tile.astype(np.float64))
        if self.ntime:
            if tile.shape[2] != self.ntime:
                raise ValueError(
                    f"tile has {tile.shape[2]} steps, array has {self.ntime}"
                )
            enc = self.encoding.encode(tile[:h, :w, :], label=label)
            self.array[:, r0 : r0 + h, c0 : c0 + w] = np.transpose(enc, (2, 0, 1))
        else:
            self.array[r0 : r0 + h, c0 : c0 + w] = self.encoding.encode(
                tile[:h, :w], label=label
            )


def _layout(shape, shards, chunks, encoding: Encoding) -> dict[str, Any]:
    return {
        "shape": list(shape),
        "dtype": encoding.dtype.name,
        "shards": list(shards),
        "chunks": list(chunks),
        "delta": encoding.delta,
        "attributes": encoding.attributes(),
    }


def _existing_layout(path: Path) -> dict[str, Any] | None:
    meta_path = path / "zarr.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    try:
        sh = meta["codecs"][0]["configuration"]
        return {
            "shape": list(meta["shape"]),
            "dtype": np.dtype(meta["data_type"]).name,
            "shards": list(meta["chunk_grid"]["configuration"]["chunk_shape"]),
            "chunks": list(sh["chunk_shape"]),
            "delta": any(c["name"] == "numcodecs.delta" for c in sh["codecs"]),
            "attributes": {
                k: v
                for k, v in (meta.get("attributes") or {}).items()
                if k in ("scale_factor", "add_offset")
            },
        }
    except (KeyError, IndexError, TypeError):
        return {"unreadable": str(meta_path)}


def _create(path: Path, shape, shards, chunks, encoding: Encoding):
    import zarr
    from zarr.codecs import BloscCodec

    filters = []
    if encoding.delta:
        from numcodecs.zarr3 import Delta

        filters = [Delta(dtype=encoding.dtype.str)]
    return zarr.create_array(
        zarr.storage.LocalStore(str(path)),
        shape=shape,
        chunks=chunks,
        shards=shards,
        dtype=encoding.dtype,
        filters=filters,
        compressors=[
            BloscCodec(cname="zstd", clevel=BLOSC_CLEVEL, shuffle="bitshuffle")
        ],
        fill_value=encoding.fill_value,
        dimension_names=("time", "lat", "lon") if len(shape) == 3 else ("lat", "lon"),
        attributes=encoding.attributes(),
        overwrite=True,
    )


@contextmanager
def _creation_lock(path: Path) -> Iterator[None]:
    """Serialise array creation across the packager's worker processes.

    The lock file lives in the temp directory, not beside the array, so it is
    never published with the release.
    """
    key = hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:16]
    lock_path = Path(tempfile.gettempdir()) / f"climate-zarr-{key}.lock"
    with open(lock_path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def read_tile(
    metric_root: str | Path, tile_r: int, tile_c: int, *, tile_size: int = 64
) -> np.ndarray:
    """A whole tile, decoded, in the old format's shape and padding.

    (tile, tile, ntime) for a series, (tile, tile) for a scalar metric, NaN
    beyond the grid. For packager-side readers (maps, aggregates, coverage);
    uses zarr-python.
    """
    import zarr

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="Numcodecs codecs are not in the Zarr"
        )
        arr = zarr.open_array(str(zarr_dir(metric_root)), mode="r")
    enc = _encoding_from_attrs(np.dtype(arr.dtype), dict(arr.attrs))
    ts = int(tile_size)
    r0, c0 = tile_r * ts, tile_c * ts
    if arr.ndim == 3:
        block = np.transpose(np.asarray(arr[:, r0 : r0 + ts, c0 : c0 + ts]), (1, 2, 0))
        out = np.full((ts, ts, arr.shape[0]), np.nan, dtype=np.float32)
    else:
        block = np.asarray(arr[r0 : r0 + ts, c0 : c0 + ts])
        out = np.full((ts, ts), np.nan, dtype=np.float32)
    h, w = block.shape[0], block.shape[1]
    out[:h, :w, ...] = enc.decode(block)
    return out


def _encoding_from_attrs(
    dtype: np.dtype, attrs: dict[str, Any], delta: bool = False
) -> Encoding:
    return Encoding(
        dtype=dtype,
        scale=float(attrs.get("scale_factor", 1.0)),
        offset=float(attrs.get("add_offset", 0.0)),
        delta=delta,
    )


# ----------------------------------------------------------------------------
# Single-cell reader (no zarr-python)
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Meta:
    shape: tuple[int, ...]
    shard: tuple[int, ...]
    inner: tuple[int, ...]
    encoding: Encoding
    n_inner: int


@lru_cache(maxsize=1024)
def _meta(path: str, _mtime_ns: int) -> _Meta:
    meta = json.loads((Path(path) / "zarr.json").read_text(encoding="utf-8"))
    if meta.get("zarr_format") != 3 or meta.get("node_type") != "array":
        raise ValueError(f"{path}: not a zarr v3 array")
    codecs = meta["codecs"]
    if len(codecs) != 1 or codecs[0]["name"] != "sharding_indexed":
        raise ValueError(f"{path}: expected one sharding codec, got {codecs}")
    sh = codecs[0]["configuration"]
    names = [c["name"] for c in sh["codecs"]]
    if names not in (["bytes", "blosc"], ["numcodecs.delta", "bytes", "blosc"]):
        raise ValueError(f"{path}: unsupported inner codecs {names}")
    if (
        sh["codecs"][names.index("bytes")]["configuration"].get("endian", "little")
        != "little"
    ):
        raise ValueError(f"{path}: big-endian chunks are not supported")
    if sh.get("index_location", "end") != "end" or [
        c["name"] for c in sh["index_codecs"]
    ] != [
        "bytes",
        "crc32c",
    ]:
        raise ValueError(f"{path}: unsupported shard index layout")
    shard = tuple(meta["chunk_grid"]["configuration"]["chunk_shape"])
    inner = tuple(sh["chunk_shape"])
    if any(s % i for s, i in zip(shard, inner)):
        raise ValueError(f"{path}: inner chunks {inner} do not divide shards {shard}")
    dtype = np.dtype(meta["data_type"]).newbyteorder("<")
    enc = _encoding_from_attrs(
        dtype, meta.get("attributes") or {}, delta="numcodecs.delta" in names
    )
    fill = meta["fill_value"]
    if not (enc.is_float or fill == enc.fill_value):
        raise ValueError(f"{path}: fill value {fill} is not {enc.fill_value}")
    n_inner = 1
    for s, i in zip(shard, inner):
        n_inner *= s // i
    return _Meta(tuple(meta["shape"]), shard, inner, enc, n_inner)


def _read_chunk(path: Path, lin: int, n_inner: int) -> bytes | None:
    # Every tile is stored, so a missing shard raises FileNotFoundError.
    fd = os.open(path, os.O_RDONLY)
    try:
        size = os.fstat(fd).st_size
        off, nbytes = struct.unpack(
            "<QQ", os.pread(fd, 16, size - 4 - 16 * n_inner + 16 * lin)
        )
        if off == _EMPTY and nbytes == _EMPTY:
            return None
        return os.pread(fd, nbytes, off)
    finally:
        os.close(fd)


def read_cell(metric_root: str | Path, i_lat: int, i_lon: int) -> np.ndarray:
    """Full decoded series at one grid cell; shape (ntime,), or (1,) for a scalar metric.

    Missing data reads as NaN; a missing shard is a missing tile and raises
    FileNotFoundError.
    """
    path = zarr_dir(metric_root)
    m = _meta(str(path), (path / "zarr.json").stat().st_mtime_ns)
    enc = m.encoding
    if len(m.shape) == 2:
        nlat, nlon = m.shape
        T, st, ct = 1, 1, 1
        sy, sx = m.shard
        cy, cx = m.inner
    else:
        T, nlat, nlon = m.shape
        st, sy, sx = m.shard
        ct, cy, cx = m.inner
    if not (0 <= i_lat < nlat and 0 <= i_lon < nlon):
        raise IndexError(f"cell ({i_lat}, {i_lon}) outside {nlat} x {nlon}")
    ny, nx = sy // cy, sx // cx
    iy, ix = (i_lat % sy) // cy, (i_lon % sx) // cx
    sr, sc = i_lat // sy, i_lon // sx
    parts: list[np.ndarray] = []
    for k in range(-(-T // st)):
        shard_path = (
            path / "c" / str(sr) / str(sc)
            if len(m.shape) == 2
            else path / "c" / str(k) / str(sr) / str(sc)
        )
        for kt in range(st // ct):
            lin = (kt * ny + iy) * nx + ix
            buf = _read_chunk(shard_path, lin, m.n_inner)
            if buf is None:
                parts.append(np.full(ct, enc.fill_value, dtype=enc.dtype))
                continue
            flat = np.frombuffer(_blosc.decompress(buf), dtype=enc.dtype)
            if enc.delta:
                flat = np.cumsum(flat, dtype=enc.dtype)
            parts.append(flat.reshape(ct, cy, cx)[:, i_lat % cy, i_lon % cx])
    return enc.decode(np.concatenate(parts)[:T])
