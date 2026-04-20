import { useLocation } from "react-router-dom";
import { setSearchQuery, useAppStore } from "../../store/store";

const searchHints = {
  "/overview": "Search markets, assets, anomalies...",
  "/markets": "Search ticker or asset...",
  "/anomalies": "Search anomalies, vectors, logs...",
  "/forecasts": "Search models and forecasts...",
};

export default function TopBar() {
  const location = useLocation();
  const query = useAppStore((s) => s.query);
  const connected = useAppStore((s) => s.connection.connected);
  const schedulerRunning = useAppStore((s) => s.scheduler.running);
  const streamActive = useAppStore((s) => s.stream.active);
  const placeholder =
    searchHints[location.pathname] ?? "Search the kinetic vault...";

  const isHealthy = connected && schedulerRunning;
  const statusLabel = !connected
    ? "Disconnected"
    : !schedulerRunning
      ? "Scheduler stopped"
      : streamActive
        ? "Live"
        : "Connected";

  return (
    <header className="topbar">
      <div className="topbar-title">The Kinetic Vault</div>

      <div className="search-input">
        <span className="material-symbols-outlined">search</span>
        <input
          type="text"
          placeholder={placeholder}
          value={query}
          onChange={(event) => setSearchQuery(event.target.value)}
        />
      </div>

      <div className="topbar-actions">
        <span
          className={`dot-indicator ${isHealthy ? "online" : "offline"}`}
          title={statusLabel}
        />
        <button type="button" aria-label="Notifications">
          <span className="material-symbols-outlined">notifications</span>
        </button>
        <button type="button" aria-label="Settings">
          <span className="material-symbols-outlined">settings</span>
        </button>
        <div className="avatar">KV</div>
      </div>
    </header>
  );
}
