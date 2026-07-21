"""
Cluster-side: zip only cache JSON files not listed in a local have-list.

Reads:
  {DATA_ROOT}/exports/local_cache_have.txt   (basenames, one per line)
  {DATA_ROOT}/mapbox_matrix_cache/*.json

Writes (via /tmp then copy — DBFS fuse does not support zip seek):
  {DATA_ROOT}/exports/mapbox_matrix_cache_outstanding.zip
  {DATA_ROOT}/exports/mapbox_matrix_cache_outstanding_manifest.txt
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

DEFAULT_DATA_ROOT = "/dbfs/petgeo/petGeospacial"


def _copy_to_dbfs(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    # Binary stream copy avoids seek issues on DBFS fuse mounts.
    with src.open("rb") as fin, dest.open("wb") as fout:
        shutil.copyfileobj(fin, fout, length=1024 * 1024)


def main() -> None:
    data_root = Path(os.environ.get("PETGEO_DATA_ROOT", "").strip() or DEFAULT_DATA_ROOT)
    cache_dir = data_root / "mapbox_matrix_cache"
    export_dir = data_root / "exports"
    have_path = export_dir / "local_cache_have.txt"
    zip_dest = export_dir / "mapbox_matrix_cache_outstanding.zip"
    manifest_dest = export_dir / "mapbox_matrix_cache_outstanding_manifest.txt"

    export_dir.mkdir(parents=True, exist_ok=True)
    if not cache_dir.is_dir():
        raise SystemExit(f"Missing cache dir: {cache_dir}")
    if not have_path.is_file():
        raise SystemExit(f"Missing have-list: {have_path}")

    have = {
        line.strip()
        for line in have_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    remote = sorted(p.name for p in cache_dir.glob("*.json"))
    outstanding = [name for name in remote if name not in have]

    print(f"DATA_ROOT={data_root}", flush=True)
    print(f"remote_cache={len(remote)}", flush=True)
    print(f"local_have={len(have)}", flush=True)
    print(f"outstanding={len(outstanding)}", flush=True)

    with tempfile.TemporaryDirectory(prefix="petgeo_zip_") as tmp:
        tmp_dir = Path(tmp)
        zip_tmp = tmp_dir / "mapbox_matrix_cache_outstanding.zip"
        manifest_tmp = tmp_dir / "mapbox_matrix_cache_outstanding_manifest.txt"

        written = 0
        with zipfile.ZipFile(
            zip_tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as zf:
            for i, name in enumerate(outstanding, 1):
                src = cache_dir / name
                # Read via Path.open into writestr to avoid fuse quirks in ZipFile.write
                data = src.read_bytes()
                zf.writestr(name, data)
                written += 1
                if i % 2000 == 0 or i == len(outstanding):
                    print(f"  zipped {i}/{len(outstanding)}", flush=True)

        manifest_tmp.write_text(
            "\n".join(
                [
                    f"remote_cache={len(remote)}",
                    f"local_have={len(have)}",
                    f"outstanding={len(outstanding)}",
                    f"zip_bytes={zip_tmp.stat().st_size}",
                    *outstanding,
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        print(
            f"local zip ready: {zip_tmp} ({zip_tmp.stat().st_size:,} bytes) "
            f"files={written}",
            flush=True,
        )
        _copy_to_dbfs(zip_tmp, zip_dest)
        _copy_to_dbfs(manifest_tmp, manifest_dest)

    print(f"Wrote {zip_dest} ({zip_dest.stat().st_size:,} bytes)", flush=True)
    print(f"Wrote {manifest_dest}", flush=True)


if __name__ == "__main__":
    main()
