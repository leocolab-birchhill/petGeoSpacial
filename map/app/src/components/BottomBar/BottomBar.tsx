import { MARKET_CLASS_STYLE } from "../../config/classification";
import { METRICS } from "../../config/metrics";
import { useAppState } from "../../state/useAppState";

export default function BottomBar() {
  const metric = useAppState((s) => s.metric);
  const meta = useAppState((s) => s.meta);
  const def = METRICS.find((m) => m.id === metric)!;
  const domain = meta?.metric_domains?.[def.field];
  return (
    <footer className="bottombar">
      <div className="legend">
        <strong>{def.label}</strong>
        {metric === "market_class" ? (
          <div className="swatches">
            {Object.entries(MARKET_CLASS_STYLE)
              .filter(([k]) => k !== "other" && k !== "pending_routing")
              .map(([k, s]) => (
                <span key={k} className="legend-item" title={s.description}>
                  <i style={{ background: s.color }} />
                  {s.label}
                </span>
              ))}
          </div>
        ) : (
          <div className="ramp">
            {def.ramp.map((c, i) => (
              <i key={i} style={{ background: c }} title={domain?.breaks?.[i - 1]?.toFixed?.(1)} />
            ))}
            {domain && (
              <span className="muted">
                {def.format(domain.min ?? 0)} → {def.format(domain.max ?? 0)}
              </span>
            )}
          </div>
        )}
      </div>

      <div className="class-key">
        {(["true_whitespace", "proven_market_no_pv", "competitive_infill", "weak_whitespace"] as const).map(
          (k) => (
            <span key={k} className="legend-item" title={MARKET_CLASS_STYLE[k].description}>
              <i style={{ background: MARKET_CLASS_STYLE[k].color }} />
              {MARKET_CLASS_STYLE[k].label}
            </span>
          ),
        )}
      </div>
    </footer>
  );
}
