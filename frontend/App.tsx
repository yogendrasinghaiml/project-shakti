import TacticalMapView, { type TacticalIntelPoint } from "./TacticalMapView";

const demoEvents: TacticalIntelPoint[] = [
  {
    id: "evt-001",
    unitType: "FRIENDLY",
    timestamp: "2026-03-01T10:00:00Z",
    lat: 28.6139,
    lon: 77.209,
    label: "Blue Unit 1",
    source: "SATCOM",
  },
  {
    id: "evt-002",
    unitType: "HOSTILE",
    timestamp: "2026-03-01T10:12:00Z",
    lat: 28.7041,
    lon: 77.1025,
    label: "Red Unit 7",
    source: "ISR DRONE",
  },
  {
    id: "evt-003",
    unitType: "UNKNOWN",
    timestamp: "2026-03-01T10:31:00Z",
    lat: 27.1767,
    lon: 78.0081,
    label: "Unknown Contact",
    source: "FIELD RELAY",
  },
  {
    id: "evt-004",
    unitType: "HOSTILE",
    timestamp: "2026-03-01T10:52:00Z",
    lat: 26.9124,
    lon: 75.7873,
    label: "Red Convoy",
    source: "HUMINT",
  },
];

export default function App() {
  return (
    <main className="app-shell">
      <section className="hero-panel">
        <div>
          <div className="eyebrow">Mission Console</div>
          <h1>Local Tactical Map Sandbox</h1>
          <p className="hero-copy">
            A self-contained frontend harness for the SHAKTI tactical view. It is wired for
            local tiles by default and safe to run inside CI or an offline operations network.
          </p>
        </div>
        <div className="status-grid">
          <div className="status-card">
            <span>Event Feed</span>
            <strong>{demoEvents.length} signals loaded</strong>
          </div>
          <div className="status-card">
            <span>Display Mode</span>
            <strong>Local tile cache</strong>
          </div>
          <div className="status-card">
            <span>UI Surface</span>
            <strong>Vite + React</strong>
          </div>
        </div>
      </section>

      <section className="map-panel">
        <TacticalMapView events={demoEvents} center={[27.5, 77.0]} zoom={6} />
      </section>
    </main>
  );
}
