import KpiCard from "../components/common/KpiCard";
import Panel from "../components/common/Panel";
import RealtimeLineChart from "../components/charts/RealtimeLineChart";
import {
  setDataContext,
  setSelectedMarketSymbol,
  setTimeRange,
  useAppStore,
} from "../store/store";
import {
  average,
  formatCurrency,
  formatPercent,
  formatRelativeTime,
} from "../utils/formatters";

const CRYPTO_SYMBOLS = new Set(["BTC", "ETH", "SOL"]);
const STOCK_SYMBOLS = new Set(["AAPL", "MSFT", "TSLA"]);
const TOP_MOVERS_LIMIT = 8;

function resolveSourceCategory(source) {
  const value = String(source || "").toLowerCase();
  if (value.includes("crypto")) return "crypto";
  if (value.includes("stock") || value.includes("polygon")) return "stock";
  return null;
}

function resolveSymbolCategory(symbol, symbolCategoryLookup = new Map()) {
  const upper = String(symbol || "").toUpperCase();
  if (symbolCategoryLookup.has(upper)) return symbolCategoryLookup.get(upper);
  if (CRYPTO_SYMBOLS.has(upper)) return "crypto";
  if (STOCK_SYMBOLS.has(upper)) return "stock";
  return null;
}

function getChartLines(context) {
  const ctx = context.toLowerCase();
  if (ctx === "crypto") {
    return [{ dataKey: "crypto", color: "#7adf8a", strokeWidth: 2.6 }];
  }
  if (ctx === "stock") {
    return [{ dataKey: "stock", color: "#ffb782", strokeWidth: 2.6 }];
  }
  // "all" — show separate lines, no combined total
  return [
    { dataKey: "crypto", color: "#7adf8a", strokeWidth: 2.2 },
    { dataKey: "stock", color: "#ffb782", strokeWidth: 2.2 },
  ];
}

function getChartTitle(context) {
  const ctx = context.toLowerCase();
  if (ctx === "crypto") return "Crypto Market Overview";
  if (ctx === "stock") return "Stock Market Overview";
  return "Global Market Overview";
}

