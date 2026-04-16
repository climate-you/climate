#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], root: Path, *, env: dict[str, str] | None = None) -> int:
    print(f"[run] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=root, env=env)
    return int(result.returncode)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Run validation in one pass: registry checks, tile coverage, unit tests, and API smoke tests."
        )
    )
    ap.add_argument(
        "--release",
        default="dev",
        help='Release for smoke checks (default: "dev").',
    )
    ap.add_argument(
        "--registry-release",
        default=None,
        help=(
            "Release to validate registry from data/releases/<release>/registry. "
            "Defaults to --release when registry/tile checks run, except for "
            'dev which uses repo-root "registry/".'
        ),
    )
    ap.add_argument(
        "--manifest-release",
        default=None,
        help=(
            "Release id whose data/releases/<release>/manifest.json should be "
            "validated. Defaults to --release when registry/tile checks run, "
            "except for dev where manifest validation is skipped."
        ),
    )
    ap.add_argument(
        "--releases-root",
        type=Path,
        default=Path("data/releases"),
        help='Releases root for --registry-release/--manifest-release (default: "data/releases").',
    )
    ap.add_argument(
        "--artifacts-root",
        type=Path,
        default=None,
        help=(
            "Artifact store root for v2 release manifest validation "
            "(default: sibling of releases-root named 'artifacts')."
        ),
    )
    ap.add_argument(
        "--base-url",
        default=f"http://127.0.0.1:{os.environ.get('API_PORT', '8001')}",
        help='API base URL for smoke checks (default: "http://127.0.0.1:8001", overridden by API_PORT env).',
    )
    ap.add_argument(
        "--locations-csv",
        type=Path,
        default=Path("data/locations/locations.csv"),
        help='Locations CSV path (default: "data/locations/locations.csv").',
    )
    ap.add_argument(
        "--index-csv",
        type=Path,
        default=Path("data/locations/locations.index.csv"),
        help='Locations index CSV path (default: "data/locations/locations.index.csv").',
    )
    ap.add_argument(
        "--tiles-root",
        type=Path,
        default=Path("data/releases/dev"),
        help='Tile root path for coverage checks (default: "data/releases/dev").',
    )
    ap.add_argument(
        "--tile-max-tiles",
        type=int,
        default=0,
        help="Max tiles per metric for coverage pass (default: 0 = full set).",
    )
    ap.add_argument(
        "--tile-only-referenced-metrics",
        action="store_true",
        help="Check tiles only for metrics referenced by maps/panels and dependencies (default: enabled).",
    )
    ap.add_argument(
        "--tile-all-metrics",
        action="store_true",
        help="Disable referenced-only mode and check all materialized tiled metrics.",
    )
    ap.add_argument(
        "--tile-require-real-coverage-pct",
        type=float,
        default=100.0,
        help="Fail if any checked metric is below this real coverage percent (default: 100).",
    )
    ap.add_argument(
        "--tile-global-domain",
        action="store_true",
        help="Disable domain-aware coverage and enforce global real coverage for all metrics.",
    )
    ap.add_argument(
        "--tile-summary-only",
        action="store_true",
        help="Pass --summary-only to tile_coverage: print one summary line per metric instead of every tile.",
    )
    ap.add_argument(
        "--tile-ocean-mask-metric",
        default="sst_yearly_mean_c",
        help="Ocean mask metric id used by domain-aware tile coverage (default: sst_yearly_mean_c).",
    )
    ap.add_argument(
        "--skip-registry",
        action="store_true",
        help="Skip registry validation.",
    )
    ap.add_argument(
        "--skip-tiles", action="store_true", help="Skip tile coverage check."
    )
    ap.add_argument(
        "--skip-pytest", action="store_true", help="Skip Python unit tests."
    )
    ap.add_argument(
        "--run-api-e2e",
        action="store_true",
        help="Run opt-in API e2e tests in tests/test_api_e2e.py (requires release/location data).",
    )
    ap.add_argument(
        "--api-e2e-release",
        default=None,
        help="Release id for API e2e tests (defaults to --release).",
    )
    ap.add_argument(
        "--check-rankings",
        action="store_true",
        help="Check that precomputed ranking files exist for all metrics that declare them.",
    )
    ap.add_argument(
        "--check-aggregates",
        action="store_true",
        help="Check that precomputed regional aggregate files exist for all metrics that declare them.",
    )
    ap.add_argument("--skip-smoke", action="store_true", help="Skip API smoke checks.")
    ap.add_argument(
        "--smoke-only",
        action="store_true",
        help="Run only endpoint smoke checks (no latency benchmark loops).",
    )
    ap.add_argument(
        "--smoke-n",
        type=int,
        default=25,
        help="Request count per endpoint when benchmark loops are enabled (default: 25).",
    )
    ap.add_argument(
        "--smoke-timeout-s",
        type=float,
        default=5.0,
        help="Per-request timeout for smoke/benchmark checks (default: 5).",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    run_release_checks = not args.skip_registry or not args.skip_tiles
    effective_registry_release = args.registry_release
    if effective_registry_release is None and run_release_checks:
        # Development mode resolves registry files from repo root.
        if args.release != "dev":
            effective_registry_release = args.release

    effective_manifest_release = args.manifest_release
    if effective_manifest_release is None and run_release_checks:
        # Development mode does not require a release manifest.
        if args.release != "dev":
            effective_manifest_release = args.release

    tiles_root = args.tiles_root
    if effective_registry_release and args.tiles_root == Path("data/releases/dev"):
        tiles_root = args.releases_root / effective_registry_release

    steps: list[list[str]] = []
    if effective_manifest_release:
        manifest_cmd = [
            sys.executable,
            "scripts/validate/release_manifest.py",
            "--release",
            effective_manifest_release,
            "--releases-root",
            str(args.releases_root),
        ]
        if args.artifacts_root is not None:
            manifest_cmd.extend(["--artifacts-root", str(args.artifacts_root)])
        steps.append(manifest_cmd)
        steps.append(
            [
                sys.executable,
                "scripts/validate/sparse_risk_mask.py",
                "--release",
                effective_manifest_release,
                "--releases-root",
                str(args.releases_root),
            ]
        )
    elif args.release == "dev" and run_release_checks:
        steps.append(
            [
                sys.executable,
                "scripts/validate/sparse_risk_mask.py",
                "--release",
                args.release,
                "--releases-root",
                str(args.releases_root),
                "--datasets-path",
                "registry/datasets.json",
            ]
        )

    if not args.skip_registry:
        registry_cmd = [sys.executable, "scripts/validate/all.py"]
        if effective_registry_release:
            registry_cmd.extend(
                [
                    "--release",
                    effective_registry_release,
                    "--releases-root",
                    str(args.releases_root),
                ]
            )
        steps.append(registry_cmd)
    if not args.skip_tiles:
        use_referenced_metrics = True
        if args.tile_all_metrics:
            use_referenced_metrics = False
        elif args.tile_only_referenced_metrics:
            use_referenced_metrics = True

        tile_cmd = [
            sys.executable,
            "scripts/tile_coverage.py",
            "--root",
            str(tiles_root),
            "--max-tiles",
            str(args.tile_max_tiles),
        ]
        if not args.tile_global_domain:
            tile_cmd.extend(
                [
                    "--domain-aware",
                    "--ocean-mask-metric",
                    str(args.tile_ocean_mask_metric),
                ]
            )
        if use_referenced_metrics:
            tile_cmd.append("--only-referenced-metrics")
        if args.tile_summary_only:
            tile_cmd.append("--summary-only")
        if args.tile_require_real_coverage_pct is not None:
            tile_cmd.extend(
                [
                    "--require-real-coverage-pct",
                    str(args.tile_require_real_coverage_pct),
                ]
            )
        if effective_registry_release:
            registry_root = args.releases_root / effective_registry_release / "registry"
            tile_cmd.extend(
                [
                    "--metrics-path",
                    str(registry_root / "metrics.json"),
                    "--datasets-path",
                    str(registry_root / "datasets.json"),
                    "--maps-path",
                    str(registry_root / "maps.json"),
                    "--panels-path",
                    str(registry_root / "panels.json"),
                ]
            )
        elif args.release == "dev":
            tile_cmd.extend(
                [
                    "--metrics-path",
                    "registry/metrics.json",
                    "--datasets-path",
                    "registry/datasets.json",
                    "--maps-path",
                    "registry/maps.json",
                    "--panels-path",
                    "registry/panels.json",
                ]
            )
        steps.append(tile_cmd)
    if args.check_rankings:
        rankings_cmd = [
            sys.executable,
            "scripts/validate/rankings.py",
            "--series-root",
            str(tiles_root / "series"),
        ]
        if effective_registry_release:
            rankings_cmd.extend([
                "--metrics",
                str(args.releases_root / effective_registry_release / "registry" / "metrics.json"),
            ])
        steps.append(rankings_cmd)
    if args.check_aggregates:
        aggregates_cmd = [
            sys.executable,
            "scripts/validate/aggregates.py",
            "--series-root",
            str(tiles_root / "series"),
        ]
        if effective_registry_release:
            aggregates_cmd.extend([
                "--metrics",
                str(args.releases_root / effective_registry_release / "registry" / "metrics.json"),
            ])
        steps.append(aggregates_cmd)
    if not args.skip_pytest:
        steps.append([sys.executable, "-m", "pytest", "-q"])
    if args.run_api_e2e:
        steps.append(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--cov-append",
                "tests/test_api_e2e.py",
            ]
        )
    if not args.skip_smoke:
        smoke_cmd = [
            sys.executable,
            "scripts/bench_api_endpoints.py",
            "--base-url",
            args.base_url,
            "--release",
            args.release,
            "--locations-csv",
            str(args.locations_csv),
            "--index-csv",
            str(args.index_csv),
            "--smoke",
            "--n",
            str(args.smoke_n),
            "--timeout-s",
            str(args.smoke_timeout_s),
        ]
        if args.smoke_only:
            smoke_cmd.append("--smoke-only")
        steps.append(smoke_cmd)

    for cmd in steps:
        env = None
        if args.run_api_e2e and cmd[-1] == "tests/test_api_e2e.py":
            e2e_release = args.api_e2e_release or args.release
            env = dict(os.environ)
            env["RUN_API_E2E"] = "1"
            env["API_E2E_RELEASE"] = e2e_release
        code = _run(cmd, root=root, env=env)
        if code != 0:
            print(f"[fail] validation suite failed (exit={code}): {' '.join(cmd)}")
            return code

    print("[ok] validation suite passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
