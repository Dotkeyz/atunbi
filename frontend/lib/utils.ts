export function formatDuration(hours: number, rangeMax?: number): string {
  // If rangeMax is provided, pick unit based on the slider SCALE, not the value
  if (rangeMax !== undefined) {
    if (rangeMax <= 0.01) return `${Math.round(hours * 3600)}s`;
    if (rangeMax <= 0.1) return `${Math.round(hours * 60)}m`;
    if (rangeMax <= 2) return `${Math.round(hours * 60)}m`;
    if (rangeMax <= 48) return `${hours.toFixed(1)}h`;
    return `${(hours / 24).toFixed(1)}d`;
  }
  // Original value-driven formatting
  const totalSeconds = hours * 3600;
  if (totalSeconds < 60) return `${Math.round(totalSeconds)}s`;
  if (totalSeconds < 3600) {
    const m = Math.floor(totalSeconds / 60);
    const s = Math.round(totalSeconds % 60);
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
  }
  if (totalSeconds < 86400) {
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.round((totalSeconds % 3600) / 60);
    return m > 0 ? `${h}h ${m}m` : `${h}h`;
  }
  const d = Math.floor(totalSeconds / 86400);
  const h = Math.round((totalSeconds % 86400) / 3600);
  return h > 0 ? `${d}d ${h}h` : `${d}d`;
}
