from __future__ import annotations

from pathlib import Path
from typing import Any

import cdsapi


def retrieve(
    dataset: str,
    request: dict[str, Any],
    target: Path,
    *,
    overwrite: bool = False,
) -> Path:
    """
    Retrieve a CDS dataset to a local file with basic caching.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        return target

    tmp = target.with_suffix(target.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()

    # cdsapi backs off to 120s between status polls by default, so a job can sit
    # finished on the server for up to two minutes before we start downloading.
    # That dead time is paid once per request, which is minor against a 17-minute
    # queue but dominates when the queue is short (off-peak, or on the
    # uncongested monthly-means and hourly datasets).
    client = cdsapi.Client(sleep_max=20)
    client.retrieve(dataset, request, str(tmp))
    tmp.replace(target)
    return target
