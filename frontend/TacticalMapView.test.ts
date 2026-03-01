import { buildUnitIconSvg, filterEventsByTimeRange, type TacticalIntelPoint } from "./TacticalMapView";

describe("TacticalMapView helpers", () => {
  const events: TacticalIntelPoint[] = [
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

  test("filters events by timestamp range", () => {
    const start = new Date("2026-03-01T10:05:00Z").getTime();
    const end = new Date("2026-03-01T10:30:00Z").getTime();
    const filtered = filterEventsByTimeRange(events, start, end);

    expect(filtered).toHaveLength(1);
    expect(filtered[0].id).toBe("2");
  });

  test("returns stable SVG marker for hostile units", () => {
    const svg = buildUnitIconSvg("HOSTILE");
    expect(svg).toContain("<svg");
    expect(svg).toContain("#c72828");
  });
});

