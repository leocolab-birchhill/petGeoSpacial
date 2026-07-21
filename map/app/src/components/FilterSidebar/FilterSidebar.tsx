import { useState } from "react";
import {
  MARKET_CLASS_STYLE,
  COMPETITOR_TYPE_STYLE,
  isOptInMarketClass,
  OTHER_MARKET_CLASSES,
} from "../../config/classification";
import { useAppState, DEFAULT_TOGGLES } from "../../state/useAppState";
import type { CompetitorType, MarketClass, TopTrueWhitespacePct } from "../../types";
import ClassDefinitionsModal from "../ClassDefinitionsModal";

const TOP_TW_OPTIONS: TopTrueWhitespacePct[] = [5, 10, 15, 20, 25, 50];

function Range({
  label,
  min,
  max,
  step,
  value,
  onChange,
}: {
  label: string;
  min: number;
  max: number;
  step: number;
  value: [number, number];
  onChange: (v: [number, number]) => void;
}) {
  return (
    <div className="filter-block">
      <div className="filter-label">
        {label}{" "}
        <span className="muted">
          {value[0]} – {value[1]}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value[0]}
        onChange={(e) => onChange([Number(e.target.value), value[1]])}
      />
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value[1]}
        onChange={(e) => onChange([value[0], Number(e.target.value)])}
      />
    </div>
  );
}

