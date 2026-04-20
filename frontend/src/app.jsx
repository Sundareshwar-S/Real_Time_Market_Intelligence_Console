import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Suspense, lazy, useEffect, useState } from "react";
import AppShell from "./components/layout/AppShell";
import { LoadingOverlay } from "./components/common/ErrorBoundary";
import { initializeRealtimeApp, shutdownRealtimeApp, useAppStore } from "./store/store";

const OverviewPage = lazy(() => import("./pages/overview"));
const MarketsPage = lazy(() => import("./pages/markets"));
const AnomaliesPage = lazy(() => import("./pages/anomalies"));
const ForecastsPage = lazy(() => import("./pages/forecasts"));

export default function App() {
  const [initializing, setInitializing] = useState(true);
  const initialized = useAppStore((s) => s.initialized);

  useEffect(() => {
    initializeRealtimeApp();
    return () => {
      shutdownRealtimeApp();
    };
  }, []);

  useEffect(() => {
    if (initialized) {
      // Allow a brief moment for the first render to settle
      const timer = setTimeout(() => setInitializing(false), 400);
      return () => clearTimeout(timer);
    }
  }, [initialized]);

  return (
    <>
      <LoadingOverlay visible={initializing} />
      <BrowserRouter>
        <Suspense fallback={<LoadingOverlay visible={true} />}>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<Navigate to="/overview" replace />} />
              <Route path="/overview" element={<OverviewPage />} />
              <Route path="/markets" element={<MarketsPage />} />
              <Route path="/anomalies" element={<AnomaliesPage />} />
              <Route path="/forecasts" element={<ForecastsPage />} />
              <Route path="*" element={<Navigate to="/overview" replace />} />
            </Route>
          </Routes>
        </Suspense>
      </BrowserRouter>
    </>
  );
}
