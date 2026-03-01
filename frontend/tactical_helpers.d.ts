export type UnitType = "FRIENDLY" | "HOSTILE" | "UNKNOWN";

export interface UnitStyle {
  fill: string;
  stroke: string;
}

export interface TimestampedEvent {
  timestamp: string;
}

export declare const unitStyles: Record<UnitType, UnitStyle>;

export declare function isUnitType(value: string): value is UnitType;

export declare function normalizeUnitType(unitType: UnitType): UnitType;
export declare function normalizeUnitType(unitType: string): UnitType;

export declare function getUnitStyle(unitType: UnitType): UnitStyle;
export declare function getUnitStyle(unitType: string): UnitStyle;

export declare function buildUnitIconSvg(unitType: UnitType): string;
export declare function buildUnitIconSvg(unitType: string): string;

export declare function filterEventsByTimeRange<T extends TimestampedEvent>(
  events: readonly T[],
  startMs: number,
  endMs: number,
): T[];
