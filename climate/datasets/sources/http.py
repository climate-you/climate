from typing import Optional
from pathlib import Path
from typing import Tuple
import requests
import time
import numpy as np


def _ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def _sleep_seconds(attempt: int, base: float = 1.0) -> float:
    jitter = 0.25 * np.random.random()
    return base * (2**attempt) + jitter


def download_to(
    url: str,
    path: Path,
    *,
    timeout: Tuple[int, int] = (30, 300),
    retries: int = 6,
    label: str = "",
) -> Path:
    """
    Download URL -> file with caching + retries.
    timeout=(connect_seconds, read_seconds)
    """
    _ensure_dir(path)
    if path.exists() and path.stat().st_size > 0:
        return path

    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            if label:
                print(
                    f"{label} Downloading (attempt {attempt+1}/{retries}) -> {path.name}"
                )
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            path.write_bytes(r.content)
            return path

        except requests.HTTPError as e:
            last_err = e
            status = e.response.status_code if e.response is not None else None
            if status == 404 and label and e.response is not None:
                # ERDDAP often includes the real reason in the body
                body = (e.response.text or "").strip().replace("\n", " ")
                print(f"{label} 404 body: {body[:400]}")
            wait = _sleep_seconds(attempt, base=1.0)
            if label:
                print(
                    f"{label} Download failed: HTTPError {status} (sleep {wait:.1f}s)"
                )
            time.sleep(wait)

        except Exception as e:
            last_err = e
            wait = _sleep_seconds(attempt, base=1.0)
            if label:
                print(
                    f"{label} Download failed: {type(e).__name__}: {e} (sleep {wait:.1f}s)"
                )
            time.sleep(wait)

    raise RuntimeError(f"Failed to download after {retries} attempts: {last_err}")
