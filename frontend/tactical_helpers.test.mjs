import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Buffer } from "node:buffer";

function loadHelpersFromTypeScriptSource() {
  const tsPath = new URL("./tactical_helpers.ts", import.meta.url);
  const source = readFileSync(tsPath, "utf8");
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
  return import(moduleUrl);
}

const {
  buildUnitIconSvg,
  filterEventsByTimeRange,
  normalizeUnitType,
  getUnitStyle,
} = await loadHelpersFromTypeScriptSource();

const events = [
  {
    id: "1",
    unitType: "FRIENDLY",
    timestamp: "2026-03-01T10:00:00Z",
    lat: 28.6139,
    lon: 77.209,
    label: "Blue Unit 1",
  },
  {
    id: "2",
    unitType: "HOSTILE",
    timestamp: "2026-03-01T10:15:00Z",
    lat: 28.7041,
    lon: 77.1025,
    label: "Red Unit 7",
  },
  {
    id: "3",
    unitType: "UNKNOWN",
    timestamp: "2026-03-01T10:45:00Z",
    lat: 27.1767,
    lon: 78.0081,
    label: "Unknown Contact",
  },
];

test("filters events by inclusive timestamp range", () => {
  const start = new Date("2026-03-01T10:05:00Z").getTime();
  const end = new Date("2026-03-01T10:30:00Z").getTime();
  const filtered = filterEventsByTimeRange(events, start, end);
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].id, "2");
});

test("includes start and end boundary timestamps", () => {
  const start = new Date("2026-03-01T10:00:00Z").getTime();
  const end = new Date("2026-03-01T10:45:00Z").getTime();
  const filtered = filterEventsByTimeRange(events, start, end);
  assert.equal(filtered.length, 3);
});

test("drops events with invalid timestamps from filtered output", () => {
  const withInvalid = events.concat({
    id: "invalid",
    unitType: "UNKNOWN",
    timestamp: "not-a-time",
    lat: 0,
    lon: 0,
    label: "bad",
  });
  const start = new Date("2026-03-01T09:00:00Z").getTime();
  const end = new Date("2026-03-01T11:00:00Z").getTime();
  const filtered = filterEventsByTimeRange(withInvalid, start, end);
  assert.equal(filtered.length, 3);
  assert.equal(filtered.some((event) => event.id === "invalid"), false);
});

test("builds stable hostile marker SVG", () => {
  const svg = buildUnitIconSvg("HOSTILE");
  assert.equal(svg.includes("<svg"), true);
  assert.equal(svg.includes("#c72828"), true);
});

test("normalizes unsupported unit types to UNKNOWN style", () => {
  const normalized = normalizeUnitType("NEUTRAL");
  assert.equal(normalized, "UNKNOWN");
  const style = getUnitStyle("NEUTRAL");
  assert.equal(style.fill, "#c48a1d");
  const svg = buildUnitIconSvg("NEUTRAL");
  assert.equal(svg.includes("#c48a1d"), true);
});
