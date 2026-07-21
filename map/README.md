# Pet Valu Whitespace Map

Interactive map app for the Canadian Pet Valu whitespace analysis. H3 R8 opportunity
choropleth, store/competitor layers, per-hex route metrics, and market classification.

**Read `PLAN.md` first** — it is the master implementation plan. `DATA_CONTRACT.md`
defines every input/output schema. This folder is a skeleton: pipeline scripts are
spec'd stubs, the app is scaffolded with typed component stubs.

## Hard constraints

1. **NO new Mapbox API calls. Ever.** All routing metrics come from the existing
   local cache (`../data/runtime/mapbox_matrix_cache/`). The basemap uses
   OpenFreeMap (key-free). Do not add a Mapbox token anywhere.
2. Routing cache pull is complete (~99.5% `ok`; remainder is terminal `no_route`
   from failed/unreachable Matrix responses). Re-running 01 → 03 → 04 → 05
   refreshes scores/tiles if cache files change. No `pending_routing` class remains.
3. Never load raw national data as one GeoJSON in the browser. Hexes and postal
   points ship as PMTiles; only stores (1,687 points) load as plain GeoJSON.

## Layout

```
map/
├── PLAN.md                 Master plan (architecture, decisions, features, phases)
├── DATA_CONTRACT.md        Exact schemas for all pipeline inputs/outputs
├── pipeline/               Python data pipeline (repo root ../data → map/app/public/data + tiles)
│   ├── config.py           Paths, thresholds, classification & score constants
│   ├── 01_assemble_routing.py
│   ├── 02_build_competitors.py
│   ├── 03_build_opportunity_scores.py
│   ├── 04_export_geojson.py
│   ├── 05_make_tiles.sh    Tippecanoe + pmtiles commands (run in WSL or Docker)
│   └── requirements.txt
└── app/                    React + TypeScript + Vite + MapLibre GL JS
    ├── package.json
    ├── vite.config.ts / tsconfig.json / index.html
    ├── public/
    │   ├── tiles/          *.pmtiles output of step 05 (gitignored)
    │   └── data/           stores.geojson, clusters.geojson, details/ shards, fsa_index.json
    └── src/                see PLAN.md §6 for the component map
```

## Quickstart (once implemented)

```bash
# 1. Pipeline (from repo root, Windows Python is fine)
cd map/pipeline
pip install -r requirements.txt
python 01_assemble_routing.py        # cache JSONs -> routing wide parquet (no API calls)
python 02_build_competitors.py       # Excel -> competitors parquet + per-hex intensity
python 03_build_opportunity_scores.py# joins + opportunity score + classification
python 04_export_geojson.py          # GeoJSON for tiling + app static data

# 2. Tiles (tippecanoe is Linux-only: use WSL or Docker — exact commands in 05_make_tiles.sh)
bash 05_make_tiles.sh

# 3. App
cd ../app
npm install
npm run dev                          # http://localhost:5173
# production: npm run build && npx http-server dist -p 8080   (any range-request-capable static server)
```

## Re-running when the remaining routing cache arrives

Drop/merge the new `{h3_id}.json` files into `../data/runtime/mapbox_matrix_cache/`
(or point `config.OUTSTANDING_ZIP` at a new zip), then:

```bash
python 01_assemble_routing.py && python 03_build_opportunity_scores.py \
  && python 04_export_geojson.py && bash 05_make_tiles.sh
```