function formatDataAge(seconds) {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "--";
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

function buildSymbolOptions(items) {
  const bySymbol = new Map();
  for (const item of items) {
    const symbol = String(item.symbol || "").toUpperCase();
    if (!symbol) continue;
    const current = bySymbol.get(symbol);
    const nextCap = Number(item.market_cap ?? -1);
    const currentCap = Number(current?.market_cap ?? -1);
    if (!current || nextCap >= currentCap) {
      bySymbol.set(symbol, item);
    }
  }
  return [...bySymbol.values()].sort((left, right) => {
    const rightCap = Number(right.market_cap ?? -1);
    const leftCap = Number(left.market_cap ?? -1);
    if (rightCap !== leftCap) return rightCap - leftCap;
    const rightVolume = Number(right.volume_24h ?? -1);
    const leftVolume = Number(left.volume_24h ?? -1);
    if (rightVolume !== leftVolume) return rightVolume - leftVolume;
    return String(left.symbol || "").localeCompare(String(right.symbol || ""));
  });
}

function calculateSharePercent(part, total) {
  const numericPart = Number(part);
  const numericTotal = Number(total);
  if (!Number.isFinite(numericPart) || !Number.isFinite(numericTotal) || numericPart <= 0 || numericTotal <= 0) {
    return null;
  }
  return (numericPart / numericTotal) * 100;
}

export default function OverviewPage() {
  const context = useAppStore((s) => s.context);
  const timeRange = useAppStore((s) => s.timeRange);
  const query = useAppStore((s) => s.query.trim().toLowerCase());
  const marketItems = useAppStore((s) => s.market.items);
  const globalCryptoMarketCap = useAppStore((s) => s.market.globalCryptoMarketCap);
  const globalCryptoMarketCapSource = useAppStore((s) => s.market.globalCryptoMarketCapSource);
  const selectedCryptoSymbol = useAppStore((s) => s.market.selectedCryptoSymbol);
  const selectedStockSymbol = useAppStore((s) => s.market.selectedStockSymbol);
  const marketSeries = useAppStore((s) => s.charts.marketSeries);
  const anomalyEvents = useAppStore((s) => s.anomalies.events);
  const freshness = useAppStore((s) => s.freshness);
  const connection = useAppStore((s) => s.connection);
  const schedulerRunning = useAppStore((s) => s.scheduler.running);

  const normalizedContext = context.toLowerCase();
  const symbolCategoryLookup = new Map();
  for (const item of marketItems) {
    const category = resolveSourceCategory(item.source);
    if (category) {
      symbolCategoryLookup.set(String(item.symbol || "").toUpperCase(), category);
    }
  }
  const contextFilteredItems = marketItems.filter((item) => {
    if (normalizedContext === "all") {
      return true;
    }
    return resolveSourceCategory(item.source) === normalizedContext;
  });
  const filteredItems = contextFilteredItems.filter((item) => {
    if (!query) {
      return true;
    }
    const label = `${item.symbol} ${item.name || ""} ${item.source}`.toLowerCase();
    return label.includes(query);
  });

  const totalMarketCap = filteredItems.reduce(
    (acc, item) => acc + Number(item.market_cap || 0),
    0
  );
  const totalCryptoMarketCap = contextFilteredItems
    .filter((item) => resolveSourceCategory(item.source) === "crypto")
    .reduce((acc, item) => acc + Number(item.market_cap || 0), 0);
  const totalStockMarketCap = contextFilteredItems
    .filter((item) => resolveSourceCategory(item.source) === "stock")
    .reduce((acc, item) => acc + Number(item.market_cap || 0), 0);
  const totalVolume = filteredItems.reduce(
    (acc, item) => acc + Number(item.volume_24h || 0),
    0
  );
  const cryptoOptions = buildSymbolOptions(
    contextFilteredItems.filter((item) => resolveSourceCategory(item.source) === "crypto")
  );
  const stockOptions = buildSymbolOptions(
    contextFilteredItems.filter((item) => resolveSourceCategory(item.source) === "stock")
  );
  const selectedCryptoItem =
    cryptoOptions.find((item) => item.symbol === selectedCryptoSymbol) || cryptoOptions[0] || null;
  const selectedStockItem =
    stockOptions.find((item) => item.symbol === selectedStockSymbol) || stockOptions[0] || null;
  const selectedCategory = normalizedContext === "crypto"
    ? "crypto"
    : normalizedContext === "stock"
      ? "stock"
      : null;
  const contextSelectedItem =
    selectedCategory === "crypto" ? selectedCryptoItem : selectedCategory === "stock" ? selectedStockItem : null;
  const cryptoShareBase = Number.isFinite(Number(globalCryptoMarketCap))
    ? Number(globalCryptoMarketCap)
    : totalCryptoMarketCap;
  const selectedCryptoShare = calculateSharePercent(selectedCryptoItem?.market_cap, cryptoShareBase);
  const selectedStockShare = calculateSharePercent(selectedStockItem?.market_cap, totalStockMarketCap);
  const selectedContextShare = selectedCategory === "crypto" ? selectedCryptoShare : selectedStockShare;
  const selectedContextShareLabel = selectedCategory === "crypto"
    ? "global crypto market cap"
    : "tracked stock market cap";
  const displayMarketCap =
    normalizedContext === "stock"
      ? (totalMarketCap > 0 ? totalMarketCap : null)
      : (Number.isFinite(Number(globalCryptoMarketCap))
          ? Number(globalCryptoMarketCap)
          : (totalMarketCap > 0 ? totalMarketCap : null));
  const marketCapTitle = normalizedContext === "stock" ? "Stock Market Cap" : "Global Crypto Market Cap";
  const marketCapSubtitle =
    normalizedContext === "stock"
      ? (totalMarketCap > 0 ? `${filteredItems.length} assets with reported cap` : "stock cap unavailable from provider")
      : (Number.isFinite(Number(globalCryptoMarketCap))
          ? `source: ${String(globalCryptoMarketCapSource || "coingecko").toUpperCase()}`
          : (totalMarketCap > 0 ? `tracked assets: ${filteredItems.length}` : "market cap unavailable"));
  const heroValueDisplay = contextSelectedItem
    ? formatCurrency(contextSelectedItem.value)
    : displayMarketCap == null
      ? "--"
      : formatCurrency(displayMarketCap);
  const heroSubtitle = contextSelectedItem
    ? `${contextSelectedItem.symbol} selected • ${
        selectedContextShare == null
          ? "market-share unavailable"
          : `${formatPercent(selectedContextShare)} of ${selectedContextShareLabel}`
      }`
    : `${marketCapTitle} • ${marketCapSubtitle}`;
  const topMovers = [...filteredItems]
    .sort((a, b) => Math.abs(Number(b.change_24h || 0)) - Math.abs(Number(a.change_24h || 0)))
    .slice(0, TOP_MOVERS_LIMIT);

  // Filter anomalies by symbol category instead of source field
  // (anomalies always have source="processing", not "crypto"/"stock")
  const contextAnomalies = anomalyEvents.filter((event) => {
    if (normalizedContext === "all") return true;
    const category = resolveSymbolCategory(event.symbol, symbolCategoryLookup);
    return category === normalizedContext;
  });
  const activeAnomalies =
    contextAnomalies.length > 0
      ? contextAnomalies.slice(0, 4)
      : normalizedContext === "all"
        ? []
        : anomalyEvents.slice(0, 4);

  const contextFreshnessRows = freshness.filter((row) => {
    if (normalizedContext === "all") return true;
    return resolveSourceCategory(row.source) === normalizedContext;
  });
  const freshnessSource = contextFreshnessRows.length > 0 ? contextFreshnessRows : freshness;
  const freshnessAges = freshnessSource
    .map((row) => Number(row.age_seconds))
    .filter((value) => Number.isFinite(value));
  const avgAgeSec = average(freshnessAges);
  const cryptoSeries = marketSeries
    .filter((point) => Number.isFinite(Number(point?.crypto)))
    .map((point) => ({ timestamp: point.timestamp, crypto: point.crypto }));
  const stockSeries = marketSeries
    .filter((point) => Number.isFinite(Number(point?.stock)))
    .map((point) => ({ timestamp: point.timestamp, stock: point.stock }));

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h2>System Overview</h2>
          <p>Real-time aggregate intelligence stream.</p>
        </div>
        <div className="overview-switches">
          <div className="segmented" aria-label="overview-time-range">
            <button
              type="button"
              className={timeRange === "30d" ? "active" : ""}
              onClick={() => setTimeRange("30d")}
            >
              30D
            </button>
            <button
              type="button"
              className={timeRange === "1y" ? "active" : ""}
              onClick={() => setTimeRange("1y")}
            >
              1Y
            </button>
            <button
              type="button"
              className={timeRange === "4y" ? "active" : ""}
              onClick={() => setTimeRange("4y")}
            >
              4Y
            </button>
          </div>
          <div className="segmented" aria-label="overview-data-context">
            <button
              type="button"
              className={context === "crypto" ? "active" : ""}
              onClick={() => setDataContext("crypto")}
            >
              Crypto
            </button>
            <button
              type="button"
              className={context === "stock" ? "active" : ""}
              onClick={() => setDataContext("stock")}
            >
              Stock
            </button>
            <button
              type="button"
              className={context === "all" ? "active" : ""}
              onClick={() => setDataContext("all")}
            >
              All
            </button>
          </div>
        </div>
      </header>

      <section className="grid two-third">
        <Panel
          title={getChartTitle(context)}
          subtitle={`24h Vol: ${formatCurrency(totalVolume)} • Stream: ${
            connection.connected ? "Connected" : "Disconnected"
          }`}
          className="hero-panel"
        >
          <h1 className="hero-value">
            {heroValueDisplay}
          </h1>
          <p>{heroSubtitle}</p>
          {normalizedContext === "all" ? (
            <div className="stack">
              <RealtimeLineChart
                data={cryptoSeries}
                height={110}
                connectNulls
                valueMode="currency"
                lines={[{ dataKey: "crypto", color: "#7adf8a", strokeWidth: 2.3 }]}
              />
              <RealtimeLineChart
                data={stockSeries}
                height={110}
                connectNulls
                valueMode="currency"
                lines={[{ dataKey: "stock", color: "#ffb782", strokeWidth: 2.3 }]}
              />
            </div>
          ) : (
            <RealtimeLineChart
              data={marketSeries}
              height={180}
              connectNulls
              valueMode="currency"
              lines={getChartLines(context)}
            />
          )}
        </Panel>

        <Panel title="Active Anomalies" actions={<span className="pill warning">Live</span>}>
          <div className="stack">
            {activeAnomalies.length === 0 ? (
              <div className="chart-empty">No active anomalies.</div>
            ) : null}
            {activeAnomalies.map((event) => (
              <article key={event.id} className={`alert-item ${event.severity}`}>
                <h4>
                  {event.symbol} • {event.type}
                </h4>
                <p>Score {(event.score ?? 0).toFixed(2)} from {event.source}</p>
                <small>{formatRelativeTime(event.timestamp)}</small>
              </article>
            ))}
          </div>
        </Panel>
      </section>

      <section className="grid two-third">
        <Panel title="Top Movers (24h)">
          <div className="stack">
            {(normalizedContext !== "stock" && cryptoOptions.length > 0) ? (
              <div className="segmented selector-block">
                <span className="selector-label">Crypto</span>
                <select
                  value={selectedCryptoItem?.symbol || ""}
                  onChange={(event) => setSelectedMarketSymbol("crypto", event.target.value)}
                >
                  {cryptoOptions.map((item) => (
                    <option key={`crypto-${item.symbol}`} value={item.symbol}>
                      {item.symbol} • {item.name || item.symbol}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            {(normalizedContext !== "crypto" && stockOptions.length > 0) ? (
              <div className="segmented selector-block">
                <span className="selector-label">Stock</span>
                <select
                  value={selectedStockItem?.symbol || ""}
                  onChange={(event) => setSelectedMarketSymbol("stock", event.target.value)}
                >
                  {stockOptions.map((item) => (
                    <option key={`stock-${item.symbol}`} value={item.symbol}>
                      {item.symbol} • {item.name || item.symbol}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            {topMovers.length === 0 ? (
              <div className="chart-empty">No market movers available.</div>
            ) : null}
            {topMovers.map((item) => (
              <button
                key={`${item.source}:${item.symbol}`}
                type="button"
                className={`list-row selectable-row ${
                  (resolveSourceCategory(item.source) === "crypto" && item.symbol === selectedCryptoItem?.symbol) ||
                  (resolveSourceCategory(item.source) === "stock" && item.symbol === selectedStockItem?.symbol)
                    ? "selected-row"
                    : ""
                }`}
                onClick={() => {
                  const category = resolveSourceCategory(item.source);
                  if (category) {
                    setSelectedMarketSymbol(category, item.symbol);
                  }
                }}
              >
                <div>
                  <strong>{item.name || item.symbol}</strong>
                  <p>{item.symbol}</p>
                </div>
                <div className="align-right">
                  <strong>{formatCurrency(item.value)}</strong>
                  <p className={Number(item.change_24h) < 0 ? "negative" : "positive"}>
                    {formatPercent(item.change_24h)}
                  </p>
                </div>
              </button>
            ))}
          </div>
        </Panel>

        <Panel title="Network Health">
          <div className="kpi-grid">
            <KpiCard
              label="Data Age"
              value={Number.isFinite(avgAgeSec) ? formatDataAge(avgAgeSec) : "--"}
              trend="freshness probe avg"
              trendType={avgAgeSec > 300 ? "warning" : "positive"}
              icon="hub"
            />
            <KpiCard
              label="Node Sync"
              value={connection.connected && schedulerRunning ? "Healthy" : "Degraded"}
              trend={schedulerRunning ? "scheduler running" : "scheduler paused"}
              trendType={connection.connected && schedulerRunning ? "positive" : "warning"}
              icon="sync"
            />
          </div>
        </Panel>
      </section>
    </div>
  );
}
