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

    client = cdsapi.Client()
    client.retrieve(dataset, request, str(tmp))
    tmp.replace(target)
    return target
