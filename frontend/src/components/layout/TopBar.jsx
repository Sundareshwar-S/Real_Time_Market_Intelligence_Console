import { toggleTheme, useAppStore } from "../../store/store";

export default function TopBar() {
  const connected = useAppStore((s) => s.connection.connected);
  const schedulerRunning = useAppStore((s) => s.scheduler.running);
  const streamActive = useAppStore((s) => s.stream.active);
  const theme = useAppStore((s) => s.theme);

  const isHealthy = connected && schedulerRunning;
  const statusLabel = !connected
    ? "Disconnected"
    : !schedulerRunning
      ? "Scheduler stopped"
      : streamActive
        ? "Live"
        : "Connected";
  const nextThemeLabel = theme === "dark" ? "light" : "dark";

  return (
    <header className="topbar">
      <div className="topbar-title">Data Intelligence Hub</div>

      <div className="topbar-actions">
        <span
          className={`dot-indicator ${isHealthy ? "online" : "offline"}`}
          title={statusLabel}
        />
        <button
          type="button"
          aria-label={`Switch to ${nextThemeLabel} mode`}
          title={`Switch to ${nextThemeLabel} mode`}
          onClick={toggleTheme}
        >
          <span className="material-symbols-outlined">
            {theme === "dark" ? "light_mode" : "dark_mode"}
          </span>
        </button>
        <button type="button" aria-label="Notifications">
          <span className="material-symbols-outlined">notifications</span>
        </button>
      </div>
    </header>
  );
}
