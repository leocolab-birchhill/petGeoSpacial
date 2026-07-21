"""
Controlled cutover from local Mapbox run to Databricks Volume-backed job.

Steps:
  1) Stop local routing process
  2) Census successful cache
  3) Upload input + cache + raw responses to Volume
  4) Deploy bundle
  5) Cloud dry-run
  6) Launch full job (no-wait)

Usage:
  python scripts/setup_databricks_storage.py --profile petgeo
  python scripts/cutover_to_databricks.py --profile petgeo
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(ROOT), check=check, text=True)


def cache_census() -> tuple[int, int]:
    cache = ROOT / "data" / "runtime" / "mapbox_matrix_cache"
    files = list(cache.glob("*.json")) if cache.exists() else []
    ok = 0
    for path in files:
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("success"):
                ok += 1
        except Exception:
            pass
    return len(files), ok


def stop_local_routing() -> None:
    print("=== 1) Stop local routing process ===", flush=True)
    stopped = False

    # Prefer PowerShell process lookup (works on Windows)
    ps = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine -like '*run_mapbox_matrix_routing.py*' } | "
                "ForEach-Object { "
                "  Write-Output $_.ProcessId; "
                "  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue "
                "}"
            ),
        ],
        capture_output=True,
        text=True,
    )
    pids = [line.strip() for line in (ps.stdout or "").splitlines() if line.strip().isdigit()]
    if pids:
        print(f"Stopped PIDs: {', '.join(pids)}", flush=True)
        stopped = True

    # Optional: also try bash pkill when available (Git Bash / WSL)
    if not stopped:
        pkill = subprocess.run(
            ["bash", "-lc", "pkill -INT -f run_mapbox_matrix_routing.py || true"],
            capture_output=True,
            text=True,
        )
        if pkill.returncode == 0 and "No such" not in (pkill.stderr or ""):
            # pkill returns 1 when no process matched; treat cautiously
            pass

    if not stopped:
        print("No local routing process found (or already stopped).", flush=True)
    else:
        time.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="petgeo")
    parser.add_argument(
        "--skip-stop",
        action="store_true",
        help="Do not attempt to stop the local process",
    )
    parser.add_argument(
        "--skip-launch",
        action="store_true",
        help="Upload + dry-run only; do not start the paid job",
    )
    args = parser.parse_args()

    config_path = ROOT / "databricks_deploy_config.json"
    if not config_path.exists():
        raise SystemExit(
            f"Missing {config_path}. Run scripts/setup_databricks_storage.py first."
        )
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    data_root = cfg["petgeo_data_root"]
    # databricks fs commands need dbfs:/ or /Volumes URI, not /dbfs FUSE path
    fs_root = cfg.get("dbfs_uri") or data_root
    if data_root.startswith("/dbfs/"):
        fs_root = "dbfs:/" + data_root[len("/dbfs/") :]
    profile = args.profile or cfg.get("profile", "petgeo")
    print(f"Cluster DATA_ROOT: {data_root}", flush=True)
    print(f"Upload FS root:    {fs_root}", flush=True)

    # Patch databricks.yml default volume path if needed
    yml = ROOT / "databricks.yml"
    text = yml.read_text(encoding="utf-8")
    if data_root not in text:
        # Update default and prod variable values
        import re

        text2 = re.sub(
            r"(petgeo_data_root:\s*).*",
            rf"\1{data_root}",
            text,
        )
        # Also replace the default: line under variables
        text2 = text2.replace(
            "default: /Volumes/main/default/petgeo/petGeospacial",
            f"default: {data_root}",
        )
        text2 = text2.replace(
            "petgeo_data_root: /Volumes/main/default/petgeo/petGeospacial",
            f"petgeo_data_root: {data_root}",
        )
        yml.write_text(text2, encoding="utf-8")
        print(f"Updated databricks.yml petgeo_data_root -> {data_root}", flush=True)

    if not args.skip_stop:
        stop_local_routing()

    total, ok = cache_census()
    print(f"=== 2) Local cache census: files={total} successful={ok} ===", flush=True)

    print("=== 3) Upload input + cache + raw to persistent storage ===", flush=True)
    run(["databricks", "fs", "mkdirs", fs_root, "--profile", profile], check=False)
    run(
        [
            "databricks",
            "fs",
            "mkdirs",
            f"{fs_root}/mapbox_matrix_cache",
            "--profile",
            profile,
        ],
        check=False,
    )
    run(
        [
            "databricks",
            "fs",
            "mkdirs",
            f"{fs_root}/mapbox_raw_responses",
            "--profile",
            profile,
        ],
        check=False,
    )

    input_parquet = ROOT / "data" / "processed" / "h3_store_routing_input.parquet"
    if not input_parquet.exists():
        raise SystemExit("Missing data/processed/h3_store_routing_input.parquet")
    run(
        [
            "databricks",
            "fs",
            "cp",
            str(input_parquet),
            f"{fs_root}/h3_store_routing_input.parquet",
            "--profile",
            profile,
            "--overwrite",
        ]
    )

    cache_dir = ROOT / "data" / "runtime" / "mapbox_matrix_cache"
    if cache_dir.exists() and any(cache_dir.glob("*.json")):
        run(
            [
                "databricks",
                "fs",
                "cp",
                str(cache_dir),
                f"{fs_root}/mapbox_matrix_cache",
                "--profile",
                profile,
                "--recursive",
                "--overwrite",
            ]
        )

    raw_dir = ROOT / "data" / "runtime" / "mapbox_raw_responses"
    if raw_dir.exists() and any(raw_dir.glob("*.json")):
        run(
            [
                "databricks",
                "fs",
                "cp",
                str(raw_dir),
                f"{fs_root}/mapbox_raw_responses",
                "--profile",
                profile,
                "--recursive",
                "--overwrite",
            ]
        )

    print("=== 4) Deploy bundle ===", flush=True)
    run(["databricks", "bundle", "deploy", "-t", "prod", "--profile", profile])

    print("=== 5) Cloud dry-run ===", flush=True)
    run(
        [
            "databricks",
            "bundle",
            "run",
            "mapbox_matrix_dry_run",
            "-t",
            "prod",
            "--profile",
            profile,
        ]
    )

    if args.skip_launch:
        print("Skipping launch (--skip-launch). Review dry-run, then relaunch.", flush=True)
        return

    print("=== 6) Launch full routing job (no-wait) ===", flush=True)
    run(
        [
            "databricks",
            "bundle",
            "run",
            "mapbox_matrix_routing",
            "-t",
            "prod",
            "--profile",
            profile,
            "--no-wait",
        ]
    )
    print(
        "\nCutover complete. Laptop may be shut down.\n"
        f"Monitor: databricks jobs list --profile {profile}\n"
        f"Volume: {data_root}",
        flush=True,
    )


if __name__ == "__main__":
    main()
