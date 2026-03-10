export type UnitType = "FRIENDLY" | "HOSTILE" | "UNKNOWN";

export interface UnitStyle {
  fill: string;
  stroke: string;
}

export interface TimestampedEvent {
  timestamp: string;
}

export const unitStyles: Record<UnitType, UnitStyle> = {
  FRIENDLY: { fill: "#1f8f4a", stroke: "#0f4d27" },
  HOSTILE: { fill: "#c72828", stroke: "#6b0f0f" },
  UNKNOWN: { fill: "#c48a1d", stroke: "#5e430d" },
};

export function isUnitType(value: string): value is UnitType {
  return value === "FRIENDLY" || value === "HOSTILE" || value === "UNKNOWN";
}

export function normalizeUnitType(unitType: UnitType | string): UnitType {
  if (isUnitType(unitType)) {
    return unitType;
  }
  return "UNKNOWN";
}

export function getUnitStyle(unitType: UnitType | string): UnitStyle {
  return unitStyles[normalizeUnitType(unitType)];
}

export function buildUnitIconSvg(unitType: UnitType | string): string {
  const style = getUnitStyle(unitType);
  return `
<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <circle cx="12" cy="12" r="10" fill="${style.fill}" stroke="${style.stroke}" stroke-width="2"/>
  <circle cx="12" cy="12" r="3.5" fill="#f4f1e9" />
</svg>`.trim();
}

export function filterEventsByTimeRange<T extends TimestampedEvent>(
  events: readonly T[],
  startMs: number,
  endMs: number,
): T[] {
  const minMs = Math.min(startMs, endMs);
  const maxMs = Math.max(startMs, endMs);
  return events.filter((event) => {
    const ts = new Date(event.timestamp).getTime();
    return Number.isFinite(ts) && ts >= minMs && ts <= maxMs;
  });
}
