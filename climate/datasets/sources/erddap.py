import pandas as pd
from pathlib import Path
from urllib.parse import quote


def build_griddap_query(
    spec: dict,
    *,
    a_date: str,
    b_date: str,
    lat0: float,
    lat1: float,
    lon0: float,
    lon1: float,
    stride_time: int = 1,
    stride_lat: int = 1,
    stride_lon: int = 1,
) -> str:
    """
    Build a griddap constraint string in the correct dimension order for the variable,
    including any required fixed dimensions (e.g. zlev=0.0).

    a_date/b_date are YYYY-MM-DD (no time part). Spec controls time HH:MM:SSZ.
    """
    var = spec["var"]
    dims = spec["dims"]
    fixed = spec.get("fixed", {})
    time_hms = spec.get("time_hms", "00:00:00Z")

    # Build one bracketed constraint per dim, in order.
    parts: list[str] = []

    for dim in dims:
        if dim == "time":
            parts.append(
                f"[({a_date}T{time_hms}):{int(stride_time)}:({b_date}T{time_hms})]"
            )
        elif dim in fixed:
            parts.append(f"[({fixed[dim]})]")
        elif dim in ("latitude", "lat"):
            parts.append(f"[({lat0}):{int(stride_lat)}:({lat1})]")
        elif dim in ("longitude", "lon"):
            parts.append(f"[({lon0}):{int(stride_lon)}:({lon1})]")
        else:
            # If we ever add a dataset with a new dim, we must encode how to constrain it.
            raise RuntimeError(
                f"Unhandled ERDDAP dim '{dim}' for var '{var}'. Update spec/query builder."
            )

    return var + "".join(parts)


def make_griddap_url(base: str, dataset_id: str, query: str, ext: str) -> str:
    """
    Build {base}/griddap/{dataset_id}.{ext}?{query}
    Query is URL-encoded but keeps ERDDAP bracket syntax readable.
    """
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_[]():,.-TZ"
    q = quote(query, safe=safe)
    return f"{base}/griddap/{dataset_id}.{ext}?{q}"


def read_csv(path: Path) -> pd.DataFrame:
    """
    ERDDAP CSV: header row, then units row. Skip units row.
    """
    return pd.read_csv(path, skiprows=[1])
