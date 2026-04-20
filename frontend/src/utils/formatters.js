function toDisplayNumber(value) {
  if (value == null || value === "") {
    return null;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export function formatCurrency(value) {
  const numeric = toDisplayNumber(value);
  if (numeric == null) {
    return "--";
  }
  if (Math.abs(numeric) >= 1_000_000_000) {
    return `$${(numeric / 1_000_000_000).toFixed(2)}B`;
  }
  if (Math.abs(numeric) >= 1_000_000) {
    return `$${(numeric / 1_000_000).toFixed(2)}M`;
  }
  if (Math.abs(numeric) >= 1_000) {
    return `$${(numeric / 1_000).toFixed(2)}K`;
  }
  return `$${numeric.toFixed(2)}`;
}

export function formatPercent(value) {
  const numeric = toDisplayNumber(value);
  if (numeric == null) {
    return "--";
  }
  const sign = numeric > 0 ? "+" : "";
  return `${sign}${numeric.toFixed(2)}%`;
}

export function formatRelativeTime(value) {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) {
    return `${seconds}s ago`;
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m ago`;
  }
  if (seconds < 86400) {
    return `${Math.floor(seconds / 3600)}h ago`;
  }
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function formatNumber(value) {
  const numeric = toDisplayNumber(value);
  if (numeric == null) {
    return "--";
  }
  return numeric.toLocaleString();
}

export function average(values) {
  if (!values.length) {
    return 0;
  }
  return values.reduce((acc, item) => acc + Number(item || 0), 0) / values.length;
}
