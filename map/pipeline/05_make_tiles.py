"""Step 05 — Build PMTiles on Windows without tippecanoe/Docker/WSL.

Reads newline-delimited GeoJSON from build/geojson/ and writes:
  ../app/public/tiles/hexes.pmtiles   (layers h3_r7 z3-7, h3_r8 z6-13)
  ../app/public/tiles/postal.pmtiles  (layer postal z11-14, densest-drop)
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import mapbox_vector_tile
import mercantile
from pmtiles.tile import Compression, TileType, tileid_to_zxy, zxy_to_tileid
from pmtiles.writer import Writer

import config

HEX_MAX_PER_TILE = 2500
POSTAL_MAX_PER_TILE = 800


def _iter_ndjson(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _feature_centroid(feat: dict) -> tuple[float, float]:
    geom = feat["geometry"]
    gtype = geom["type"]
    coords = geom["coordinates"]
    if gtype == "Point":
        return float(coords[0]), float(coords[1])
    ring = coords[0] if gtype == "Polygon" else coords[0][0]
    xs = [p[0] for p in ring[:-1]]
    ys = [p[1] for p in ring[:-1]]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2.0**z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    x = min(max(x, 0), int(n) - 1)
    y = min(max(y, 0), int(n) - 1)
    return x, y


def build_pmtiles(
    out_path: Path,
    layers: list[tuple[str, Path, int, int, str | None, int]],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    # tile_id -> layer_name -> features
    bucket: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    min_z = min(mz for _, _, mz, _, _, _ in layers)
    max_z = max(Mz for _, _, _, Mz, _, _ in layers)

    for layer_name, path, minzoom, maxzoom, sort_prop, max_per_tile in layers:
        print(f"  indexing {layer_name} from {path.name} z{minzoom}-{maxzoom} ...")
        count = 0
        for feat in _iter_ndjson(path):
            lon, lat = _feature_centroid(feat)
            for z in range(minzoom, maxzoom + 1):
                x, y = _lonlat_to_tile(lon, lat, z)
                bucket[zxy_to_tileid(z, x, y)][layer_name].append(feat)
            count += 1
            if count % 100000 == 0:
                print(f"    {count} features...")
        print(f"    {count} features indexed")

        # Densest-drop for this layer across all tiles
        for layers_map in bucket.values():
            feats = layers_map.get(layer_name)
            if not feats or len(feats) <= max_per_tile:
                continue
            if sort_prop:
                feats.sort(
                    key=lambda f: float((f.get("properties") or {}).get(sort_prop) or 0),
                    reverse=True,
                )
            layers_map[layer_name] = feats[:max_per_tile]

    print(f"  encoding {len(bucket)} tiles -> {out_path.name}")
    with out_path.open("wb") as f:
        writer = Writer(f)
        for tid in sorted(bucket.keys()):
            z, x, y = tileid_to_zxy(tid)
            bounds = mercantile.bounds(x, y, z)
            mvt_layers = []
            for layer_name, feats in bucket[tid].items():
                if not feats:
                    continue
                # Pass WGS84 GeoJSON; library quantizes into tile space
                mvt_layers.append(
                    {
                        "name": layer_name,
                        "features": [
                            {
                                "geometry": feat["geometry"],
                                "properties": feat.get("properties") or {},
                            }
                            for feat in feats
                        ],
                    }
                )
            if not mvt_layers:
                continue
            encoded = mapbox_vector_tile.encode(
                mvt_layers,
                default_options={
                    "quantize_bounds": (bounds.west, bounds.south, bounds.east, bounds.north),
                },
            )
            writer.write_tile(tid, encoded)

        header = {
            "version": 3,
            "tile_type": TileType.MVT,
            "tile_compression": Compression.NONE,
            "min_zoom": min_z,
            "max_zoom": max_z,
            "center_zoom": 4,
            "center_lon_e7": int(-96 * 1e7),
            "center_lat_e7": int(56 * 1e7),
            "min_lon_e7": int(-141 * 1e7),
            "min_lat_e7": int(41 * 1e7),
            "max_lon_e7": int(-52 * 1e7),
            "max_lat_e7": int(83 * 1e7),
        }
        # pmtiles Writer API: finalize(header, metadata)
        if hasattr(writer, "finalize"):
            writer.finalize(header, {"name": out_path.stem, "generator": "petvalu-map-pipeline"})
        else:
            writer.close(header)

    print(f"  wrote {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")


def main(hexes_only: bool = False) -> None:
    config.APP_TILES.mkdir(parents=True, exist_ok=True)
    r7 = config.GEOJSON_DIR / "h3_r7.geojson.nd"
    r8 = config.GEOJSON_DIR / "h3_r8.geojson.nd"
    postal = config.GEOJSON_DIR / "postal_points.geojson.nd"
    required = (r7, r8) if hexes_only else (r7, r8, postal)
    for p in required:
        if not p.exists():
            raise FileNotFoundError(f"Missing {p}; run 04_export_geojson.py first")

    print("Building hexes.pmtiles ...")
    build_pmtiles(
        config.APP_TILES / "hexes.pmtiles",
        [
            ("h3_r7", r7, 3, 7, "households", HEX_MAX_PER_TILE),
            ("h3_r8", r8, 6, 13, "households", HEX_MAX_PER_TILE),
        ],
    )

    if not hexes_only:
        print("Building postal.pmtiles ...")
        build_pmtiles(
            config.APP_TILES / "postal.pmtiles",
            [
                ("postal", postal, 11, 14, "households", POSTAL_MAX_PER_TILE),
            ],
        )
    else:
        print("Skipping postal.pmtiles (--hexes-only)")
    print("Done.")


if __name__ == "__main__":
    import sys

    main(hexes_only="--hexes-only" in sys.argv)
