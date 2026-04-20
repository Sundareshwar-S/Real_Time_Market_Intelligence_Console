import { useSyncExternalStore } from "react";
import { buildReadEndpoint, endpoints } from "../api/endpoints";
import { get, post } from "../api/restClient";
import { createSocket } from "../api/socketClient";

const MAX_MARKET_ITEMS = 240;
const MAX_SERIES_POINTS = 400;
const MAX_EVENT_ITEMS = 2000;
const DEFAULT_TIME_RANGE = "30d";
const VALID_TIME_RANGES = new Set(["30d", "1y", "4y"]);
const DEFAULT_ANOMALY_WINDOW = "24h";
const VALID_ANOMALY_WINDOWS = new Set(["24h", "7d", "30d"]);
const BUCKET_FOR_RANGE = { "30d": "1h", "1y": "1d", "4y": "1m" };
const CONTEXT_SOURCE_MAP = {
  crypto: "crypto",
  stock: "stock",
};
const CONTEXT_SOURCE_ALIASES = {
  crypto: ["crypto", "freecryptoapi"],
  stock: ["stock", "polygon"],
};

function resolveSeriesBucket(context, timeRange) {
  const normalizedContext = normalizeContext(context);
  const normalizedRange = normalizeTimeRange(timeRange);
  if (normalizedContext === "stock" && normalizedRange === "30d") {
    return "1d";
  }
  return BUCKET_FOR_RANGE[normalizedRange] || "1h";
}

const state = {
  context: "all",
  timeRange: DEFAULT_TIME_RANGE,
  anomalyWindow: DEFAULT_ANOMALY_WINDOW,
  query: "",
  theme: "dark",
  initialized: false,
  connection: {
    connected: false,
    status: "idle",
    transport: "socketio",
    connectedClients: 0,
    reconnectAttempts: 0,
    lastHeartbeatAt: null,
    lastError: null,
  },
  stream: {
    active: false,
    intervalSeconds: 2,
  },
  market: {
    items: [],
    updatedAt: null,
    source: "database",
    globalCryptoMarketCap: null,
    globalCryptoMarketCapSource: null,
    selectedCryptoSymbol: null,
    selectedStockSymbol: null,
  },
  anomalies: {
    events: [],
    updatedAt: null,
  },
  forecasts: {
    predictions: [],
    updatedAt: null,
  },
  scheduler: {
    running: false,
    recentJobs: [],
    scheduledJobs: [],
  },
  freshness: [],
  charts: {
    marketSeries: [],
    anomalySeries: [],
    forecastSeries: [],
  },
  ui: {
    loading: false,
    lastSyncAt: null,
    error: null,
  },
};

const listeners = new Set();
let socket = null;
let heartbeatTimer = null;
let bootstrapPromise = null;

function notify() {
  listeners.forEach((listener) => listener());
}

function update(mutator) {
  mutator(state);
  notify();
}

