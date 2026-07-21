"""
Local orchestrator: zip only outstanding Mapbox cache files on Databricks,
download the archive, and merge into data/runtime/mapbox_matrix_cache.

Steps:
  1) Build local have-list from mapbox_matrix_cache + mapbox_matrix_cache_pull
  2) Upload have-list + zip script
  3) Submit one-shot cluster job to zip outstanding files
  4) Download zip + extract into mapbox_matrix_cache
  5) Merge pull staging into cache and clean staging leftovers

Does not stop the cloud Mapbox routing job.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "data" / "runtime"
CACHE = RUNTIME / "mapbox_matrix_cache"
PULL = RUNTIME / "mapbox_matrix_cache_pull"
HAVE_LOCAL = RUNTIME / "local_cache_have.txt"
ZIP_SCRIPT = ROOT / "scripts" / "zip_outstanding_cache.py"

PROFILE_DEFAULT = "petgeo"
CLUSTER_DEFAULT = "0721-005223-u1oo2qrv"
DBFS_EXPORTS = "dbfs:/petgeo/petGeospacial/exports"
# Bundle Workspace path works for spark_python_task (import as RAW, not SOURCE).
WS_SCRIPT = (
    "/Users/lcolabrese@birchhillequity.com/.bundle/petgeo-mapbox-routing/"
    "prod/files/scripts/zip_outstanding_cache.py"
)


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, check=False, text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout.rstrip(), flush=True)
    if proc.stderr:
        print(proc.stderr.rstrip(), flush=True)
    if check and proc.returncode != 0:
        raise SystemExit(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


def build_have_list() -> set[str]:
    CACHE.mkdir(parents=True, exist_ok=True)
    PULL.mkdir(parents=True, exist_ok=True)
    have = {p.name for p in CACHE.glob("*.json")} | {p.name for p in PULL.glob("*.json")}
    HAVE_LOCAL.write_text(
        "\n".join(sorted(have)) + ("\n" if have else ""), encoding="utf-8"
    )
    print(f"local_have={len(have)} -> {HAVE_LOCAL}", flush=True)
    return have


def submit_zip_job(profile: str, cluster_id: str) -> str:
    run(["databricks", "fs", "mkdirs", DBFS_EXPORTS, "--profile", profile])
    # Remove prior zip so success probes don't match a stale artifact.
    run(
        [
            "databricks",
            "fs",
            "rm",
            f"{DBFS_EXPORTS}/mapbox_matrix_cache_outstanding.zip",
            "--profile",
            profile,
        ],
        check=False,
    )
    run(
        [
            "databricks",
            "fs",
            "rm",
            f"{DBFS_EXPORTS}/mapbox_matrix_cache_outstanding_manifest.txt",
            "--profile",
            profile,
        ],
        check=False,
    )
    run(
        [
            "databricks",
            "fs",
            "cp",
            str(HAVE_LOCAL),
            f"{DBFS_EXPORTS}/local_cache_have.txt",
            "--profile",
            profile,
            "--overwrite",
        ]
    )
    run(
        [
            "databricks",
            "fs",
            "cp",
            str(ZIP_SCRIPT),
            f"{DBFS_EXPORTS}/zip_outstanding_cache.py",
            "--profile",
            profile,
            "--overwrite",
        ]
    )
    # Git Bash path conversion breaks /Users/... unless disabled.
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"
    print(
        f"+ databricks workspace import {WS_SCRIPT} --file {ZIP_SCRIPT} "
        f"--format RAW --overwrite --profile {profile}",
        flush=True,
    )
    imp = subprocess.run(
        [
            "databricks",
            "workspace",
            "import",
            WS_SCRIPT,
            "--file",
            str(ZIP_SCRIPT),
            "--format",
            "RAW",
            "--overwrite",
            "--profile",
            profile,
        ],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    if imp.stdout:
        print(imp.stdout.rstrip(), flush=True)
    if imp.stderr:
        print(imp.stderr.rstrip(), flush=True)
    if imp.returncode != 0:
        raise SystemExit(f"workspace import failed ({imp.returncode})")

    payload = {
        "run_name": "petgeo-zip-outstanding-cache",
        "tasks": [
            {
                "task_key": "zip_outstanding",
                "existing_cluster_id": cluster_id,
                "spark_python_task": {"python_file": WS_SCRIPT},
            }
        ],
    }
    proc = run(
        [
            "databricks",
            "jobs",
            "submit",
            "--profile",
            profile,
            "--no-wait",
            "--json",
            json.dumps(payload),
        ]
    )
    out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    run_id = None
    try:
        data = json.loads(proc.stdout)
        run_id = str(data.get("run_id") or data.get("number_in_job") or "")
    except Exception:
        for token in out.replace(",", " ").split():
            if token.isdigit() and len(token) > 6:
                run_id = token
                break
    if not run_id:
        raise SystemExit(f"Could not parse run_id from submit output:\n{out}")
    print(f"submitted run_id={run_id}", flush=True)
    return run_id


def wait_run(profile: str, run_id: str, timeout_s: int = 3600) -> None:
    start = time.time()
    while True:
        proc = run(
            ["databricks", "jobs", "get-run", run_id, "--profile", profile]
        )
        data = json.loads(proc.stdout)
        state = (data.get("state") or {}).get("life_cycle_state", "?")
        result = (data.get("state") or {}).get("result_state")
        print(f"run {run_id}: life={state} result={result}", flush=True)
        if state in {"TERMINATED", "INTERNAL_ERROR", "SKIPPED"}:
            if result == "SUCCESS":
                return
            # Databricks flags bare sys.exit(0) as FAILED even when zip succeeded.
            # Verify the zip artifact exists before failing hard.
            probe = run(
                [
                    "databricks",
                    "fs",
                    "ls",
                    f"{DBFS_EXPORTS}/mapbox_matrix_cache_outstanding.zip",
                    "--profile",
                    profile,
                ],
                check=False,
            )
            if probe.returncode == 0 and "mapbox_matrix_cache_outstanding.zip" in (
                probe.stdout or ""
            ):
                print(
                    "Zip artifact present despite non-SUCCESS job result; continuing.",
                    flush=True,
                )
                return
            raise SystemExit(f"Zip job ended with result={result} state={state}")
        if time.time() - start > timeout_s:
            raise SystemExit(f"Timed out waiting for run {run_id}")
        time.sleep(15)


def download_and_merge(profile: str) -> None:
    dest_zip = RUNTIME / "mapbox_matrix_cache_outstanding.zip"
    dest_manifest = RUNTIME / "mapbox_matrix_cache_outstanding_manifest.txt"
    if dest_zip.exists():
        dest_zip.unlink()

    run(
        [
            "databricks",
            "fs",
            "cp",
            f"{DBFS_EXPORTS}/mapbox_matrix_cache_outstanding.zip",
            str(dest_zip),
            "--profile",
            profile,
            "--overwrite",
        ]
    )
    run(
        [
            "databricks",
            "fs",
            "cp",
            f"{DBFS_EXPORTS}/mapbox_matrix_cache_outstanding_manifest.txt",
            str(dest_manifest),
            "--profile",
            profile,
            "--overwrite",
        ],
        check=False,
    )

    CACHE.mkdir(parents=True, exist_ok=True)
    extracted = 0
    with zipfile.ZipFile(dest_zip, "r") as zf:
        names = [n for n in zf.namelist() if n.endswith(".json")]
        for name in names:
            target = CACHE / Path(name).name
            with zf.open(name) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted += 1
    print(f"extracted_into_cache={extracted}", flush=True)

    moved = 0
    if PULL.is_dir():
        for src in PULL.glob("*.json"):
            dst = CACHE / src.name
            if not dst.exists():
                shutil.move(str(src), str(dst))
                moved += 1
            else:
                src.unlink()
        leftover = list(PULL.glob("*"))
        print(
            f"merged_from_pull_staging={moved} leftover={len(leftover)}",
            flush=True,
        )

    total = len(list(CACHE.glob("*.json")))
    print(f"cache_total_now={total}", flush=True)
    print(f"zip_kept_at={dest_zip}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=PROFILE_DEFAULT)
    parser.add_argument("--cluster-id", default=CLUSTER_DEFAULT)
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Skip submit; just download/extract an already-built zip",
    )
    args = parser.parse_args()

    if not ZIP_SCRIPT.exists():
        raise SystemExit(f"Missing {ZIP_SCRIPT}")

    build_have_list()
    if not args.download_only:
        run_id = submit_zip_job(args.profile, args.cluster_id)
        wait_run(args.profile, run_id)
    download_and_merge(args.profile)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
