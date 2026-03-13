import { C } from "../data/missionControlData";

export default function PhaseCompletionBanner({
  activePhaseIndex,
  onAdvance,
  phase,
  phases,
  progress,
  scrollToTop,
  setOpenStepId,
}) {
  if (progress.completed !== phase.steps.length) {
    return null;
  }

  const nextPhase = phases[activePhaseIndex + 1];

  return (
    <div
      style={{
        marginTop: 14,
        padding: "12px 16px",
        background: "rgba(0,255,136,0.05)",
        border: "1px solid rgba(0,255,136,0.25)",
        borderRadius: 4,
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
    >
      <span style={{ fontSize: 18 }}>✅</span>
      <div style={{ flex: 1 }}>
        <div style={{ color: C.green, fontSize: 11, letterSpacing: 1 }}>
          {phase.title} — COMPLETE
        </div>
        {nextPhase ? (
          <div style={{ color: C.textDim, fontSize: 9, marginTop: 2 }}>
            Next: {nextPhase.title}
          </div>
        ) : null}
      </div>
      {nextPhase ? (
        <button
          onClick={() => {
            onAdvance();
            scrollToTop();
            setOpenStepId(null);
          }}
          style={{
            padding: "6px 16px",
            fontSize: 9,
            fontFamily: "inherit",
            background: `${nextPhase.color}15`,
            border: `1px solid ${nextPhase.color}`,
            color: nextPhase.color,
            cursor: "pointer",
            borderRadius: 2,
            letterSpacing: 1,
          }}
        >
          START {nextPhase.id} →
        </button>
      ) : null}
    </div>
  );
}
