import { startTransition, useDeferredValue, useEffect, useState } from "react";
import TacticalMapView, { type TacticalIntelPoint } from "./TacticalMapView";
import {
  type ApiConflict,
  fetchApiHealth,
  fetchPendingConflicts,
  fetchRecentObservations,
} from "./api";

type ViewTab = "overview" | "map" | "conflicts";

interface DashboardState {
  healthStatus: string;
  healthTimestamp: string;
  conflicts: ApiConflict[];
  events: TacticalIntelPoint[];
  lastUpdatedLabel: string;
}

function formatDateTime(raw: string): string {
  const ts = Date.parse(raw);
  if (!Number.isFinite(ts)) {
    return raw;
  }
  return new Date(ts).toLocaleString();
}

function buildEventsFromObservations(
  observations: Awaited<ReturnType<typeof fetchRecentObservations>>,
): TacticalIntelPoint[] {
  return observations.map((item) => ({
    id: item.observation_id,
    unitType: item.unit_type,
    timestamp: item.observed_at,
    lat: item.lat,
    lon: item.lon,
    label: item.target_id,
    source: item.source_id,
  }));
}

export default function App() {
  const [activeTab, setActiveTab] = useState<ViewTab>("overview");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [state, setState] = useState<DashboardState>({
    healthStatus: "unknown",
    healthTimestamp: "",
    conflicts: [],
    events: [],
    lastUpdatedLabel: "",
  });
  const deferredEvents = useDeferredValue(state.events);

  async function loadDashboard(isRefresh = false): Promise<void> {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setErrorMessage(null);

    try {
      const [health, conflicts, observations] = await Promise.all([
        fetchApiHealth(),
        fetchPendingConflicts(100),
        fetchRecentObservations(250),
      ]);
      const nextState: DashboardState = {
        healthStatus: health.status,
        healthTimestamp: health.time,
        conflicts,
        events: buildEventsFromObservations(observations),
        lastUpdatedLabel: new Date().toLocaleTimeString(),
      };
      startTransition(() => {
        setState(nextState);
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load operational data.";
      setErrorMessage(
        `${message} Configure VITE_SHAKTI_BEARER_TOKEN or VITE_SHAKTI_AUTH_* for /v1 access.`,
      );
    } finally {
      if (isRefresh) {
        setRefreshing(false);
      } else {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    let active = true;
    void loadDashboard(false);
    const interval = setInterval(() => {
      if (active) {
        void loadDashboard(true);
      }
    }, 15000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  const totalSignals = state.events.length;
  const unresolvedConflicts = state.conflicts.length;

  return (
    <main className="app-shell">
      <section className="hero-panel">
        <div className="hero-topbar">
          <div className="eyebrow">Mission Console</div>
          <div className="topbar-actions">
            <button
              className="refresh-button"
              onClick={() => {
                void loadDashboard(true);
              }}
              disabled={refreshing}
            >
              {refreshing ? "Refreshing..." : "Refresh"}
            </button>
          </div>
        </div>
        <h1>SHAKTI Operational Surface</h1>
        <p className="hero-copy">
          API-backed command surface for map telemetry and conflict review. This UI now runs
          against live service endpoints instead of local hardcoded event bundles.
        </p>
        <div className="status-grid">
          <div className="status-card">
            <span>Service Health</span>
            <strong>{state.healthStatus}</strong>
            <small>{state.healthTimestamp ? formatDateTime(state.healthTimestamp) : "N/A"}</small>
          </div>
          <div className="status-card">
            <span>Recent Signals</span>
            <strong>{totalSignals}</strong>
            <small>Live observations feed</small>
          </div>
          <div className="status-card">
            <span>Pending Conflicts</span>
            <strong>{unresolvedConflicts}</strong>
            <small>Manual review queue</small>
          </div>
          <div className="status-card">
            <span>Last Refresh</span>
            <strong>{state.lastUpdatedLabel || "N/A"}</strong>
            <small>Auto-refresh every 15s</small>
          </div>
        </div>
        <nav className="nav-strip" aria-label="Primary">
          <button
            className={activeTab === "overview" ? "nav-button nav-button-active" : "nav-button"}
            onClick={() => startTransition(() => setActiveTab("overview"))}
          >
            Overview
          </button>
          <button
            className={activeTab === "map" ? "nav-button nav-button-active" : "nav-button"}
            onClick={() => startTransition(() => setActiveTab("map"))}
          >
            Tactical Map
          </button>
          <button
            className={activeTab === "conflicts" ? "nav-button nav-button-active" : "nav-button"}
            onClick={() => startTransition(() => setActiveTab("conflicts"))}
          >
            Conflict Queue
          </button>
        </nav>
      </section>

      {loading ? (
        <section className="panel loading-panel">Loading SHAKTI operational feeds...</section>
      ) : null}
      {errorMessage ? <section className="panel error-panel">{errorMessage}</section> : null}

      {!loading && !errorMessage && activeTab === "overview" ? (
        <section className="panel overview-panel">
          <h2>Operational Summary</h2>
          <p>
            Active feed contains <strong>{totalSignals}</strong> recent observations and{" "}
            <strong>{unresolvedConflicts}</strong> pending conflict cases.
          </p>
          <p>
            Use the <strong>Tactical Map</strong> tab for geospatial context and{" "}
            <strong>Conflict Queue</strong> for triage.
          </p>
        </section>
      ) : null}

      {!loading && !errorMessage && activeTab === "map" ? (
        <section className="map-panel">
          <TacticalMapView events={deferredEvents} center={[27.5, 77.0]} zoom={6} />
        </section>
      ) : null}

      {!loading && !errorMessage && activeTab === "conflicts" ? (
        <section className="panel conflicts-panel">
          <h2>Pending Conflicts</h2>
          {state.conflicts.length === 0 ? (
            <div className="empty-state">No pending conflicts found.</div>
          ) : (
            <div className="conflict-list">
              {state.conflicts.map((conflict) => (
                <article key={conflict.conflict_id} className="conflict-item">
                  <div className="conflict-head">
                    <strong>{conflict.target_id}</strong>
                    <span>{conflict.classification_marking}</span>
                  </div>
                  <p>{conflict.conflict_reason}</p>
                  <div className="conflict-meta">
                    <span>Status: {conflict.status}</span>
                    <span>Distance: {conflict.distance_meters.toFixed(1)}m</span>
                    <span>Created: {formatDateTime(conflict.created_at)}</span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      ) : null}
    </main>
  );
}
