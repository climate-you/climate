#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _normalize_base(url: str) -> str:
    url = url.strip()
    if not url:
        return url
    if not url.endswith("/"):
        url += "/"
    if not url.endswith("erddap/"):
        if "erddap" not in url:
            url += "erddap/"
        elif url.endswith("erddap"):
            url += "/"
    return url


def _has_dataset(base: str, dataset_id: str, timeout: float) -> bool:
    # Prefer info endpoint; fallback to search.
    info_json = urllib.parse.urljoin(base, f"info/{dataset_id}/index.json")
    info_html = urllib.parse.urljoin(base, f"info/{dataset_id}/index.html")
    search_url = urllib.parse.urljoin(
        base,
        "search/index.json?searchFor="
        + urllib.parse.quote(dataset_id)
        + "&itemsPerPage=1",
    )
    for url in (info_json, info_html, search_url):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                if 200 <= resp.status < 300:
                    return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
        except Exception:
            continue
    return False


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Check which ERDDAP servers host a dataset."
    )
    ap.add_argument(
        "--list-url",
        default="https://irishmarineinstitute.github.io/awesome-erddap/erddaps.json",
    )
    ap.add_argument("--dataset-id", required=True)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    with urllib.request.urlopen(args.list_url, timeout=args.timeout) as resp:
        servers = json.load(resp)

    matches = []
    print(f"Found {len(servers)} servers")
    for i, entry in enumerate(servers):
        base = _normalize_base(entry.get("url", ""))
        if not base:
            continue
        print(f"({i+1}/{len(servers)}) Testing: {base}")
        ok = _has_dataset(base, args.dataset_id, args.timeout)
        if ok:
            matches.append({"name": entry.get("name"), "url": base})
            print(f"FOUND: {base}")

    if args.out:
        args.out.write_text(json.dumps(matches, indent=2))
        print(f"Wrote {len(matches)} match(es) to {args.out}")
    else:
        print(f"Found {len(matches)} match(es).")


if __name__ == "__main__":
    main()
