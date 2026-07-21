"""
Databricks job entrypoint for Mapbox Matrix routing.

Expects:
  PETGEO_DATA_ROOT       Persistent DBFS/Volume project root (optional default)
  MAPBOX_ACCESS_TOKEN    Injected from Databricks secret scope via dbutils
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


BUNDLE_FILES_ROOT = Path(
    "/Workspace/Users/lcolabrese@birchhillequity.com/"
    ".bundle/petgeo-mapbox-routing/prod/files"
)
DEFAULT_DATA_ROOT = "/dbfs/petgeo/petGeospacial"


def _bootstrap_sys_path() -> None:
    candidates: list[Path] = [
        BUNDLE_FILES_ROOT,
        Path.cwd(),
        Path("/Workspace"),
    ]
    # When __file__ exists (local / some runners), prefer it
    try:
        here = Path(__file__).resolve().parent
        candidates = [here.parent, here, *candidates]
    except NameError:
        pass

    for candidate in candidates:
        target = candidate / "run_mapbox_matrix_routing.py"
        if target.exists():
            sys.path.insert(0, str(candidate))
            print(f"Using project root: {candidate}", flush=True)
            return

    # Last resort search under Workspace bundle trees
    for path in Path("/Workspace").rglob("run_mapbox_matrix_routing.py"):
        sys.path.insert(0, str(path.parent))
        print(f"Using discovered project root: {path.parent}", flush=True)
        return

    raise SystemExit("Could not locate run_mapbox_matrix_routing.py on cluster")


def _ensure_token_from_dbutils() -> None:
    if os.environ.get("MAPBOX_ACCESS_TOKEN", "").strip():
        print("MAPBOX_ACCESS_TOKEN already set in environment", flush=True)
        return
    scope = os.environ.get("MAPBOX_SECRET_SCOPE", "petgeo")
    key = os.environ.get("MAPBOX_SECRET_KEY", "mapbox_access_token")
    try:
        from pyspark.dbutils import DBUtils  # type: ignore
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
        dbutils = DBUtils(spark)
        token = dbutils.secrets.get(scope=scope, key=key)
        if token:
            os.environ["MAPBOX_ACCESS_TOKEN"] = token
            print(f"Loaded MAPBOX_ACCESS_TOKEN from secrets/{scope}/{key}", flush=True)
            return
    except Exception as exc:  # noqa: BLE001
        print(f"dbutils secret fallback unavailable: {exc}", flush=True)
    raise SystemExit(
        f"MAPBOX_ACCESS_TOKEN missing and secrets/{scope}/{key} unavailable"
    )


def main() -> None:
    _bootstrap_sys_path()
    _ensure_token_from_dbutils()

    data_root = os.environ.get("PETGEO_DATA_ROOT", "").strip() or DEFAULT_DATA_ROOT
    os.environ["PETGEO_DATA_ROOT"] = data_root
    Path(data_root).mkdir(parents=True, exist_ok=True)
    print(f"PETGEO_DATA_ROOT={data_root}", flush=True)

    import run_mapbox_matrix_routing as routing

    # Flat DBFS layout — do not use the local data/{processed,runtime,output} tree
    routing.bind_data_paths(Path(data_root), flat=True)

    # Forward CLI args; Databricks may inject notebook-style argv
    forwarded = [a for a in sys.argv[1:] if not str(a).startswith("/Workspace")]
    sys.argv = ["run_mapbox_matrix_routing.py", *forwarded]
    routing.main()


# Always invoke: Databricks spark_python_task may exec() without a normal __main__ guard.
main()
