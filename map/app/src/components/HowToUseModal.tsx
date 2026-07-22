import { useEffect } from "react";
import { COMPETITOR_TYPE_STYLE, MARKET_CLASS_STYLE } from "../config/classification";
import { useAppState } from "../state/useAppState";
import type { MarketClass } from "../types";

const CLASS_ORDER: MarketClass[] = [
  "true_whitespace",
  "proven_market_no_pv",
  "competitive_infill",
  "weak_whitespace",
  "other",
];

export default function HowToUseModal({ onClose }: { onClose: () => void }) {
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
        className="modal modal-howto"
        role="dialog"
        aria-labelledby="howto-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sidebar-head">
          <h2 id="howto-title">How to use this map</h2>
          <button type="button" className="linkish" onClick={onClose}>
            Close
          </button>
        </div>

        <section className="howto-section howto-callout">
          <h3>Inspect whitespace — click it</h3>
          <p>
            <strong>Click any green true-whitespace hex</strong> (or a blue proven-market hex) on the
            map. The right panel opens with demand, drive times to Pet Valu, competition, demographics,
            and factor bars. Click a clustered whitespace marker to zoom in, then click a hex or cluster
            outline for the same detail view.
          </p>
        </section>

        <section className="howto-section">
          <h3>What you’re looking at</h3>
          <p>
            Canada is tiled into H3 hexagons (~neighbourhood scale). Colour shows opportunity or another
            metric you pick in the top bar. Pet Valu stores are logo markers; competitors are small dots.
            Drive times come from the Mapbox API.
          </p>
        </section>

        <section className="howto-section">
          <h3>Market classes</h3>
          <p className="muted tiny">
            Each hex is labelled from demand, Pet Valu access, and competitor intensity
            {t
              ? ` (high demand ≥ ${(t.high_demand_percentile * 100).toFixed(0)}th pct; poor access ≥ ${t.poor_access_minutes_urban} min urban / ${t.poor_access_minutes_rural} min rural; meaningful competition ≥ ${(t.meaningful_competition_pct * 100).toFixed(0)}th pct).`
              : "."}
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
          <p className="muted tiny">
            True whitespace (green) and Proven market (blue) are overlays — leave them checked to see
            opportunity areas. Use <em>Top true whitespace</em> in the sidebar to focus on the
            highest-scoring green hexes only.
          </p>
        </section>

        <section className="howto-section">
          <h3>Layers &amp; filters</h3>
          <ul className="howto-bullets">
            <li>
              <strong>Market class checkboxes</strong> — show or hide each class on the map.
            </li>
            <li>
              <strong>Pet Valu network</strong> — circular logo markers for owned stores.
            </li>
            <li>
              <strong>Competitors</strong> —{" "}
              {Object.values(COMPETITOR_TYPE_STYLE)
                .map((s) => s.label)
                .join(", ")}{" "}
              (toggle each type).
            </li>
            <li>
              <strong>Whitespace cluster markers</strong> — groups of opportunity hexes when zoomed out;
              expand as you zoom in.
            </li>
            <li>
              <strong>Whitespace spotlight</strong> — dims the base choropleth so green/blue overlays stand
              out.
            </li>
            <li>
              <strong>Postal points</strong> — household dots at high zoom (optional).
            </li>
            <li>
              <strong>More filters</strong> — demand percentile, drive time, competition intensity,
              opportunity score ranges.
            </li>
            <li>
              <strong>Search / province / metric</strong> — jump to an FSA or store; colour the map by
              opportunity, demand, access, or class.
            </li>
          </ul>
        </section>

        <section className="howto-section">
          <h3>Dashboard tab</h3>
          <p>
            Switch to <strong>Dashboard</strong> for ranked lists, charts, and filters across Canada:
            opportunity-score definition, demand by province, top expandable clusters, and hexes sorted by
            demand or score. Use <strong>View on map</strong> on any row to fly there and open the detail
            panel automatically.
          </p>
        </section>

        <div className="howto-footer">
          <button type="button" className="btn" onClick={onClose}>
            Got it — show the map
          </button>
          <p className="muted tiny">Reopen anytime with the Help button in the top bar.</p>
        </div>
      </div>
    </div>
  );
}