export default function FilterSidebar() {
  const filters = useAppState((s) => s.filters);
  const toggles = useAppState((s) => s.toggles);
  const meta = useAppState((s) => s.meta);
  const setFilters = useAppState((s) => s.setFilters);
  const setToggles = useAppState((s) => s.setToggles);
  const resetFilters = useAppState((s) => s.resetFilters);
  const [moreOpen, setMoreOpen] = useState(false);
  const [defsOpen, setDefsOpen] = useState(false);

  const topTwActive = filters.topTrueWhitespacePct != null;
  const topTwPct = filters.topTrueWhitespacePct ?? 10;

  const optInSelected = filters.marketClasses.filter(isOptInMarketClass);
  const otherSelected = filters.marketClasses.filter((c) => !isOptInMarketClass(c));

  const enableTopTrueWhitespace = (pct: TopTrueWhitespacePct) => {
    setFilters({
      topTrueWhitespacePct: pct,
      hideOtherClasses: true,
      marketClasses: ["true_whitespace"],
    });
  };

  const disableTopTrueWhitespace = (patch: Partial<typeof filters> = {}) => {
    setFilters({
      topTrueWhitespacePct: null,
      ...patch,
    });
  };

  const toggleOptIn = (cls: MarketClass) => {
    // Checking any other opt-in class while top-TW is on → show all true whitespace again
    if (topTwActive && cls !== "true_whitespace") {
      const set = new Set<MarketClass>(["true_whitespace", cls]);
      disableTopTrueWhitespace({
        marketClasses: [...set],
        hideOtherClasses: true,
      });
      return;
    }

    const set = new Set(filters.marketClasses);
    if (set.has(cls)) {
      set.delete(cls);
      // Turning off true whitespace also clears the top-TW filter
      if (cls === "true_whitespace" && topTwActive) {
        disableTopTrueWhitespace({
          marketClasses: [...set],
          hideOtherClasses: false,
        });
        return;
      }
    } else {
      set.add(cls);
    }
    setFilters({ marketClasses: [...set] });
  };

  const toggleOther = (cls: MarketClass) => {
    // Checking any choropleth class while top-TW is on → exit top mode, keep all TW + this class
    if (topTwActive) {
      disableTopTrueWhitespace({
        marketClasses: ["true_whitespace", cls],
        hideOtherClasses: false,
      });
      return;
    }

    if (otherSelected.length === 0 && !filters.hideOtherClasses) {
      // Was "all others" → turn off this one, keep opt-ins
      setFilters({
        marketClasses: [...OTHER_MARKET_CLASSES.filter((c) => c !== cls), ...optInSelected],
        hideOtherClasses: false,
      });
      return;
    }

    const set = new Set(otherSelected);
    if (set.has(cls)) set.delete(cls);
    else set.add(cls);

    if (set.size === 0) {
      setFilters({ marketClasses: [...optInSelected], hideOtherClasses: true });
    } else if (set.size === OTHER_MARKET_CLASSES.length && !filters.hideOtherClasses) {
      setFilters({ marketClasses: [...optInSelected], hideOtherClasses: false });
    } else {
      setFilters({ marketClasses: [...set, ...optInSelected], hideOtherClasses: false });
    }
  };

  const isOtherChecked = (cls: MarketClass) => {
    if (topTwActive) return false;
    if (filters.hideOtherClasses && otherSelected.length === 0) return false;
    return otherSelected.length === 0 || otherSelected.includes(cls);
  };

  const thr =
    topTwActive && meta?.true_whitespace_top_thresholds
      ? meta.true_whitespace_top_thresholds[String(topTwPct)]
      : null;

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <h2>Filters</h2>
        <button
          type="button"
          className="linkish"
          onClick={() => {
            resetFilters();
            setToggles(DEFAULT_TOGGLES);
          }}
        >
          Reset
        </button>
      </div>

      <div className="filter-block top-tw-filter">
        <div className="filter-label">Top true whitespace</div>
        <p className="muted tiny" style={{ margin: "0 0 8px" }}>
          Focus the map on the highest-scoring true whitespace only (by opportunity score within
          that class). Turns off proven market, competitive infill, weak whitespace, and other
          classes. Checking any other market class clears this and shows <em>all</em> true
          whitespace again.
        </p>
        <label className="check">
          <input
            type="checkbox"
            checked={topTwActive}
            onChange={(e) => {
              if (e.target.checked) enableTopTrueWhitespace(topTwPct);
              else
                disableTopTrueWhitespace({
                  marketClasses: filters.marketClasses.includes("true_whitespace")
                    ? ["true_whitespace"]
                    : [],
                  hideOtherClasses: false,
                });
            }}
          />
          Show only top
          <select
            className="inline-select"
            value={topTwPct}
            onChange={(e) => {
              const pct = Number(e.target.value) as TopTrueWhitespacePct;
              enableTopTrueWhitespace(pct);
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {TOP_TW_OPTIONS.map((p) => (
              <option key={p} value={p}>
                {p}%
              </option>
            ))}
          </select>
          of true whitespace
        </label>
        {topTwActive && thr != null && (
          <p className="muted tiny" style={{ margin: "6px 0 0" }}>
            Active — opportunity score ≥ {thr.toFixed(0)} (top {topTwPct}% of true whitespace).
          </p>
        )}
      </div>

      <div className="filter-block">
        <div className="filter-label">Urban / rural</div>
        {(["all", "urban", "rural"] as const).map((v) => (
          <label key={v} className="check">
            <input
              type="radio"
              name="ur"
              checked={filters.urbanRural === v}
              onChange={() => setFilters({ urbanRural: v })}
            />
            {v}
          </label>
        ))}
      </div>

      <div className="filter-block">
        <div className="filter-label-row">
          <div className="filter-label" style={{ marginBottom: 0 }}>
            Market class
          </div>
          <button type="button" className="define-btn" onClick={() => setDefsOpen(true)}>
            Define these
          </button>
        </div>
        <p className="muted tiny" style={{ margin: "6px 0 8px" }}>
          All classes start checked on load. True whitespace &amp; Proven market are overlays — uncheck
          to hide.
        </p>
        {(Object.keys(MARKET_CLASS_STYLE) as MarketClass[])
          .filter((cls) => cls !== "pending_routing")
          .map((cls) => {
          const optIn = isOptInMarketClass(cls);
          const checked = optIn
            ? filters.marketClasses.includes(cls)
            : isOtherChecked(cls);
          return (
            <label key={cls} className="check">
              <input
                type="checkbox"
                checked={checked}
                onChange={() => (optIn ? toggleOptIn(cls) : toggleOther(cls))}
              />
              <span className="swatch" style={{ background: MARKET_CLASS_STYLE[cls].color }} />
              {MARKET_CLASS_STYLE[cls].label}
            </label>
          );
          })}
        {(otherSelected.length > 0 ||
          optInSelected.length > 0 ||
          filters.hideOtherClasses ||
          topTwActive) && (
          <button
            type="button"
            className="linkish"
            onClick={() =>
              setFilters({
                marketClasses: [],
                topTrueWhitespacePct: null,
                hideOtherClasses: false,
              })
            }
          >
            Clear class filter
          </button>
        )}
      </div>

      <h2>Layers</h2>
      <label className="check">
        <input
          type="checkbox"
          checked={toggles.whitespaceSpotlight}
          onChange={(e) => setToggles({ whitespaceSpotlight: e.target.checked })}
        />
        Whitespace spotlight
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={toggles.clusters}
          onChange={(e) => setToggles({ clusters: e.target.checked })}
        />
        Whitespace cluster markers
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={toggles.networkStores}
          onChange={(e) => setToggles({ networkStores: e.target.checked })}
        />
        Pet Valu network
      </label>
      {(Object.keys(COMPETITOR_TYPE_STYLE) as CompetitorType[]).map((t) => (
        <label key={t} className="check">
          <input
            type="checkbox"
            checked={toggles.competitorTypes[t]}
            onChange={(e) =>
              setToggles({
                competitorTypes: { ...toggles.competitorTypes, [t]: e.target.checked },
              })
            }
          />
          <span className="swatch" style={{ background: COMPETITOR_TYPE_STYLE[t].color }} />
          {COMPETITOR_TYPE_STYLE[t].label}
        </label>
      ))}
      <label className="check">
        <input
          type="checkbox"
          checked={toggles.postalPoints}
          onChange={(e) => setToggles({ postalPoints: e.target.checked })}
        />
        Postal points (high zoom)
      </label>

      <div className="more-filters">
        <button
          type="button"
          className="more-filters-toggle"
          aria-expanded={moreOpen}
          onClick={() => setMoreOpen((v) => !v)}
        >
          <span>More filters</span>
          <span className="muted">{moreOpen ? "▾" : "▸"} range sliders</span>
        </button>
        {moreOpen && (
          <div className="more-filters-body">
            <Range
              label="Demand percentile"
              min={0}
              max={1}
              step={0.05}
              value={filters.demandPctRange}
              onChange={(demandPctRange) => setFilters({ demandPctRange })}
            />
            <Range
              label="Nearest PV minutes"
              min={0}
              max={240}
              step={5}
              value={filters.nearestPvMinutesRange}
              onChange={(nearestPvMinutesRange) => setFilters({ nearestPvMinutesRange })}
            />
            <Range
              label="Competitor intensity"
              min={0}
              max={20}
              step={0.5}
              value={[
                filters.competitorIntensityRange[0],
                Math.min(filters.competitorIntensityRange[1], 20),
              ]}
              onChange={(competitorIntensityRange) =>
                setFilters({
                  competitorIntensityRange: [
                    competitorIntensityRange[0],
                    competitorIntensityRange[1] >= 20 ? 999 : competitorIntensityRange[1],
                  ],
                })
              }
            />
            <Range
              label="Opportunity score"
              min={0}
              max={100}
              step={1}
              value={filters.opportunityScoreRange}
              onChange={(opportunityScoreRange) => setFilters({ opportunityScoreRange })}
            />
          </div>
        )}
      </div>

      {defsOpen && <ClassDefinitionsModal onClose={() => setDefsOpen(false)} />}
    </aside>
  );
}
