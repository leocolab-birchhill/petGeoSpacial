import { useEffect, useState } from "react";
import TopBar from "./components/TopBar/TopBar";
import FilterSidebar from "./components/FilterSidebar/FilterSidebar";
import MapView from "./components/MapView/MapView";
import DetailPanel from "./components/DetailPanel/DetailPanel";
import BottomBar from "./components/BottomBar/BottomBar";
import Dashboard from "./components/Dashboard/Dashboard";
import HowToUseModal from "./components/HowToUseModal";
import { useAppState } from "./state/useAppState";
import { getMap } from "./lib/mapRef";

export default function App() {
  const selection = useAppState((s) => s.selection);
  const tab = useAppState((s) => s.tab);
  const onMap = tab === "map";
  // Open on every load / refresh; Help button reopens
  const [howToOpen, setHowToOpen] = useState(true);
  const [exploredDashboard, setExploredDashboard] = useState(false);
  const [showDashboardHint, setShowDashboardHint] = useState(false);

  useEffect(() => {
    if (!onMap) return;
    const t = window.setTimeout(() => getMap()?.resize(), 50);
    return () => window.clearTimeout(t);
  }, [onMap, selection]);

  useEffect(() => {
    if (tab === "dashboard") {
      setExploredDashboard(true);
      setShowDashboardHint(false);
    }
  }, [tab]);

  const closeHelp = () => {
    setHowToOpen(false);
    if (!exploredDashboard) setShowDashboardHint(true);
  };

  return (
    <div
      className={onMap ? "app-grid" : "app-dashboard"}
      data-has-selection={onMap && selection ? "true" : "false"}
    >
      <TopBar
        onOpenHelp={() => setHowToOpen(true)}
        showDashboardHint={showDashboardHint}
      />
      {onMap && <FilterSidebar />}
      <div className={onMap ? "map-container" : "map-parked"}>
        <MapView />
      </div>
      {onMap && selection && <DetailPanel />}
      {onMap && <BottomBar />}
      {!onMap && <Dashboard />}
      {howToOpen && <HowToUseModal onClose={closeHelp} />}
    </div>
  );
}
