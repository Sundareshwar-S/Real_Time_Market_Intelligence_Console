import { Outlet } from "react-router-dom";
import SideNav from "./SideNav";
import TopBar from "./TopBar";

export default function AppShell() {
  return (
    <div className="app-shell">
      <TopBar />
      <SideNav />
      <main className="main-area">
        <Outlet />
      </main>
    </div>
  );
}
