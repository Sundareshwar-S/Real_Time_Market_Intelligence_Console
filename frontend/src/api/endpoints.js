const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:5000";

export const endpoints = {
  data: `${API_BASE}/api/data`,
  latest: `${API_BASE}/api/latest`,
  forecast: `${API_BASE}/api/forecast`,
  correlation: `${API_BASE}/api/correlation`,
  anomalies: `${API_BASE}/api/anomalies`,
  marketSeries: `${API_BASE}/api/series/market`,
  websocketStatus: `${API_BASE}/api/websocket/status`,
  start: `${API_BASE}/api/start`,
  stop: `${API_BASE}/api/stop`,
  runTask: `${API_BASE}/api/run-task`,
};

function normalizeQueryValue(value) {
  if (value == null) {
    return null;
  }
  if (value instanceof Date) {
    return value.toISOString();
  }
  if (typeof value === "string") {
    const normalized = value.trim();
    return normalized === "" ? null : normalized;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : null;
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return String(value);
}

export function buildEndpointUrl(baseUrl, query = {}) {
  const defaultOrigin =
    typeof window !== "undefined" && window.location?.origin
      ? window.location.origin
      : "http://localhost";
  const url = new URL(baseUrl, defaultOrigin);
  const entries = Object.entries(query || {});

  for (const [key, rawValue] of entries) {
    const values = Array.isArray(rawValue) ? rawValue : [rawValue];
    for (const value of values) {
      const normalized = normalizeQueryValue(value);
      if (normalized == null) {
        continue;
      }
      url.searchParams.append(key, normalized);
    }
  }

  return url.toString();
}

export function buildReadEndpoint(endpointKey, query = {}) {
  const baseUrl = endpoints[endpointKey];
  if (!baseUrl) {
    throw new Error(`Unknown read endpoint: ${endpointKey}`);
  }
  return buildEndpointUrl(baseUrl, query);
}

export const socketEndpoint = import.meta.env.VITE_SOCKET_URL ?? API_BASE;