function toFiniteNumber(value) {
  if (value == null) {
    return null;
  }
  if (typeof value === "string" && value.trim() === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function toNumber(value) {
  return toFiniteNumber(value) ?? 0;
}

function parseTimestamp(value, fallback = null) {
  if (!value) {
    return fallback;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return fallback;
  }
  return date.toISOString();
}

function normalizeContext(context) {
  const normalized = String(context || "all").toLowerCase();
  if (normalized === "all" || CONTEXT_SOURCE_MAP[normalized]) {
    return normalized;
  }
  return "all";
}

function normalizeTimeRange(timeRange) {
  const normalized = String(timeRange || "").toLowerCase();
  return VALID_TIME_RANGES.has(normalized) ? normalized : DEFAULT_TIME_RANGE;
}

function normalizeAnomalyWindow(window) {
  const normalized = String(window || "").toLowerCase();
  return VALID_ANOMALY_WINDOWS.has(normalized) ? normalized : DEFAULT_ANOMALY_WINDOW;
}

function resolveContextSource(context) {
  const normalizedContext = normalizeContext(context);
  return CONTEXT_SOURCE_MAP[normalizedContext] ?? null;
}

function resolveContextSources(context) {
  const normalizedContext = normalizeContext(context);
  if (normalizedContext === "all") {
    return [null];
  }
  const aliases = CONTEXT_SOURCE_ALIASES[normalizedContext] || [];
  return aliases.length ? [...new Set(aliases)] : [resolveContextSource(normalizedContext)];
}

function resolveSourceCategory(source) {
  const normalizedSource = String(source || "").toLowerCase();
  if (normalizedSource.includes("crypto")) {
    return "crypto";
  }
  if (normalizedSource.includes("stock") || normalizedSource.includes("polygon")) {
    return "stock";
  }
  return null;
}

function normalizeMarketCategory(category) {
  const normalizedCategory = String(category || "").toLowerCase();
  if (normalizedCategory === "crypto" || normalizedCategory === "stock") {
    return normalizedCategory;
  }
  return null;
}

function getItemsByCategory(items, category) {
  const normalizedCategory = normalizeMarketCategory(category);
  if (!normalizedCategory) {
    return [];
  }
  return items.filter((item) => resolveSourceCategory(item.source) === normalizedCategory);
}

function pickPreferredSymbol(items, preferredSymbol) {
  if (!items.length) {
    return null;
  }
  const preferred = String(preferredSymbol || "").toUpperCase();
  if (preferred && items.some((item) => item.symbol === preferred)) {
    return preferred;
  }
  const ranked = items
    .slice()
    .sort((left, right) => {
      const rightCap = toFiniteNumber(right.market_cap) ?? -1;
      const leftCap = toFiniteNumber(left.market_cap) ?? -1;
      if (rightCap !== leftCap) {
        return rightCap - leftCap;
      }
      const rightVolume = toFiniteNumber(right.volume_24h) ?? -1;
      const leftVolume = toFiniteNumber(left.volume_24h) ?? -1;
      if (rightVolume !== leftVolume) {
        return rightVolume - leftVolume;
      }
      return String(left.symbol || "").localeCompare(String(right.symbol || ""));
    });
  return String(ranked[0]?.symbol || "").toUpperCase() || null;
}

function reconcileSelectedMarketSymbols() {
  const cryptoItems = getItemsByCategory(state.market.items, "crypto");
  const stockItems = getItemsByCategory(state.market.items, "stock");
  state.market.selectedCryptoSymbol = pickPreferredSymbol(
    cryptoItems,
    state.market.selectedCryptoSymbol
  );
  state.market.selectedStockSymbol = pickPreferredSymbol(
    stockItems,
    state.market.selectedStockSymbol
  );
}

function getMarketBucketTimestamp(timestamp, timeRange = state.timeRange) {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }

  const normalizedRange = normalizeTimeRange(timeRange);
  const bucketSize = resolveSeriesBucket(state.context, normalizedRange);
  const bucket = new Date(parsed);

  if (bucketSize === "1h") {
    bucket.setUTCMinutes(0, 0, 0);
  } else if (bucketSize === "4h") {
    const currentHour = bucket.getUTCHours();
    bucket.setUTCHours(Math.floor(currentHour / 4) * 4, 0, 0, 0);
  } else if (bucketSize === "1d") {
    bucket.setUTCHours(0, 0, 0, 0);
  } else if (bucketSize === "1w") {
    bucket.setUTCHours(0, 0, 0, 0);
    const dayOfWeek = (bucket.getUTCDay() + 6) % 7;
    bucket.setUTCDate(bucket.getUTCDate() - dayOfWeek);
  } else {
    bucket.setUTCHours(0, 0, 0, 0);
    bucket.setUTCDate(1);
  }

  return bucket.toISOString();
}

export function getTimeRangeWindow(timeRange, referenceTime = new Date()) {
  const selectedRange = normalizeTimeRange(timeRange);
  const end = new Date(referenceTime);
  const start = new Date(referenceTime);

  if (selectedRange === "1y") {
    start.setUTCFullYear(start.getUTCFullYear() - 1);
  } else if (selectedRange === "4y") {
    start.setUTCFullYear(start.getUTCFullYear() - 4);
  } else {
    start.setUTCDate(start.getUTCDate() - 30);
  }

  return {
    start_time: start.toISOString(),
    end_time: end.toISOString(),
  };
}

function getAnomalyWindowRange(anomalyWindow, referenceTime = new Date()) {
  const selectedWindow = normalizeAnomalyWindow(anomalyWindow);
  const end = new Date(referenceTime);
  const start = new Date(referenceTime);
  if (selectedWindow === "30d") {
    start.setUTCDate(start.getUTCDate() - 30);
  } else if (selectedWindow === "7d") {
    start.setUTCDate(start.getUTCDate() - 7);
  } else {
    start.setUTCHours(start.getUTCHours() - 24);
  }
  return {
    start_time: start.toISOString(),
    end_time: end.toISOString(),
  };
}

function getAnomalyBucketTimestamp(timestamp, anomalyWindow = state.anomalyWindow) {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  const bucket = new Date(parsed);
  const selectedWindow = normalizeAnomalyWindow(anomalyWindow);
  if (selectedWindow === "24h") {
    bucket.setUTCMinutes(0, 0, 0);
  } else if (selectedWindow === "7d") {
    bucket.setUTCHours(Math.floor(bucket.getUTCHours() / 6) * 6, 0, 0, 0);
  } else {
    bucket.setUTCHours(0, 0, 0, 0);
  }
  return bucket.toISOString();
}

function buildReadFilters({ context = state.context, timeRange = state.timeRange } = {}) {
  const sources = resolveContextSources(context);
  const timeWindow = getTimeRangeWindow(timeRange);
  const buildSourceQueries = (baseQuery = {}) =>
    sources.map((source) => (source ? { ...baseQuery, source } : { ...baseQuery }));

  return { timeWindow, sources, buildSourceQueries };
}

function buildBootstrapEndpoints(filters = {}) {
  const context = normalizeContext(filters.context ?? state.context);
  const { timeWindow, buildSourceQueries } = buildReadFilters(filters);
  const anomalyWindow = normalizeAnomalyWindow(filters.anomalyWindow ?? state.anomalyWindow);
  const anomalyWindowRange = getAnomalyWindowRange(anomalyWindow);
  const anomalyLimit = anomalyWindow === "30d" ? 2500 : anomalyWindow === "7d" ? 1200 : 500;
  const analyticsLimit = normalizeTimeRange(filters.timeRange ?? state.timeRange) === "1y" ? 5000 : 2000;
  const anomalyEndpoints = buildSourceQueries({
    ...anomalyWindowRange,
    anomalies_only: true,
    limit: anomalyLimit,
  }).map((query) => {
    // Anomalies always have source="processing", not crypto/stock.
    // Remove source filter so we actually get results.
    const { source, ...rest } = query;
    return buildReadEndpoint("anomalies", rest);
  });
  const dedupedAnomalyEndpoints = [...new Set(anomalyEndpoints)];

  return {
    data: buildSourceQueries({ ...timeWindow, limit: 500 }).map((query) =>
      buildReadEndpoint("data", query)
    ),
    marketSeries: buildReadEndpoint("marketSeries", {
      ...timeWindow,
      context,
      bucket: resolveSeriesBucket(context, normalizeTimeRange(filters.timeRange ?? state.timeRange)),
      max_points: MAX_SERIES_POINTS,
    }),
    forecast: buildReadEndpoint("forecast", { ...timeWindow, limit: analyticsLimit }),
    anomalies: dedupedAnomalyEndpoints,
    websocketStatus: buildReadEndpoint("websocketStatus"),
  };
}

function trimList(items, maxItems) {
  return items.slice(0, maxItems);
}

function mergeByKey(existing, incoming, keyFn, maxItems) {
  if (!incoming.length && existing.length <= maxItems) {
    return existing;
  }
  const resolveRecordTimestamp = (row) =>
    new Date(row.captured_at || row.timestamp || row.triggered_at || 0).getTime();
  const map = new Map();
  for (const row of existing) {
    map.set(keyFn(row), row);
  }
  for (const row of incoming) {
    const key = keyFn(row);
    const current = map.get(key);
    if (!current || resolveRecordTimestamp(row) >= resolveRecordTimestamp(current)) {
      map.set(key, row);
    }
  }
  const merged = [...map.values()].sort((a, b) => {
    const left = new Date(b.captured_at || b.timestamp || b.triggered_at || 0).getTime();
    const right = new Date(a.captured_at || a.timestamp || a.triggered_at || 0).getTime();
    return left - right;
  });
  return trimList(merged, maxItems);
}

function buildMarketSeriesPoint(items, timestamp) {
  const point = {
    timestamp,
    total: null,
    crypto: null,
    stock: null,
  };
  for (const item of items) {
    const value = toFiniteNumber(item.value);
    if (value == null) {
      continue;
    }
    point.total = (point.total ?? 0) + value;
    const sourceCategory = resolveSourceCategory(item.source);
    if (sourceCategory) {
      point[sourceCategory] = (point[sourceCategory] ?? 0) + value;
    }
  }
  return point.total == null ? null : point;
}

function appendMarketSeries(items, timestamp) {
  if (!items.length) {
    return;
  }
  const bucketTimestamp = getMarketBucketTimestamp(timestamp) || timestamp;
  const point = buildMarketSeriesPoint(items, bucketTimestamp);
  if (!point) {
    return;
  }
  const seriesByBucket = new Map(
    state.charts.marketSeries.map((entry) => [entry.timestamp, entry])
  );
  seriesByBucket.set(bucketTimestamp, point);
  state.charts.marketSeries = [...seriesByBucket.values()]
    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
    .slice(-MAX_SERIES_POINTS);
}

function buildHistoricalMarketSeries(rows, timeRange = state.timeRange) {
  const normalizedRows = normalizeMarketItems(rows, "database")
    .filter((item) => item.value != null)
    .sort((a, b) => new Date(a.captured_at).getTime() - new Date(b.captured_at).getTime());

  const bucketed = new Map();
  for (const row of normalizedRows) {
    const bucketTimestamp = getMarketBucketTimestamp(row.captured_at, timeRange);
    if (!bucketTimestamp) {
      continue;
    }
    if (!bucketed.has(bucketTimestamp)) {
      bucketed.set(bucketTimestamp, new Map());
    }
    const bucketRows = bucketed.get(bucketTimestamp);
    bucketRows.set(`${row.source}:${row.symbol}`, row);
  }

  return [...bucketed.entries()]
    .sort((a, b) => new Date(a[0]).getTime() - new Date(b[0]).getTime())
    .map(([bucketTimestamp, bucketRows]) =>
      buildMarketSeriesPoint([...bucketRows.values()], bucketTimestamp)
    )
    .filter(Boolean)
    .slice(-MAX_SERIES_POINTS);
}

function normalizeMarketSeriesPoints(points) {
  return (points || [])
    .map((point) => ({
      timestamp: parseTimestamp(point?.timestamp),
      total: toFiniteNumber(point?.total),
      crypto: toFiniteNumber(point?.crypto),
      stock: toFiniteNumber(point?.stock),
    }))
    .filter((point) => point.timestamp && point.total != null)
    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
    .slice(-MAX_SERIES_POINTS);
}

function buildHistoricalAnomalySeries(events, anomalyWindow = state.anomalyWindow) {
  const windowRange = getAnomalyWindowRange(anomalyWindow);
  const startMs = new Date(windowRange.start_time).getTime();
  const endMs = new Date(windowRange.end_time).getTime();
  const bucketed = new Map();
  for (const event of events) {
    const eventMs = new Date(event.timestamp || 0).getTime();
    if (!Number.isFinite(eventMs) || eventMs < startMs || eventMs > endMs) {
      continue;
    }
    const bucketTimestamp = getAnomalyBucketTimestamp(event.timestamp, anomalyWindow);
    if (!bucketTimestamp) {
      continue;
    }
    const severity = String(event.severity || "low").toLowerCase();
    if (!bucketed.has(bucketTimestamp)) {
      bucketed.set(bucketTimestamp, { timestamp: bucketTimestamp, high: 0, medium: 0, low: 0, total: 0 });
    }
    const point = bucketed.get(bucketTimestamp);
    if (severity === "high") {
      point.high += 1;
    } else if (severity === "medium") {
      point.medium += 1;
    } else {
      point.low += 1;
    }
    point.total += 1;
  }
  return [...bucketed.values()]
    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
    .slice(-MAX_SERIES_POINTS);
}

function calculateStdDev(values) {
  if (!values.length) {
    return 0;
  }
  const mean = values.reduce((acc, value) => acc + value, 0) / values.length;
  const variance =
    values.reduce((acc, value) => acc + (value - mean) ** 2, 0) / values.length;
  return Math.sqrt(variance);
}

function applyForecastSeries(predictions) {
  const normalized = predictions
    .map((row) => ({
      ...row,
      symbol: String(row.symbol || "").toUpperCase(),
      horizon_step: toNumber(row.horizon_step || 0),
      predicted_value: toNumber(row.predicted_value),
      lower_bound: row.lower_bound == null ? null : toNumber(row.lower_bound),
      upper_bound: row.upper_bound == null ? null : toNumber(row.upper_bound),
      unit: row.unit ? String(row.unit).toUpperCase() : null,
      created_at: parseTimestamp(row.created_at),
      generated_at: parseTimestamp(row.generated_at),
    }))
    .filter((row) => row.symbol && row.horizon_step > 0 && row.generated_at);

  const latestByRun = new Map();
  for (const row of normalized) {
    const key = `${row.symbol}:${row.horizon_step}:${row.generated_at}`;
    const current = latestByRun.get(key);
    const rowTs = new Date(row.created_at || row.generated_at || 0).getTime();
    const currentTs = new Date(current?.created_at || current?.generated_at || 0).getTime();
    if (!current || rowTs >= currentTs) {
      latestByRun.set(key, row);
    }
  }

  const deduped = [...latestByRun.values()];
  const symbolRows = new Map();
  for (const row of deduped) {
    if (row.horizon_step !== 1) {
      continue;
    }
    if (!symbolRows.has(row.symbol)) {
      symbolRows.set(row.symbol, []);
    }
    symbolRows.get(row.symbol).push(row);
  }

  let bestSymbol = null;
  let bestScore = -1;
  for (const [symbol, rows] of symbolRows.entries()) {
    const ordered = rows
      .slice()
      .sort((a, b) => new Date(a.generated_at).getTime() - new Date(b.generated_at).getTime());
    const values = ordered.map((row) => row.predicted_value).filter((value) => Number.isFinite(value));
    const variability = calculateStdDev(values);
    const score = values.length * 1000 + variability;
    if (score > bestScore) {
      bestScore = score;
      bestSymbol = symbol;
    }
  }

  let series = deduped
    .filter((row) => row.symbol === bestSymbol && row.horizon_step === 1)
    .sort((a, b) => new Date(a.generated_at).getTime() - new Date(b.generated_at).getTime())
    .map((row) => ({
      timestamp: row.generated_at,
      predicted: row.predicted_value,
      lower: row.lower_bound,
      upper: row.upper_bound,
        source: "forecast",
      }));

  state.charts.forecastSeries = series.slice(-MAX_SERIES_POINTS);
}

function normalizeMarketItems(rows, sourceHint = "stream") {
  return rows
    .map((row) => {
      const rawSource = String(row.source || sourceHint).toLowerCase();
      const normalizedSource = resolveSourceCategory(rawSource) || rawSource;
      const numericValue = toFiniteNumber(row.value == null ? row.price : row.value);
      const sourceCategory = resolveSourceCategory(normalizedSource);
      const sanitizedValue =
        numericValue === 0 && (sourceCategory === "crypto" || sourceCategory === "stock")
          ? null
          : numericValue;
      return {
        symbol: String(row.symbol || "").toUpperCase(),
        name: row.name || row.symbol,
        source: normalizedSource,
        value: sanitizedValue,
        change_24h: row.change_24h == null ? null : toFiniteNumber(row.change_24h),
        volume_24h: row.volume_24h == null ? null : toFiniteNumber(row.volume_24h),
        market_cap: row.market_cap == null ? null : toFiniteNumber(row.market_cap),
        captured_at: parseTimestamp(row.captured_at, new Date().toISOString()),
      };
    })
    .filter((item) => item.symbol && item.value != null);
}

function applyMarketRows(rows, source = "stream", replace = false, timestamp = new Date().toISOString()) {
  const incoming = normalizeMarketItems(rows, source);
  if (replace) {
    state.market.items = mergeByKey(
      [],
      incoming,
      (row) => `${row.source}:${row.symbol}`,
      MAX_MARKET_ITEMS
    );
  } else {
    state.market.items = mergeByKey(
      state.market.items,
      incoming,
      (row) => `${row.source}:${row.symbol}`,
      MAX_MARKET_ITEMS
    );
  }
  reconcileSelectedMarketSymbols();
  state.market.updatedAt = timestamp;
  state.market.source = source;
  appendMarketSeries(state.market.items, timestamp);
}

function normalizeAnomalyEvents(rows, sourceHint = "processing") {
  return rows
    .map((row) => ({
      id: row.id || `${row.symbol || "UNK"}:${row.timestamp || ""}:${row.score || row.anomaly_score || ""}`,
      symbol: String(row.symbol || "").toUpperCase(),
      source: String(row.source || sourceHint).toLowerCase(),
      type: row.type || row.anomaly_type || "volatility",
      score: toNumber(row.score == null ? row.anomaly_score : row.score),
      severity: String(row.severity || "low").toLowerCase(),
      value: row.value == null ? null : toNumber(row.value),
      timestamp: parseTimestamp(row.timestamp, new Date().toISOString()),
      message: row.message || null,
    }))
    .filter((item) => item.symbol);
}

function applyAnomalyRows(rows, source = "processing", replace = false, timestamp = new Date().toISOString()) {
  const incoming = normalizeAnomalyEvents(rows, source);
  if (replace) {
    state.anomalies.events = trimList(incoming, MAX_EVENT_ITEMS);
  } else {
    state.anomalies.events = mergeByKey(
      state.anomalies.events,
      incoming,
      (row) => row.id,
      MAX_EVENT_ITEMS
    );
  }
  state.anomalies.updatedAt = timestamp;
  state.charts.anomalySeries = buildHistoricalAnomalySeries(state.anomalies.events, state.anomalyWindow);
}

function applySystemStatus(payload = {}) {
  const connection = payload.connection || {};
  const stream = payload.stream || {};
  state.connection.connectedClients =
    connection.connected_clients ?? state.connection.connectedClients;
  state.connection.lastHeartbeatAt =
    connection.last_heartbeat_at ?? state.connection.lastHeartbeatAt;
  if (payload.freshness) {
    state.freshness = payload.freshness;
  }
  state.stream = {
    ...state.stream,
    active: stream.active ?? state.stream.active,
    intervalSeconds: stream.interval_seconds ?? state.stream.intervalSeconds,
  };
  if (payload.scheduler) {
    state.scheduler.running =
      payload.scheduler.running ?? state.scheduler.running;
    if (payload.scheduler.last_job) {
      state.scheduler.recentJobs = trimList(
        [payload.scheduler.last_job, ...state.scheduler.recentJobs],
        50
      );
    }
  }
}

function applySchedulerStatus(result) {
  const scheduler = result?.data?.scheduler;
  if (!scheduler) {
    return;
  }
  state.scheduler.running = Boolean(scheduler.running);
  state.scheduler.recentJobs = scheduler.recent_jobs || state.scheduler.recentJobs;
  state.scheduler.scheduledJobs = scheduler.scheduled_jobs || state.scheduler.scheduledJobs;
  if (scheduler.freshness) {
    state.freshness = scheduler.freshness;
  }
}

async function bootstrapData(filters = {}) {
  const context = normalizeContext(filters.context ?? state.context);
  const timeRange = normalizeTimeRange(filters.timeRange ?? state.timeRange);
  const pickLatestTimestamp = (current, candidate) => {
    const parsedCandidate = parseTimestamp(candidate);
    if (!parsedCandidate) {
      return current;
    }
    if (!current) {
      return parsedCandidate;
    }
    return new Date(parsedCandidate).getTime() > new Date(current).getTime()
      ? parsedCandidate
      : current;
  };
  if (bootstrapPromise) {
    await bootstrapPromise;
  }
  const readEndpoints = buildBootstrapEndpoints({ context, timeRange });
  bootstrapPromise = (async () => {
    update((draft) => {
      draft.ui.loading = true;
      draft.ui.error = null;
    });
    try {
      const dataPromise = Promise.allSettled(readEndpoints.data.map((endpoint) => get(endpoint)));
      const anomaliesPromise = Promise.allSettled(readEndpoints.anomalies.map((endpoint) => get(endpoint)));
      const groupedResponses = await Promise.allSettled([
        get(readEndpoints.marketSeries),
        get(readEndpoints.forecast),
        get(readEndpoints.websocketStatus),
      ]);
      const [dataResponses, anomalyResponses] = await Promise.all([
        dataPromise,
        anomaliesPromise,
      ]);
      const [marketSeriesResponse, forecastResponse, websocketStatusResponse] =
        groupedResponses;

      update((draft) => {
        const marketRows = [];
        let marketTimestamp = null;
        let globalCryptoMarketCap = null;
        let globalCryptoMarketCapSource = null;
        for (const response of dataResponses) {
          if (response.status !== "fulfilled") {
            continue;
          }
          const payload = response.value;
          if (!payload || payload.status !== "success") {
            continue;
          }
          const { data, meta } = payload;
          if (data?.items?.length) {
            marketRows.push(...data.items);
          }
          const globalCap = toFiniteNumber(data?.global_crypto_market_cap);
          if (globalCap != null) {
            globalCryptoMarketCap = globalCap;
            globalCryptoMarketCapSource =
              data?.global_crypto_market_cap_source || globalCryptoMarketCapSource;
          }
          marketTimestamp = pickLatestTimestamp(marketTimestamp, data?.updated_at || meta?.timestamp);
          if (meta?.freshness) {
            draft.freshness = meta.freshness;
          }
        }

        if (marketRows.length > 0) {
          const syncedAt = marketTimestamp || new Date().toISOString();
          applyMarketRows(marketRows, "database", true, syncedAt);
          const seriesFromApi =
            marketSeriesResponse.status === "fulfilled" &&
            marketSeriesResponse.value?.status === "success" &&
            Array.isArray(marketSeriesResponse.value?.data?.points)
              ? normalizeMarketSeriesPoints(marketSeriesResponse.value.data.points)
              : [];
          draft.charts.marketSeries =
            seriesFromApi.length > 0
              ? seriesFromApi
              : buildHistoricalMarketSeries(marketRows, timeRange);
        } else {
          draft.market.items = [];
          draft.market.updatedAt = null;
          draft.market.source = "database";
          draft.charts.marketSeries = [];
        }
        if (globalCryptoMarketCap != null) {
          draft.market.globalCryptoMarketCap = globalCryptoMarketCap;
          draft.market.globalCryptoMarketCapSource = globalCryptoMarketCapSource || "coingecko";
        }

        if (forecastResponse.status === "fulfilled") {
          const payload = forecastResponse.value;
          if (payload?.status === "success" && payload.data?.predictions) {
            draft.forecasts.predictions = payload.data.predictions;
            draft.forecasts.updatedAt =
              payload.data.generated_at || payload.meta?.timestamp || null;
            applyForecastSeries(payload.data.predictions);
            if (payload.meta?.freshness) {
              draft.freshness = payload.meta.freshness;
            }
          }
        }

        const anomalyRows = [];
        let anomaliesTimestamp = null;
        for (const response of anomalyResponses) {
          if (response.status !== "fulfilled") {
            continue;
          }
          const payload = response.value;
          if (!payload || payload.status !== "success") {
            continue;
          }
          const { data, meta } = payload;
          if (data?.events?.length) {
            anomalyRows.push(...data.events);
          }
          anomaliesTimestamp = pickLatestTimestamp(
            anomaliesTimestamp,
            data?.updated_at || meta?.timestamp
          );
          if (meta?.freshness) {
            draft.freshness = meta.freshness;
          }
        }
        applyAnomalyRows(
          anomalyRows,
          "database",
          true,
          anomaliesTimestamp || new Date().toISOString()
        );

        if (websocketStatusResponse.status === "fulfilled") {
          const payload = websocketStatusResponse.value;
          if (payload?.status === "success" && (payload.data?.stream || payload.data?.connection)) {
            applySystemStatus(payload.data);
            if (payload.meta?.freshness) {
              draft.freshness = payload.meta.freshness;
            }
          }
        }

        draft.initialized = true;
        draft.ui.loading = false;
        draft.ui.lastSyncAt = new Date().toISOString();
      });
    } catch (error) {
      update((draft) => {
        draft.ui.loading = false;
        draft.ui.error = String(error.message || error);
      });
    } finally {
      bootstrapPromise = null;
    }
  })();
  return bootstrapPromise;
}

async function ensureLivePipeline() {
  try {
    const schedulerStatus = await runPipelineTask("scheduler_status");
    const running = Boolean(schedulerStatus?.data?.scheduler?.running);
    if (running) {
      return;
    }
    await startPipeline();
    await runPipelineTask("run_full_cycle");
    await bootstrapData({ context: state.context, timeRange: state.timeRange });
  } catch (error) {
    update((draft) => {
      draft.ui.error = String(error?.message || error || "pipeline_autostart_failed");
    });
  }
}

function startHeartbeat() {
  if (heartbeatTimer || !socket) {
    return;
  }
  heartbeatTimer = setInterval(() => {
    if (!socket.connected) {
      return;
    }
    socket.emit("client_heartbeat", { client_ts: new Date().toISOString() });
  }, 20000);
}

function stopHeartbeat() {
  if (!heartbeatTimer) {
    return;
  }
  clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}

function withSocketGuard(eventName, handler) {
  return (payload) => {
    try {
      handler(payload);
    } catch (error) {
      const message = String(error?.message || error || `${eventName}_handler_failed`);
      console.error(`[Socket] ${eventName} handler failed`, error);
      update((draft) => {
        draft.connection.lastError = message;
        draft.ui.error = message;
      });
    }
  };
}

function registerSocketHandlers() {
  if (!socket) {
    return;
  }
  socket.on("connect", () => {
    update((draft) => {
      draft.connection.connected = true;
      draft.connection.status = "connected";
      draft.connection.lastError = null;
    });
    startHeartbeat();
    socket.emit("request_snapshot");
  });

  socket.on("disconnect", () => {
    update((draft) => {
      draft.connection.connected = false;
      draft.connection.status = "disconnected";
    });
    stopHeartbeat();
  });

  socket.on("connect_error", (error) => {
    update((draft) => {
      draft.connection.status = "error";
      draft.connection.lastError = String(error?.message || error || "connection_error");
    });
  });

  socket.io.on("reconnect_attempt", (attempt) => {
    update((draft) => {
      draft.connection.reconnectAttempts = attempt;
      draft.connection.status = "reconnecting";
    });
  });

  socket.on("heartbeat_ack", withSocketGuard("heartbeat_ack", (payload) => {
    update((draft) => {
      draft.connection.lastHeartbeatAt =
        payload?.timestamp || new Date().toISOString();
    });
  }));

  socket.on("stream_state", withSocketGuard("stream_state", (payload) => {
    update((draft) => {
      draft.stream.active = Boolean(payload?.active);
      draft.stream.intervalSeconds = payload?.interval_seconds ?? draft.stream.intervalSeconds;
      draft.connection.connectedClients =
        payload?.connected_clients ?? draft.connection.connectedClients;
    });
  }));

  socket.on("new_data", withSocketGuard("new_data", (payload) => {
    update((draft) => {
      applyMarketRows(
        payload?.items || [],
        payload?.source || "stream",
        false,
        payload?.timestamp || new Date().toISOString()
      );
      if (payload?.freshness) {
        draft.freshness = payload.freshness;
      }
      draft.ui.lastSyncAt = payload?.timestamp || new Date().toISOString();
    });
  }));

  socket.on("anomaly_detected", withSocketGuard("anomaly_detected", (payload) => {
    update((draft) => {
      applyAnomalyRows(
        payload?.events || [],
        payload?.source || "processing",
        false,
        payload?.timestamp || new Date().toISOString()
      );
      draft.ui.lastSyncAt = payload?.timestamp || new Date().toISOString();
    });
  }));

  socket.on("system_status", withSocketGuard("system_status", (payload) => {
    update((draft) => {
      applySystemStatus(payload);
      draft.ui.lastSyncAt = payload?.timestamp || new Date().toISOString();
    });
  }));

  // Legacy event compatibility during migration.
  socket.on("latest_data_points", withSocketGuard("latest_data_points", (payload) => {
    update(() => {
      applyMarketRows(
        payload?.records || [],
        payload?.source || "stream",
        false,
        payload?.timestamp || new Date().toISOString()
      );
    });
  }));
  socket.on("anomaly_events", withSocketGuard("anomaly_events", (payload) => {
    update(() => {
      applyAnomalyRows(
        payload?.events || [],
        payload?.source || "processing",
        false,
        payload?.timestamp || new Date().toISOString()
      );
    });
  }));
  socket.on("scheduler_status", withSocketGuard("scheduler_status", (payload) => {
    update((draft) => {
      draft.scheduler.running = Boolean(payload?.running);
    });
  }));
  socket.on("scheduler_job", withSocketGuard("scheduler_job", (payload) => {
    update((draft) => {
      draft.scheduler.recentJobs = trimList([payload, ...draft.scheduler.recentJobs], 50);
    });
  }));
}

function connectSocket() {
  if (socket) {
    return;
  }
  socket = createSocket();
  update((draft) => {
    draft.connection.status = "connecting";
  });
  registerSocketHandlers();
}

export async function initializeRealtimeApp() {
  await bootstrapData();
  connectSocket();
  await ensureLivePipeline();
}

export function shutdownRealtimeApp() {
  stopHeartbeat();
  if (socket) {
    socket.disconnect();
    socket = null;
  }
  update((draft) => {
    draft.connection.connected = false;
    draft.connection.status = "disconnected";
  });
}

export async function refreshDashboardData() {
  await bootstrapData();
}

export async function startPipeline() {
  const response = await post(endpoints.start, {});
  update((draft) => {
    draft.stream.active = Boolean(response?.data?.stream?.active);
    draft.scheduler.running = Boolean(response?.data?.scheduler?.running);
  });
  return response;
}

export async function stopPipeline() {
  const response = await post(endpoints.stop, {});
  update((draft) => {
    draft.stream.active = Boolean(response?.data?.stream?.active);
    draft.scheduler.running = Boolean(response?.data?.scheduler?.running);
  });
  return response;
}

export async function runPipelineTask(task, payload = {}) {
  const response = await post(endpoints.runTask, { task, ...payload });
  update((draft) => {
    if (task === "scheduler_status") {
      applySchedulerStatus(response);
    }
  });
  return response;
}

export function setSearchQuery(query) {
  update((draft) => {
    draft.query = query;
  });
}

export function setSelectedMarketSymbol(category, symbol) {
  const normalizedCategory = normalizeMarketCategory(category);
  const normalizedSymbol = String(symbol || "").toUpperCase();
  if (!normalizedCategory || !normalizedSymbol) {
    return;
  }
  update((draft) => {
    const scopedItems = getItemsByCategory(draft.market.items, normalizedCategory);
    if (!scopedItems.some((item) => item.symbol === normalizedSymbol)) {
      return;
    }
    if (normalizedCategory === "crypto") {
      draft.market.selectedCryptoSymbol = normalizedSymbol;
      return;
    }
    draft.market.selectedStockSymbol = normalizedSymbol;
  });
}

export function setDataContext(context) {
  const nextContext = normalizeContext(context);
  update((draft) => {
    draft.context = nextContext;
  });
  void bootstrapData({ context: nextContext, timeRange: state.timeRange });
}

export function setTimeRange(timeRange) {
  const nextRange = normalizeTimeRange(timeRange);
  update((draft) => {
    draft.timeRange = nextRange;
  });
  void bootstrapData({ context: state.context, timeRange: nextRange, anomalyWindow: state.anomalyWindow });
}

export function setAnomalyWindow(anomalyWindow) {
  const nextWindow = normalizeAnomalyWindow(anomalyWindow);
  update((draft) => {
    draft.anomalyWindow = nextWindow;
    draft.charts.anomalySeries = buildHistoricalAnomalySeries(draft.anomalies.events, nextWindow);
  });
  void bootstrapData({ context: state.context, timeRange: state.timeRange, anomalyWindow: nextWindow });
}

export function getState() {
  return state;
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useAppStore(selector = (snapshot) => snapshot) {
  return useSyncExternalStore(
    subscribe,
    () => selector(state),
    () => selector(state)
  );
}
