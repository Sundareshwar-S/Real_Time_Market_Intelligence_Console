import { NavLink } from "react-router-dom";
import { useAppStore } from "../../store/store";
import { navigationItems } from "./navigation";

const navClassName = ({ isActive }) =>
  `nav-item${isActive ? " active" : ""}`;

export default function SideNav() {
  const anomalyCount = useAppStore((s) => s.anomalies.events.length);

  return (
    <aside className="sidebar">
      <div className="brand-block">
        <div className="brand-logo">
          <span className="material-symbols-outlined">terminal</span>
        </div>
        <div>
          <h1>Intelligence</h1>
          <p>Kinetic v2.4</p>
        </div>
      </div>

      <nav className="nav-list">
        {navigationItems.map((item) => (
          <NavLink key={item.path} to={item.path} className={navClassName}>
            <span className="material-symbols-outlined">{item.icon}</span>
            <span>{item.label}</span>
            {item.path === "/anomalies" && anomalyCount > 0 ? (
              <span className="badge">{Math.min(anomalyCount, 99)}</span>
            ) : null}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
