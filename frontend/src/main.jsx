import React from "react";
import ReactDOM from "react-dom/client";
import App from "./app";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import "./styles/style.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
