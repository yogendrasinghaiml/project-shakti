import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import L from "leaflet";
import { MapContainer, Marker, Popup, TileLayer } from "react-leaflet";
import {
  buildUnitIconSvg,
  filterEventsByTimeRange,
  getUnitStyle,
  normalizeUnitType,
  type UnitType,
} from "./tactical_helpers";

export { buildUnitIconSvg, filterEventsByTimeRange } from "./tactical_helpers";
export type { UnitType } from "./tactical_helpers";

export interface TacticalIntelPoint {
  id: string;
  unitType: UnitType | string;
  timestamp: string;
  lat: number;
  lon: number;
  label: string;
  source?: string;
}

export interface TacticalMapViewProps {
  events: TacticalIntelPoint[];
  center?: [number, number];
  zoom?: number;
  tileUrlTemplate?: string;
  tileAttribution?: string;
}

function buildUnitIcon(unitType: UnitType | string): L.DivIcon {
  return L.divIcon({
    className: "tactical-unit-icon",
    html: buildUnitIconSvg(unitType),
    iconSize: [24, 24],
    iconAnchor: [12, 12],
    popupAnchor: [0, -12],
  });
}

function formatTimestamp(tsMs: number): string {
  return new Date(tsMs).toLocaleString();
}

function markerStyleForEvent(unitType: UnitType | string): CSSProperties {
  const color = getUnitStyle(unitType).fill;
  return { borderColor: color };
}

export default function TacticalMapView({
  events,
  center = [28.6139, 77.209],
  zoom = 5,
  tileUrlTemplate = "/tiles/{z}/{x}/{y}.png",
  tileAttribution = "Local tactical tile cache",
}: TacticalMapViewProps) {
  const sortedTimes = useMemo(
    () =>
      events
        .map((event) => new Date(event.timestamp).getTime())
        .filter((value) => Number.isFinite(value))
        .sort((a, b) => a - b),
    [events],
  );

  const minTs = sortedTimes.length > 0 ? sortedTimes[0] : Date.now();
  const maxTs = sortedTimes.length > 0 ? sortedTimes[sortedTimes.length - 1] : Date.now();

  const [startTs, setStartTs] = useState<number>(minTs);
  const [endTs, setEndTs] = useState<number>(maxTs);

  useEffect(() => {
    setStartTs(minTs);
    setEndTs(maxTs);
  }, [minTs, maxTs]);

  const filteredEvents = useMemo(
    () => filterEventsByTimeRange(events, Math.min(startTs, endTs), Math.max(startTs, endTs)),
    [events, startTs, endTs],
  );

  return (
    <section
      style={{
        display: "grid",
        gridTemplateRows: "1fr auto",
        gap: "12px",
        width: "100%",
        minHeight: "560px",
        padding: "12px",
        background:
          "radial-gradient(circle at 15% 10%, #1f2733 0%, #101820 48%, #0a1017 100%)",
        color: "#f3f1ea",
        border: "1px solid #223447",
      }}
    >
      <MapContainer center={center} zoom={zoom} style={{ width: "100%", height: "100%" }}>
        <TileLayer
          attribution={tileAttribution}
          url={tileUrlTemplate}
        />

        {filteredEvents.map((event) => (
          <Marker
            key={event.id}
            position={[event.lat, event.lon]}
            icon={buildUnitIcon(normalizeUnitType(event.unitType))}
          >
            <Popup>
              <div style={markerStyleForEvent(event.unitType)}>
                <strong>{event.label}</strong>
                <div>Unit: {normalizeUnitType(event.unitType)}</div>
                <div>Source: {event.source ?? "N/A"}</div>
                <div>Time: {new Date(event.timestamp).toLocaleString()}</div>
                <div>
                  Lat/Lon: {event.lat.toFixed(4)}, {event.lon.toFixed(4)}
                </div>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>

      <div
        style={{
          display: "grid",
          gap: "8px",
          gridTemplateColumns: "1fr",
          background: "#0e151f",
          border: "1px solid #2d4057",
          padding: "12px",
        }}
      >
        <div style={{ fontSize: "0.95rem", letterSpacing: "0.04em" }}>
          TIME-SLIDER FILTER
        </div>
        <div style={{ display: "grid", gap: "6px" }}>
          <label htmlFor="start-time-range">Start: {formatTimestamp(Math.min(startTs, endTs))}</label>
          <input
            id="start-time-range"
            type="range"
            min={minTs}
            max={maxTs}
            value={Math.min(startTs, endTs)}
            step={1000}
            onChange={(event) => {
              const nextValue = Number(event.target.value);
              setStartTs(nextValue <= endTs ? nextValue : endTs);
            }}
          />
        </div>
        <div style={{ display: "grid", gap: "6px" }}>
          <label htmlFor="end-time-range">End: {formatTimestamp(Math.max(startTs, endTs))}</label>
          <input
            id="end-time-range"
            type="range"
            min={minTs}
            max={maxTs}
            value={Math.max(startTs, endTs)}
            step={1000}
            onChange={(event) => {
              const nextValue = Number(event.target.value);
              setEndTs(nextValue >= startTs ? nextValue : startTs);
            }}
          />
        </div>
        <div style={{ fontSize: "0.85rem", color: "#b4c4d8" }}>
          Showing {filteredEvents.length} of {events.length} events.
        </div>
      </div>
    </section>
  );
}
