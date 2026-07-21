#!/usr/bin/env bash
# Controlled cutover: stop local Mapbox run, upload cache+input to Volume, dry-run, launch job.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROFILE="${DATABRICKS_PROFILE:-petgeo}"
CONFIG="$ROOT/databricks_deploy_config.json"

if [[ ! -f "$CONFIG" ]]; then
  echo "Missing $CONFIG — run: python scripts/setup_databricks_storage.py --profile $PROFILE"
  exit 1
fi

DATA_ROOT="$(python -c "import json; print(json.load(open(r'$CONFIG'))['petgeo_data_root'])")"
echo "Target Volume path: $DATA_ROOT"
echo "Profile: $PROFILE"

echo ""
echo "=== 1) Stop local routing process (if running) ==="
# Prefer graceful stop of known PID file / matching command
if pgrep -f "run_mapbox_matrix_routing.py" >/dev/null 2>&1; then
  echo "Sending SIGINT to local routing process..."
  pkill -INT -f "run_mapbox_matrix_routing.py" || true
  sleep 3
  if pgrep -f "run_mapbox_matrix_routing.py" >/dev/null 2>&1; then
    echo "Still running; sending SIGTERM..."
    pkill -TERM -f "run_mapbox_matrix_routing.py" || true
    sleep 2
  fi
else
  echo "No local routing process found."
fi

echo ""
echo "=== 2) Local cache census ==="
python - <<'PY'
from pathlib import Path
import json
cache = Path("data/runtime/mapbox_matrix_cache")
files = list(cache.glob("*.json")) if cache.exists() else []
ok = 0
for p in files:
    try:
        if json.loads(p.read_text(encoding="utf-8")).get("success"):
            ok += 1
    except Exception:
        pass
print(f"cache_files={len(files)} successful={ok}")
PY

echo ""
echo "=== 3) Upload routing input + cache + raw responses ==="
# Ensure remote directories exist by uploading a marker via fs mkdirs if available
databricks fs mkdirs "$DATA_ROOT" --profile "$PROFILE" || true
databricks fs mkdirs "$DATA_ROOT/mapbox_matrix_cache" --profile "$PROFILE" || true
databricks fs mkdirs "$DATA_ROOT/mapbox_raw_responses" --profile "$PROFILE" || true

databricks fs cp "data/processed/h3_store_routing_input.parquet" "$DATA_ROOT/h3_store_routing_input.parquet" --profile "$PROFILE" --overwrite
if [[ -d data/runtime/mapbox_matrix_cache ]]; then
  databricks fs cp data/runtime/mapbox_matrix_cache "$DATA_ROOT/mapbox_matrix_cache" --profile "$PROFILE" --recursive --overwrite
fi
if [[ -d data/runtime/mapbox_raw_responses ]]; then
  databricks fs cp data/runtime/mapbox_raw_responses "$DATA_ROOT/mapbox_raw_responses" --profile "$PROFILE" --recursive --overwrite
fi

echo ""
echo "=== 4) Deploy bundle ==="
databricks bundle deploy -t prod --profile "$PROFILE"

echo ""
echo "=== 5) Cloud dry-run ==="
databricks bundle run mapbox_matrix_dry_run -t prod --profile "$PROFILE"

echo ""
echo "=== 6) Launch full routing job ==="
databricks bundle run mapbox_matrix_routing -t prod --profile "$PROFILE" --no-wait

echo ""
echo "Cutover complete. Monitor with:"
echo "  databricks jobs list --profile $PROFILE"
echo "  databricks bundle run mapbox_matrix_routing -t prod --profile $PROFILE --no-wait   # already started"
echo "Laptop may now be shut down."
