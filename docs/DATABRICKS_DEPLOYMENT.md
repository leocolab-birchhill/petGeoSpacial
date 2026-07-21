# Databricks Mapbox Matrix Deployment

## Status
- Local laptop run was stopped after transferring cache.
- Persistent storage: `dbfs:/petgeo/petGeospacial` (cluster path `/dbfs/petgeo/petGeospacial`)
  - Unity Catalog Volume create was denied; DBFS fallback is in use.
- Cluster: `petgeo-mapbox-routing` (`0721-005223-u1oo2qrv`), Personal Compute policy, autotermination 1000 minutes.
- Secret: `secrets/petgeo/mapbox_access_token`
- Full job is running and writing cache continuously.

## Monitor
```bash
databricks auth login --host https://dbc-be4688ff-39d6.cloud.databricks.com --profile petgeo
databricks jobs get-run 131583376113829 --profile petgeo
databricks fs ls dbfs:/petgeo/petGeospacial/mapbox_matrix_cache --profile petgeo | wc -l
```

Job UI:
https://dbc-be4688ff-39d6.cloud.databricks.com/?o=6294714617433660#job/156802930655843/run/131583376113829

## Resume (if needed)
Successful requests are cached on DBFS and will not be re-billed.
```bash
databricks clusters start 0721-005223-u1oo2qrv --profile petgeo
databricks bundle run mapbox_matrix_routing -t prod --profile petgeo --no-wait
```

## Assemble outputs after completion
```bash
databricks bundle run mapbox_matrix_dry_run -t prod --profile petgeo   # optional census
# Or run with --assemble-only by temporarily changing job parameters / running:
# databricks bundle run ... with parameters ["--assemble-only"]
```

Outputs land in:
- `/dbfs/petgeo/petGeospacial/h3_pet_valu_routing_results_long.parquet`
- `/dbfs/petgeo/petGeospacial/h3_pet_valu_routing_summary_wide.parquet`
- `/dbfs/petgeo/petGeospacial/h3_pet_valu_routing_failures.csv`
- `/dbfs/petgeo/petGeospacial/mapbox_request_audit.parquet`

## Caps
- Hard stop: 220,000 matrix elements / HTTP calls
- Dry-run at cutover: 1,290 cached → 52,669 new requests → 158,007 elements (under cap)
