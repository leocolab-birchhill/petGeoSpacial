import type { DetailShard, HexDetail } from "../types";
import { assetUrl } from "./baseUrl";

const PREFIX_LEN = 5; // must match pipeline config.DETAIL_SHARD_PREFIX_LEN
const cache = new Map<string, DetailShard>();

/**
 * Fetch the full detail record for a hex from its shard
 * (/data/details/{h3_id[:5]}.json). Shards are ~40 records; cached in memory.
 */
export async function fetchHexDetail(h3Id: string): Promise<HexDetail | null> {
  const prefix = h3Id.slice(0, PREFIX_LEN);
  let shard = cache.get(prefix);
  if (!shard) {
    const res = await fetch(assetUrl(`/data/details/${prefix}.json`));
    if (!res.ok) return null;
    shard = (await res.json()) as DetailShard;
    cache.set(prefix, shard);
  }
  return shard[prefix]?.[h3Id] ?? null;
}
