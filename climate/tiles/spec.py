# climate/tiles/spec.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import struct

import zstandard as zstd


MAGIC = b"CLMTILE\0"  # 8 bytes
HEADER_SIZE = 32
VERSION = 1

# dtype codes (little-endian on disk)
DT_F32 = 1
DT_U16 = 2
DT_I16 = 3
DT_U8 = 4
DT_I8 = 5
DT_U32 = 6
DT_I32 = 7

_DTYPE_CODE_TO_NP = {
    DT_F32: np.dtype("<f4"),
    DT_U16: np.dtype("<u2"),
    DT_I16: np.dtype("<i2"),
    DT_U8: np.dtype("<u1"),
    DT_I8: np.dtype("<i1"),
    DT_U32: np.dtype("<u4"),
    DT_I32: np.dtype("<i4"),
}
_NP_TO_DTYPE_CODE = {v: k for k, v in _DTYPE_CODE_TO_NP.items()}

# Header layout (32 bytes total):
# 0..7   magic (8s)
# 8..9   version (uint16)
# 10     dtype_code (uint8)
# 11     reserved0 (uint8)
# 12..13 nyears (uint16)  (0 => scalar per cell)
# 14..15 tile_h (uint16)
# 16..17 tile_w (uint16)
# 18..31 reserved/padding (14 bytes)
_HDR_STRUCT = struct.Struct("<8sHBBHHH14x")


@dataclass(frozen=True)
class TileHeader:
    version: int
    dtype_code: int
    nyears: int
    tile_h: int
    tile_w: int

    @property
    def dtype(self) -> np.dtype:
        if self.dtype_code not in _DTYPE_CODE_TO_NP:
            raise ValueError(f"Unknown dtype_code={self.dtype_code}")
        return _DTYPE_CODE_TO_NP[self.dtype_code]

    @property
    def ncell(self) -> int:
        return int(self.tile_h) * int(self.tile_w)

    def expected_values(self) -> int:
        return self.ncell if self.nyears == 0 else self.ncell * int(self.nyears)

    def pack(self) -> bytes:
        if not (0 <= self.nyears <= 65535):
            raise ValueError(f"nyears out of range: {self.nyears}")
        if not (1 <= self.tile_h <= 65535 and 1 <= self.tile_w <= 65535):
            raise ValueError(f"tile size out of range: {self.tile_h}x{self.tile_w}")
        return _HDR_STRUCT.pack(
            MAGIC,
            int(self.version),
            int(self.dtype_code),
            0,
            int(self.nyears),
            int(self.tile_h),
            int(self.tile_w),
        )

    @staticmethod
    def unpack(buf: bytes) -> "TileHeader":
        if len(buf) < HEADER_SIZE:
            raise ValueError("Buffer too small for header")
        magic, version, dtype_code, _reserved0, nyears, tile_h, tile_w = (
            _HDR_STRUCT.unpack(buf[:HEADER_SIZE])
        )
        if magic != MAGIC:
            raise ValueError(f"Bad magic: {magic!r}")
        return TileHeader(
            version=int(version),
            dtype_code=int(dtype_code),
            nyears=int(nyears),
            tile_h=int(tile_h),
            tile_w=int(tile_w),
        )


def cell_index(o_lat: int, o_lon: int, tile_w: int) -> int:
    """Row-major cell index inside a tile."""
    return int(o_lat) * int(tile_w) + int(o_lon)


def _decompress_if_needed(path: Path, data: bytes) -> bytes:
    if path.suffix == ".zst":
        return zstd.ZstdDecompressor().decompress(data)
    return data


def _compress_if_needed(path: Path, data: bytes, *, level: int = 10) -> bytes:
    if path.suffix == ".zst":
        cctx = zstd.ZstdCompressor(level=level)
        return cctx.compress(data)
    return data


def _normalize_payload(
    arr: np.ndarray,
    *,
    nyears: int,
    tile_h: int,
    tile_w: int,
    dtype: np.dtype,
) -> np.ndarray:
    """
    Normalize payload to a 1D array in on-disk order:
      - scalar: [ncell]
      - series: [ncell, nyears] flattened row-major
    Accepts input shapes:
      scalar: (tile_h, tile_w) or (ncell,)
      series: (tile_h, tile_w, nyears) or (ncell, nyears) or (nyears, tile_h, tile_w)
    """
    arr = np.asarray(arr)

    ncell = int(tile_h) * int(tile_w)

    if nyears == 0:
        if arr.shape == (tile_h, tile_w):
            arr2 = arr.reshape(ncell)
        elif arr.shape == (ncell,):
            arr2 = arr
        else:
            raise ValueError(
                f"Scalar tile expects shape {(tile_h, tile_w)} or {(ncell,)}, got {arr.shape}"
            )
        return np.asarray(arr2, dtype=dtype).reshape(-1)

    # series
    if arr.shape == (tile_h, tile_w, nyears):
        arr2 = arr.reshape(ncell, nyears)
    elif arr.shape == (ncell, nyears):
        arr2 = arr
    elif arr.shape == (nyears, tile_h, tile_w):
        arr2 = np.transpose(arr, (1, 2, 0)).reshape(ncell, nyears)
    else:
        raise ValueError(
            f"Series tile expects shape {(tile_h, tile_w, nyears)} or {(ncell, nyears)} or {(nyears, tile_h, tile_w)}, got {arr.shape}"
        )

    return np.asarray(arr2, dtype=dtype).reshape(-1)


