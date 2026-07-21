"""
Set up persistent storage + Mapbox secret for PetGeo Mapbox job.

Tries Unity Catalog Volume first; falls back to DBFS if CREATE VOLUME is denied.

Usage:
  databricks auth login --host https://dbc-be4688ff-39d6.cloud.databricks.com --profile petgeo
  python scripts/setup_databricks_storage.py --profile petgeo
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HOST = "https://dbc-be4688ff-39d6.cloud.databricks.com"
VOLUME_NAME = "petgeo"
PROJECT_SUBDIR = "petGeospacial"
SECRET_SCOPE = "petgeo"
SECRET_KEY = "mapbox_access_token"
DBFS_FALLBACK = f"dbfs:/petgeo/{PROJECT_SUBDIR}"
DBFS_LOCAL_PATH = f"/dbfs/petgeo/{PROJECT_SUBDIR}"


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def load_local_token() -> str:
    env_path = Path(__file__).resolve().parents[1] / ".envs"
    if not env_path.exists():
        raise SystemExit("Local .envs not found; cannot seed secret")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("MAPBOX_ACCESS_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("MAPBOX_ACCESS_TOKEN missing from .envs")


def try_unity_catalog_volume(profile: str, catalog: str, schema: str) -> str | None:
    print(f"Attempting UC Volume in {catalog}.{schema}...", flush=True)
    # Ensure schema (may fail without privilege)
    run(
        ["databricks", "schemas", "create", schema, catalog, "--profile", profile],
        check=False,
    )
    created = run(
        [
            "databricks",
            "volumes",
            "create",
            catalog,
            schema,
            VOLUME_NAME,
            "MANAGED",
            "--profile",
            profile,
        ],
        check=False,
    )
    if created.returncode != 0:
        msg = (created.stderr or created.stdout or "").strip()
        print(f"UC Volume unavailable: {msg}", flush=True)
        return None
    path = f"/Volumes/{catalog}/{schema}/{VOLUME_NAME}/{PROJECT_SUBDIR}"
    print(f"Created UC Volume path: {path}", flush=True)
    return path


def setup_dbfs(profile: str) -> str:
    print(f"Falling back to DBFS path {DBFS_FALLBACK}", flush=True)
    mk = run(
        ["databricks", "fs", "mkdirs", DBFS_FALLBACK, "--profile", profile],
        check=False,
    )
    if mk.returncode != 0:
        raise SystemExit(mk.stderr or "Failed to create DBFS path")
    # Cluster-local FUSE mount path used by Python open()/Path
    print(f"Cluster data root will be: {DBFS_LOCAL_PATH}", flush=True)
    return DBFS_LOCAL_PATH


def setup_secret(profile: str) -> None:
    run(
        ["databricks", "secrets", "create-scope", SECRET_SCOPE, "--profile", profile],
        check=False,
    )
    token = load_local_token()
    put = run(
        [
            "databricks",
            "secrets",
            "put-secret",
            SECRET_SCOPE,
            SECRET_KEY,
            "--string-value",
            token,
            "--profile",
            profile,
        ],
        check=False,
    )
    if put.returncode != 0:
        print(put.stderr, file=sys.stderr)
        raise SystemExit("Failed to put Mapbox secret")
    print(f"Secret stored: secrets/{SECRET_SCOPE}/{SECRET_KEY}", flush=True)


def patch_databricks_yml(data_root: str) -> None:
    yml = Path(__file__).resolve().parents[1] / "databricks.yml"
    text = yml.read_text(encoding="utf-8")
    text = text.replace(
        "default: /Volumes/main/default/petgeo/petGeospacial",
        f"default: {data_root}",
    )
    text = text.replace(
        "petgeo_data_root: /Volumes/main/default/petgeo/petGeospacial",
        f"petgeo_data_root: {data_root}",
    )
    # If already patched to another path, force-replace variable default via simple marker
    if f"petgeo_data_root: {data_root}" not in text:
        import re

        text = re.sub(
            r"(petgeo_data_root:\s*)(/Volumes/[^\n]+|/dbfs/[^\n]+)",
            rf"\1{data_root}",
            text,
        )
        text = re.sub(
            r"(default:\s*)(/Volumes/[^\n]+|/dbfs/[^\n]+)",
            rf"\1{data_root}",
            text,
            count=1,
        )
    yml.write_text(text, encoding="utf-8")
    print(f"Patched databricks.yml petgeo_data_root -> {data_root}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="petgeo")
    parser.add_argument("--catalog", default="main")
    parser.add_argument("--schema", default="default")
    parser.add_argument(
        "--force-dbfs",
        action="store_true",
        help="Skip UC Volume attempt and use DBFS",
    )
    args = parser.parse_args()

    who = run(
        [
            "databricks",
            "current-user",
            "me",
            "--profile",
            args.profile,
            "--output",
            "json",
        ],
        check=False,
    )
    if who.returncode != 0:
        raise SystemExit(
            f"Auth failed for profile {args.profile}. Run:\n"
            f"  databricks auth login --host {HOST} --profile {args.profile}"
        )
    me = json.loads(who.stdout)
    print(f"Authenticated as: {me.get('userName') or me}", flush=True)

    data_root: str | None = None
    storage_kind = "dbfs"
    if not args.force_dbfs:
        data_root = try_unity_catalog_volume(args.profile, args.catalog, args.schema)
        if data_root:
            storage_kind = "uc_volume"

    if not data_root:
        data_root = setup_dbfs(args.profile)
        storage_kind = "dbfs"

    setup_secret(args.profile)
    patch_databricks_yml(data_root)

    cfg = {
        "profile": args.profile,
        "host": HOST,
        "storage_kind": storage_kind,
        "catalog": args.catalog if storage_kind == "uc_volume" else None,
        "schema": args.schema if storage_kind == "uc_volume" else None,
        "volume_name": VOLUME_NAME if storage_kind == "uc_volume" else None,
        "petgeo_data_root": data_root,
        "dbfs_uri": DBFS_FALLBACK if storage_kind == "dbfs" else None,
        "secret_scope": SECRET_SCOPE,
        "secret_key": SECRET_KEY,
    }
    out = Path(__file__).resolve().parents[1] / "databricks_deploy_config.json"
    out.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"Wrote {out}", flush=True)
    print(json.dumps(cfg, indent=2), flush=True)


if __name__ == "__main__":
    main()
