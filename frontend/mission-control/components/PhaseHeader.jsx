import { C } from "../data/missionControlData";

export default function PhaseHeader({
  activePhaseIndex,
  onNextPhase,
  onPreviousPhase,
  phases,
  phase,
  scrollToTop,
}) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 8, color: C.textDim, letterSpacing: 3, marginBottom: 3 }}>
        PHASE {activePhaseIndex + 1} OF {phases.length}
      </div>
      <div style={{ fontSize: 20, color: phase.color, letterSpacing: 2, marginBottom: 5 }}>
        {phase.icon} {phase.title}
      </div>
      <div
        style={{
          fontSize: 11,
          color: C.textSec,
          marginBottom: 14,
          lineHeight: 1.6,
          maxWidth: 640,
        }}
      >
        {phase.subtitle}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={() => {
            onPreviousPhase();
            scrollToTop();
          }}
          disabled={activePhaseIndex === 0}
          style={{
            padding: "5px 14px",
            background: "transparent",
            border: `1px solid ${activePhaseIndex === 0 ? C.border : C.borderBright}`,
            color: activePhaseIndex === 0 ? C.textDim : C.textSec,
            cursor: activePhaseIndex === 0 ? "not-allowed" : "pointer",
            fontSize: 9,
            fontFamily: "inherit",
            borderRadius: 2,
            letterSpacing: 1,
          }}
        >
          ← PREV
        </button>
        <button
          onClick={() => {
            onNextPhase();
            scrollToTop();
          }}
          disabled={activePhaseIndex === phases.length - 1}
          style={{
            padding: "5px 14px",
            background: `${phase.color}15`,
            border: `1px solid ${phase.color}70`,
            color: phase.color,
            cursor: activePhaseIndex === phases.length - 1 ? "not-allowed" : "pointer",
            fontSize: 9,
            fontFamily: "inherit",
            borderRadius: 2,
            letterSpacing: 1,
          }}
        >
          NEXT →
        </button>
      </div>
    </div>
  );
}