def write_tile(
    path: str | Path,
    arr: np.ndarray,
    *,
    dtype: np.dtype | str,
    nyears: int,
    tile_h: int,
    tile_w: int,
    compress_level: int = 10,
) -> None:
    """
    Write a tile file. If path endswith .zst, compress with zstd.
    """
    path = Path(path)
    dtype = np.dtype(dtype)
    dtype = np.dtype(dtype).newbyteorder("<")  # enforce little-endian

    if dtype not in _NP_TO_DTYPE_CODE:
        raise ValueError(
            f"Unsupported dtype {dtype}. Supported: {list(_NP_TO_DTYPE_CODE.keys())}"
        )

    hdr = TileHeader(
        version=VERSION,
        dtype_code=_NP_TO_DTYPE_CODE[dtype],
        nyears=int(nyears),
        tile_h=int(tile_h),
        tile_w=int(tile_w),
    )

    payload = _normalize_payload(
        arr, nyears=hdr.nyears, tile_h=hdr.tile_h, tile_w=hdr.tile_w, dtype=hdr.dtype
    )
    if payload.size != hdr.expected_values():
        raise ValueError(
            f"Payload has {payload.size} values but header expects {hdr.expected_values()}"
        )

    raw = hdr.pack() + payload.tobytes(order="C")
    raw = _compress_if_needed(path, raw, level=compress_level)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)


def read_tile_array(path: str | Path) -> tuple[TileHeader, np.ndarray]:
    """
    Read the entire tile into memory.

    Returns:
      - header
      - ndarray shaped:
          scalar: (tile_h, tile_w)
          series: (tile_h, tile_w, nyears)
    """
    path = Path(path)
    data = path.read_bytes()
    data = _decompress_if_needed(path, data)

    hdr = TileHeader.unpack(data[:HEADER_SIZE])
    if hdr.version != VERSION:
        raise ValueError(f"Unsupported tile version: {hdr.version}")

    payload_bytes = data[HEADER_SIZE:]
    expected_nbytes = hdr.expected_values() * hdr.dtype.itemsize
    if len(payload_bytes) != expected_nbytes:
        raise ValueError(
            f"Bad payload size: got {len(payload_bytes)} bytes, expected {expected_nbytes} bytes"
        )

    flat = np.frombuffer(payload_bytes, dtype=hdr.dtype)
    if hdr.nyears == 0:
        arr = flat.reshape(hdr.tile_h, hdr.tile_w)
    else:
        arr = flat.reshape(hdr.ncell, hdr.nyears).reshape(
            hdr.tile_h, hdr.tile_w, hdr.nyears
        )
    return hdr, arr.copy()  # copy to detach from buffer


def read_cell_series(
    path: str | Path, *, o_lat: int, o_lon: int
) -> tuple[TileHeader, np.ndarray]:
    """
    Read just one cell's vector (scalar => length 1 array, series => length nyears).
    Note: this still decompresses the whole tile (zstd is block-based; random seek is not worth it yet).
    """
    path = Path(path)
    data = path.read_bytes()
    data = _decompress_if_needed(path, data)

    hdr = TileHeader.unpack(data[:HEADER_SIZE])
    if hdr.version != VERSION:
        raise ValueError(f"Unsupported tile version: {hdr.version}")

    idx = cell_index(o_lat, o_lon, hdr.tile_w)
    if not (0 <= idx < hdr.ncell):
        raise IndexError(
            f"Cell index out of bounds: {o_lat=}, {o_lon=}, tile={hdr.tile_h}x{hdr.tile_w}"
        )

    payload = np.frombuffer(data, dtype=hdr.dtype, offset=HEADER_SIZE)

    if hdr.nyears == 0:
        v = payload[idx : idx + 1].astype(hdr.dtype, copy=True)
        return hdr, v

    start = idx * hdr.nyears
    end = start + hdr.nyears
    v = payload[start:end].astype(hdr.dtype, copy=True)
    return hdr, v
