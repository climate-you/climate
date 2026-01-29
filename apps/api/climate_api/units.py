from __future__ import annotations
from typing import Iterable, List


def c_to_f_abs(vals: Iterable[float]) -> List[float]:
    return [v * 9.0 / 5.0 + 32.0 for v in vals]


def c_to_f_delta(vals: Iterable[float]) -> List[float]:
    return [v * 9.0 / 5.0 for v in vals]


def convert_series(
    unit: str, unit_kind: str, y: list[float]
) -> tuple[list[float], str | None]:
    """
    unit: "C" or "F"
    unit_kind:
      - temp_abs: absolute temperature (C -> F with +32)
      - temp_delta: anomaly/delta (C -> F without +32)
      - count/raw: unchanged
    """
    unit = (unit or "C").upper()
    if unit not in ("C", "F"):
        return y, None

    if unit == "C":
        return y, "C" if unit_kind.startswith("temp") else None

    # unit == "F"
    if unit_kind == "temp_abs":
        return c_to_f_abs(y), "F"
    if unit_kind == "temp_delta":
        return c_to_f_delta(y), "F"
    return y, None
