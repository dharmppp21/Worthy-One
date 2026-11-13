/** SignalForge emits UTC timestamps; a string without a zone is treated as UTC
 * rather than device-local, so relative times aren't skewed by the offset. */
function parseUtc(isoStr: string | Date): Date {
  if (isoStr instanceof Date) return isoStr;
  const hasZone = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(isoStr);
  return new Date(hasZone ? isoStr : `${isoStr}Z`);
}

export function relativeTime(isoStr: string | Date): string {
  const then = parseUtc(isoStr);
  if (Number.isNaN(then.getTime())) return '—';

  const diffMs = Date.now() - then.getTime();
  // Clock skew between an agent host and this device can put a timestamp in the
  // future; "in 3m ago" is worse than "just now".
  if (diffMs < 60_000) return 'just now';

  const diffMinutes = Math.floor(diffMs / 60_000);
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function formatUsd(amount: number, digits = 0): string {
  return `$${amount.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}
