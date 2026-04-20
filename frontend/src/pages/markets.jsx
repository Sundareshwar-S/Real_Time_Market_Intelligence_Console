import KpiCard from "../components/common/KpiCard";
import Panel from "../components/common/Panel";
import RealtimeLineChart from "../components/charts/RealtimeLineChart";
import {
  setDataContext,
  setSelectedMarketSymbol,
  setTimeRange,
  useAppStore,
} from "../store/store";
import { average, formatCurrency, formatPercent, formatRelativeTime } from "../utils/formatters";

function resolveSourceCategory(source) {
  const value = String(source || "").toLowerCase();
  if (value.includes("crypto")) return "crypto";
  if (value.includes("stock") || value.includes("polygon")) return "stock";
  return null;
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

export default function MarketsPage() {
  const context = useAppStore((s) => s.context);
  const timeRange = useAppStore((s) => s.timeRange);
  const query = useAppStore((s) => s.query.trim().toLowerCase());
  const items = useAppStore((s) => s.market.items);
  const globalCryptoMarketCap = useAppStore((s) => s.market.globalCryptoMarketCap);
  const globalCryptoMarketCapSource = useAppStore((s) => s.market.globalCryptoMarketCapSource);
  const selectedCryptoSymbol = useAppStore((s) => s.market.selectedCryptoSymbol);
  const selectedStockSymbol = useAppStore((s) => s.market.selectedStockSymbol);
  const marketSeries = useAppStore((s) => s.charts.marketSeries);
  const updatedAt = useAppStore((s) => s.market.updatedAt);

  const filteredByContext = items.filter((item) => {
    if (context === "all") {
      return true;
    }
    return resolveSourceCategory(item.source) === context;
  });
  const filtered = filteredByContext.filter((item) => {
    if (!query) {
      return true;
    }
    return `${item.symbol} ${item.name || ""} ${item.source}`
      .toLowerCase()
      .includes(query);
  });

  const totalMarketCap = filtered.reduce((acc, item) => acc + Number(item.market_cap || 0), 0);
  const totalCryptoMarketCap = filteredByContext
    .filter((item) => resolveSourceCategory(item.source) === "crypto")
    .reduce((acc, item) => acc + Number(item.market_cap || 0), 0);
  const totalStockMarketCap = filteredByContext
    .filter((item) => resolveSourceCategory(item.source) === "stock")
    .reduce((acc, item) => acc + Number(item.market_cap || 0), 0);
  const totalVolume = filtered.reduce((acc, item) => acc + Number(item.volume_24h || 0), 0);
  const volatility = average(filtered.map((item) => Math.abs(Number(item.change_24h || 0))));
  const cryptoOptions = buildSymbolOptions(
    filteredByContext.filter((item) => resolveSourceCategory(item.source) === "crypto")
  );
  const stockOptions = buildSymbolOptions(
    filteredByContext.filter((item) => resolveSourceCategory(item.source) === "stock")
  );
  const selectedCryptoItem =
    cryptoOptions.find((item) => item.symbol === selectedCryptoSymbol) || cryptoOptions[0] || null;
  const selectedStockItem =
    stockOptions.find((item) => item.symbol === selectedStockSymbol) || stockOptions[0] || null;
  const selectedContextItem = context === "crypto"
    ? selectedCryptoItem
    : context === "stock"
      ? selectedStockItem
      : null;
  const selectedCryptoShare = calculateSharePercent(
    selectedCryptoItem?.market_cap,
    Number.isFinite(Number(globalCryptoMarketCap)) ? Number(globalCryptoMarketCap) : totalCryptoMarketCap
  );
  const selectedStockShare = calculateSharePercent(
    selectedStockItem?.market_cap,
    totalStockMarketCap
  );
  const selectedContextShare = context === "crypto" ? selectedCryptoShare : selectedStockShare;
  const displayMarketCap =
    context === "stock"
      ? (totalMarketCap > 0 ? totalMarketCap : null)
      : (Number.isFinite(Number(globalCryptoMarketCap))
          ? Number(globalCryptoMarketCap)
          : (totalMarketCap > 0 ? totalMarketCap : null));
  const marketCapTrend =
    context === "stock"
      ? (totalMarketCap > 0 ? `${filtered.length} assets with reported cap` : "stock cap unavailable from provider")
      : (Number.isFinite(Number(globalCryptoMarketCap))
          ? `source: ${String(globalCryptoMarketCapSource || "coingecko").toUpperCase()}`
          : (totalMarketCap > 0 ? `tracked assets: ${filtered.length}` : "market cap unavailable"));
  const marketCapLabel = context === "stock" ? "Stock Market Cap" : "Global Crypto Market Cap";
  const selectorTrendLabel = context === "crypto"
    ? "global crypto market cap"
    : "tracked stock market cap";
  const primaryLabel =
    context === "all"
      ? marketCapLabel
      : `${selectedContextItem?.symbol || (context === "crypto" ? "Crypto" : "Stock")} Price`;
  const primaryValue =
    context === "all"
      ? (displayMarketCap == null ? "--" : formatCurrency(displayMarketCap))
      : (selectedContextItem ? formatCurrency(selectedContextItem.value) : "--");
  const primaryTrend =
    context === "all"
      ? marketCapTrend
      : selectedContextShare == null
        ? "market-share unavailable"
        : `${formatPercent(selectedContextShare)} of ${selectorTrendLabel}`;
  const totalVolumeDisplay = totalVolume > 0 ? formatCurrency(totalVolume) : "--";
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
          <h2>Global Markets</h2>
          <p>
            Live feed active
            {updatedAt ? ` • last updated ${formatRelativeTime(updatedAt)}` : ""}
            .
          </p>
        </div>
        <div className="overview-switches">
          <div className="segmented" aria-label="markets-time-range">
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
          </div>
          <div className="segmented">
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
          {(context !== "stock" && cryptoOptions.length > 0) ? (
            <div className="segmented selector-block">
              <span className="selector-label">Crypto</span>
              <select
                value={selectedCryptoItem?.symbol || ""}
                onChange={(event) => setSelectedMarketSymbol("crypto", event.target.value)}
              >
                {cryptoOptions.map((item) => (
                  <option key={`market-crypto-${item.symbol}`} value={item.symbol}>
                    {item.symbol} • {item.name || item.symbol}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          {(context !== "crypto" && stockOptions.length > 0) ? (
            <div className="segmented selector-block">
              <span className="selector-label">Stock</span>
              <select
                value={selectedStockItem?.symbol || ""}
                onChange={(event) => setSelectedMarketSymbol("stock", event.target.value)}
              >
                {stockOptions.map((item) => (
                  <option key={`market-stock-${item.symbol}`} value={item.symbol}>
                    {item.symbol} • {item.name || item.symbol}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
        </div>
      </header>

      <section className="grid thirds">
        <KpiCard
          label={primaryLabel}
          value={primaryValue}
          trend={primaryTrend}
          trendType={context === "all" ? "positive" : "neutral"}
          icon="account_balance_wallet"
        />
        <KpiCard
          label="24h Volume"
          value={totalVolumeDisplay}
          trend={totalVolume > 0 ? formatRelativeTime(updatedAt) : "provider volume unavailable"}
          trendType="neutral"
          icon="monitoring"
        />
        <KpiCard
          label="Volatility Index"
          value={`${volatility.toFixed(2)}%`}
          trend={volatility > 4 ? "Elevated" : "Stable"}
          trendType={volatility > 4 ? "warning" : "positive"}
          icon="bolt"
        />
      </section>

      <Panel title="Market Pulse" subtitle="Incremental updates from realtime stream">
        {context === "all" ? (
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
            height={170}
            connectNulls
            valueMode="currency"
            lines={
              context === "crypto"
                ? [{ dataKey: "crypto", color: "#7adf8a", strokeWidth: 2.4 }]
                : [{ dataKey: "stock", color: "#ffb782", strokeWidth: 2.4 }]
            }
          />
        )}
      </Panel>

      <Panel title="Asset Explorer" subtitle={`Showing ${filtered.length} assets`}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Asset</th>
                <th>Price</th>
                <th>24h Change</th>
                <th>24h Volume</th>
                <th>Market Cap</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={5} className="table-empty-cell">
                    No market records available.
                  </td>
                </tr>
              ) : null}
              {filtered.map((row) => (
                <tr
                  key={`${row.source}:${row.symbol}`}
                  className={`asset-row selectable-row ${
                    (resolveSourceCategory(row.source) === "crypto" && row.symbol === selectedCryptoItem?.symbol) ||
                    (resolveSourceCategory(row.source) === "stock" && row.symbol === selectedStockItem?.symbol)
                      ? "selected-row"
                      : ""
                  }`}
                  onClick={() => {
                    const category = resolveSourceCategory(row.source);
                    if (category) {
                      setSelectedMarketSymbol(category, row.symbol);
                    }
                  }}
                >
                  <td>
                    <strong>{row.name || row.symbol}</strong>
                    <p>{row.symbol}</p>
                  </td>
                  <td>{formatCurrency(row.value)}</td>
                  <td className={Number(row.change_24h) < 0 ? "negative" : "positive"}>
                    {formatPercent(row.change_24h)}
                  </td>
                  <td>{formatCurrency(row.volume_24h)}</td>
                  <td>{formatCurrency(row.market_cap)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
