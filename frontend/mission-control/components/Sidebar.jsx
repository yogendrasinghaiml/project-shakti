import { C } from "../data/missionControlData";
import { getPhaseProgress } from "../progress";

export default function Sidebar({
  activePhaseIndex,
  doneCount,
  doneMap,
  phases,
  scrollToTop,
  setActivePhaseIndex,
  setOpenStepId,
  totalSteps,
}) {
  return (
    <div
      style={{
        width: 220,
        background: C.panel,
        borderRight: `1px solid ${C.border}`,
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
      }}
    >
      <div style={{ padding: "14px 12px 10px", borderBottom: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 15, color: C.cyan, letterSpacing: 3, fontWeight: "bold" }}>
          ▓ SHAKTI V3
        </div>
        <div style={{ fontSize: 8, color: C.textDim, letterSpacing: 2, marginTop: 2 }}>
          IMPLEMENTATION GUIDE
        </div>
        <div style={{ marginTop: 10 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 8,
              color: C.textDim,
              marginBottom: 3,
            }}
          >
            <span>MISSION PROGRESS</span>
            <span style={{ color: C.cyan }}>
              {doneCount}/{totalSteps}
            </span>
          </div>
          <div style={{ height: 3, background: C.border, borderRadius: 2 }}>
            <div
              style={{
                height: "100%",
                width: `${Math.round((doneCount / totalSteps) * 100)}%`,
                background: C.cyan,
                borderRadius: 2,
                transition: "width 0.3s",
              }}
            />
          </div>
          <div style={{ textAlign: "right", fontSize: 8, color: C.cyan, marginTop: 2 }}>
            {Math.round((doneCount / totalSteps) * 100)}%
          </div>
        </div>
      </div>

      <div style={{ flex: 1, overflowY: "auto" }}>
        {phases.map((phase, phaseIndex) => {
          const progress = getPhaseProgress(phase, doneMap);
          const isActive = activePhaseIndex === phaseIndex;

          return (
            <div
              key={phase.id}
              onClick={() => {
                setActivePhaseIndex(phaseIndex);
                scrollToTop();
                setOpenStepId(null);
              }}
              style={{
                padding: "9px 12px",
                cursor: "pointer",
                borderLeft: `3px solid ${isActive ? phase.color : "transparent"}`,
                background: isActive ? `${phase.color}12` : "transparent",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ fontSize: 13 }}>{phase.icon}</span>
                <div style={{ flex: 1 }}>
                  <div
                    style={{
                      fontSize: 9,
                      color: isActive ? phase.color : C.textSec,
                      fontWeight: isActive ? "bold" : "normal",
                      letterSpacing: 0.5,
                    }}
                  >
                    {phase.id}
                  </div>
                  <div style={{ fontSize: 8, color: C.textDim }}>
                    {progress.completed}/{progress.total} done
                  </div>
                </div>
                {progress.completed === progress.total ? (
                  <span style={{ color: C.green, fontSize: 10 }}>✓</span>
                ) : null}
              </div>
              <div style={{ height: 2, background: C.border, borderRadius: 1, marginTop: 5 }}>
                <div
                  style={{
                    height: "100%",
                    width: `${progress.pct}%`,
                    background: phase.color,
                    borderRadius: 1,
                    opacity: 0.6,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
