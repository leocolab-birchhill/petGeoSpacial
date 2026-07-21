#!/usr/bin/env bash
# Step 05 — Generate PMTiles with tippecanoe (>= 2.17 writes .pmtiles natively).
#
# tippecanoe is Linux/macOS only. From Windows, run inside WSL:
#     wsl bash map/pipeline/05_make_tiles.sh
# or via Docker (no install needed):
#     docker run --rm -v "$(pwd)":/w -w /w/map/pipeline felt/tippecanoe:latest \
#         bash 05_make_tiles.sh
#
# Inputs : build/geojson/*.geojson.nd (from 04)
# Outputs: ../app/public/tiles/hexes.pmtiles, postal.pmtiles
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p ../app/public/tiles

# Hex choropleth: r7 at low zoom, r8 at working zooms, in one archive.
tippecanoe -o ../app/public/tiles/hexes.pmtiles --force \
  -L'{"file":"build/geojson/h3_r7.geojson.nd","layer":"h3_r7","minzoom":3,"maxzoom":7}' \
  -L'{"file":"build/geojson/h3_r8.geojson.nd","layer":"h3_r8","minzoom":6,"maxzoom":13}' \
  --detect-shared-borders \
  --coalesce-densest-as-needed \
  --no-simplification-of-shared-nodes \
  --read-parallel -P

# Postal points: high zoom only, thinned progressively below max zoom.
tippecanoe -o ../app/public/tiles/postal.pmtiles --force \
  -l postal --minzoom=11 --maxzoom=14 \
  --drop-densest-as-needed \
  --read-parallel -P \
  build/geojson/postal_points.geojson.nd

echo "Done:"
ls -lh ../app/public/tiles/
