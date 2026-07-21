import { useEffect } from "react";
import { MARKET_CLASS_STYLE } from "../config/classification";
import { useAppState } from "../state/useAppState";
import type { MarketClass } from "../types";

const CLASS_ORDER: MarketClass[] = [
  "true_whitespace",
  "proven_market_no_pv",
  "competitive_infill",
  "weak_whitespace",
  "other",
];

export default function ClassDefinitionsModal({ onClose }: { onClose: () => void }) {
  const meta = useAppState((s) => s.meta);
  const t = meta?.class_thresholds;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-labelledby="class-defs-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sidebar-head">
          <h2 id="class-defs-title">Market classification definitions</h2>
          <button type="button" className="linkish" onClick={onClose}>
            Close
          </button>
        </div>
        <p className="muted">
          Each H3 hex is classified from demand, Pet Valu drive-time access, and competitor intensity.
          {t && (
            <>
              {" "}
              Defaults: high demand ≥ {(t.high_demand_percentile * 100).toFixed(0)}th percentile; poor
              access ≥ {t.poor_access_minutes_urban} min urban / {t.poor_access_minutes_rural} min rural;
              meaningful competition ≥ {(t.meaningful_competition_pct * 100).toFixed(0)}th percentile
              intensity.
            </>
          )}
        </p>
        <p className="muted tiny">
          True whitespace and Proven market are translucent overlays (on by default). Uncheck a class
          to hide it.
        </p>
        <ul className="def-list">
          {CLASS_ORDER.map((k) => {
            const s = MARKET_CLASS_STYLE[k];
            return (
              <li key={k}>
                <span className="swatch" style={{ background: s.color }} />
                <div>
                  <strong>{s.label}</strong>
                  <div>{s.description}</div>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
